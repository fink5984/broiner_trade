"""FXCM ForexConnect market-data bridge (Python 3.7 — ForexConnect wheels exist only up to cp37 on Windows).

Runs as an isolated process. Logs in to the FXCM *demo* account, then:
  * backfills candles (m5, m15, H1, H4, D1) and keeps them fresh,
  * stores live Bid/Ask quotes from the Offers table,
  * records connector status in data_sources / ingestion_runs.
It only READS market data. It never places orders: trading goes through the backend's broker adapters.

Config comes from backend/.env: FXCM_USERNAME, FXCM_PASSWORD, FXCM_CONNECTION (Demo), FXCM_URL, DATABASE_URL.
Python 3.7 syntax only (no walrus, no builtin generics).
"""
import datetime as dt
import json
import logging
import os
import sys
import threading
import time
import uuid

import psycopg2
from dotenv import dotenv_values

SOURCE = "fxcm-demo"
TIMEFRAMES = {"m5": 5, "m15": 15, "H1": 60, "H4": 240, "D1": 1440}  # FXCM timeframe -> minutes
BACKFILL = {"m5": 3, "m15": 10, "H1": 40, "H4": 160, "D1": 900}       # days of history per timeframe
DEFAULT_SYMBOLS = "USD/ILS,GBP/USD,EUR/USD,XAU/USD,XAG/USD,USOil,UKOil,NGAS,Copper"  # GBP/ILS, EUR/ILS not offered on this demo account
QUOTE_EVERY = 1       # seconds between quote snapshots (own thread)
CANDLE_EVERY = 60     # seconds between candle refreshes

log = logging.getLogger("fxcm_bridge")


def utcnow():
    return dt.datetime.now(dt.timezone.utc)


def load_config():
    here = os.path.dirname(os.path.abspath(__file__))
    env = dotenv_values(os.path.join(here, "..", "backend", ".env"))
    env.update({k: v for k, v in os.environ.items() if k.startswith("FXCM_") or k == "DATABASE_URL"})
    missing = [k for k in ("FXCM_USERNAME", "FXCM_PASSWORD", "DATABASE_URL") if not env.get(k)]
    if missing:
        sys.exit("missing config: " + ", ".join(missing))
    env["DATABASE_URL"] = env["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://")
    return env


def our_symbol(fx_symbol):
    return fx_symbol.replace("/", "").upper()


class Store(object):
    def __init__(self, url):
        self.url = url
        self.conn = None
        self.inst_ids = {}
        self.source_id = None

    def connect(self):
        self.conn = psycopg2.connect(self.url)
        self.conn.autocommit = True
        with self.conn.cursor() as c:
            c.execute("SELECT id FROM data_sources WHERE name=%s", ("FXCM Demo",))
            row = c.fetchone()
            if row:
                self.source_id = row[0]
            else:
                self.source_id = str(uuid.uuid4())
                c.execute("INSERT INTO data_sources (id,name,kind,url,enabled,poll_seconds,config,status) "
                          "VALUES (%s,'FXCM Demo','market',%s,true,%s,%s,'starting')",
                          (self.source_id, "ForexConnect Demo", QUOTE_EVERY, json.dumps({})))

    def status(self, status, config=None, success=False):
        with self.conn.cursor() as c:
            c.execute("UPDATE data_sources SET status=%s, config=COALESCE(%s::jsonb, config), "
                      "last_success_at=CASE WHEN %s THEN now() ELSE last_success_at END WHERE id=%s",
                      (status, json.dumps(config) if config is not None else None, success, self.source_id))

    def run_log(self, received, new, error=None):
        with self.conn.cursor() as c:
            c.execute("INSERT INTO ingestion_runs (id,source_id,started_at,finished_at,items_received,items_new,error) "
                      "VALUES (%s,%s,now(),now(),%s,%s,%s)", (str(uuid.uuid4()), self.source_id, received, new, error))

    def instrument(self, symbol, base, quote, kind):
        if symbol in self.inst_ids:
            return self.inst_ids[symbol]
        with self.conn.cursor() as c:
            c.execute("SELECT id FROM instruments WHERE symbol=%s", (symbol,))
            row = c.fetchone()
            if row:
                iid = row[0]
            else:
                iid = str(uuid.uuid4())
                c.execute("INSERT INTO instruments (id,symbol,base,quote,kind,min_units,unit_step,max_spread,enabled) "
                          "VALUES (%s,%s,%s,%s,%s,1000,1000,0.05,true)", (iid, symbol, base, quote, kind))
        self.inst_ids[symbol] = iid
        return iid

    def candles(self, iid, tf, rows):
        """rows: list of (open_time, o, h, l, c, volume, complete). Upsert; returns number written."""
        if not rows:
            return 0
        with self.conn.cursor() as c:
            for r in rows:
                c.execute(
                    "INSERT INTO market_candles (id,instrument_id,timeframe,source,open_time,open,high,low,close,volume,is_complete,is_synthetic) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,false) "
                    "ON CONFLICT (instrument_id,timeframe,source,open_time) DO UPDATE SET "
                    "open=EXCLUDED.open, high=EXCLUDED.high, low=EXCLUDED.low, close=EXCLUDED.close, "
                    "volume=EXCLUDED.volume, is_complete=EXCLUDED.is_complete",
                    (str(uuid.uuid4()), iid, tf, SOURCE) + tuple(r))
        return len(rows)

    def candle_count(self, iid, tf):
        with self.conn.cursor() as c:
            c.execute("SELECT count(*) FROM market_candles WHERE instrument_id=%s AND timeframe=%s AND source=%s", (iid, tf, SOURCE))
            return c.fetchone()[0]

    def quote(self, iid, ts, bid, ask):
        with self.conn.cursor() as c:
            c.execute("INSERT INTO market_quotes (id,instrument_id,source,ts,bid,ask) VALUES (%s,%s,%s,%s,%s,%s) "
                      "ON CONFLICT DO NOTHING", (str(uuid.uuid4()), iid, SOURCE, ts, bid, ask))


def fetch_history(fx, symbol, tf, start, end, max_bars=300):
    """Candles via a MarketDataSnapshot request on the trading session.

    fx.get_history() uses the separate price-archive server (QuotesManager), which fails behind
    TLS-inspecting networks (errorCode=60). The snapshot request travels over the already-authenticated
    trading connection. Pages backwards in chunks of `max_bars`. Returns raw tuples ordered by time:
    (open_time_utc, bid_open, bid_high, bid_low, bid_close, volume)."""
    from forexconnect import fxcorepy
    rf = fx.session.request_factory
    timeframe = rf.timeframe_collection.get(tf)
    out = {}
    cursor = end
    while cursor > start:
        req = rf.create_market_data_snapshot_request_instrument(symbol, timeframe, max_bars)
        rf.fill_market_data_snapshot_request_time(req, start, cursor, False, fxcorepy.O2GCandleOpenPriceMode.PREVIOUS_CLOSE)
        rd = fx.send_request(req)  # returns an O2GMarketDataSnapshotResponseReader
        if rd.size == 0:
            break
        for i in range(rd.size):
            t = rd.get_date(i)
            out[t] = (t, rd.get_bid_open(i), rd.get_bid_high(i), rd.get_bid_low(i), rd.get_bid_close(i), rd.get_volume(i))
        earliest = rd.get_date(0)
        if rd.size < max_bars or earliest >= cursor:
            break
        cursor = earliest - dt.timedelta(seconds=1)
    return [out[k] for k in sorted(out)]


def history_rows(data, tf_minutes, now):
    """Convert fetched candles to DB rows (BID prices). A candle still forming
    (open_time + tf > now) is flagged incomplete and is never used for signals."""
    rows = []
    for t, o, h, l, c, vol in data:
        ts = t.replace(tzinfo=dt.timezone.utc) if t.tzinfo is None else t
        o, h, l, c = float(o), float(h), float(l), float(c)
        if not (h >= max(o, c) and l <= min(o, c) and l > 0):
            continue  # reject malformed candle
        complete = ts + dt.timedelta(minutes=tf_minutes) <= now
        rows.append((ts, o, h, l, c, float(vol) if vol is not None else None, complete))
    return rows


def run(cfg):
    from forexconnect import ForexConnect, fxcorepy  # imported late so --help works without the SDK
    if cfg.get("FXCM_CA_BUNDLE"):
        fxcorepy.O2GTransport.set_ca_info(os.path.abspath(cfg["FXCM_CA_BUNDLE"]))

    symbols = [s.strip() for s in cfg.get("FXCM_SYMBOLS", DEFAULT_SYMBOLS).split(",") if s.strip()]
    store = Store(cfg["DATABASE_URL"])
    store.connect()
    store.status("connecting")
    with ForexConnect() as fx:
        fx.login(cfg["FXCM_USERNAME"], cfg["FXCM_PASSWORD"], cfg.get("FXCM_URL", "http://www.fxcorporate.com/Hosts.jsp"),
                 cfg.get("FXCM_CONNECTION", "Demo"))
        log.info("logged in to FXCM %s", cfg.get("FXCM_CONNECTION", "Demo"))

        offers = fx.get_table(ForexConnect.OFFERS)
        available = {row.instrument for row in offers}
        active = [s for s in symbols if s in available]
        missing = [s for s in symbols if s not in available]
        if missing:
            log.warning("not offered on this account: %s", ", ".join(missing))
        ensure_price_subscription(fx, fxcorepy, offers, active)
        store.status("connected", {"symbols": active, "unavailable": missing, "account": "demo"}, success=True)

        for s in active:
            base, _, quote = s.partition("/")
            store.instrument(our_symbol(s), base, quote or "USD",
                             "metal" if s.startswith(("XAU", "XAG")) else ("fx" if quote else "commodity"))
        # Live quotes start immediately; history backfill runs one (symbol, timeframe) job per loop.
        # The 15m chart timeframe goes first for every symbol so the UI gets usable candles soonest.
        order = ["m15", "H1", "m5", "H4", "D1"]
        backfill_jobs = [(s, tf) for tf in order for s in active]
        # Empty series first (new symbols), already-filled ones (cheap top-up only) last. Stable sort keeps the tf order.
        backfill_jobs.sort(key=lambda j: store.candle_count(store.inst_ids[our_symbol(j[0])], j[1]) >= 200)
        last_candles = dict((s, time.time()) for s in active)

        stop = threading.Event()
        quoter = threading.Thread(target=quote_loop, name="quotes", daemon=True,
                                  args=(fx, ForexConnect.OFFERS, cfg["DATABASE_URL"], dict(store.inst_ids), active, stop))
        quoter.start()
        try:
            candle_loop(fx, store, active, backfill_jobs, last_candles, quoter)
        finally:
            stop.set()
            quoter.join(5)


def ensure_price_subscription(fx, fxcorepy, offers, active):
    """Offers with subscription status 'D' (disabled) get only a login-time snapshot and never stream.
    Switch those to 'V' (view only: live prices, no trading) so their quotes update in real time.
    This is a market-data subscription setting, not an order."""
    rf = fx.session.request_factory
    for row in offers:
        if row.instrument not in active or getattr(row, "subscription_status", "") in ("T", "V"):
            continue
        try:
            vm = rf.create_value_map()
            vm.set_string(fxcorepy.O2GRequestParamsEnum.COMMAND, fxcorepy.Constants.Commands.SET_SUBSCRIPTION_STATUS)
            vm.set_string(fxcorepy.O2GRequestParamsEnum.SUBSCRIPTION_STATUS, "V")
            vm.set_string(fxcorepy.O2GRequestParamsEnum.OFFER_ID, row.offer_id)
            fx.send_request(rf.create_order_request(vm))
            log.info("subscribed %s to live prices (status %s -> V)", row.instrument, row.subscription_status)
        except Exception as e:
            log.warning("could not subscribe %s to live prices: %s", row.instrument, e)


def quote_loop(fx, offers_table, db_url, inst_ids, active, stop):
    """Writes changed Bid/Ask quotes every QUOTE_EVERY seconds on its own DB connection,
    so slow history requests on the main thread never freeze live prices."""
    from psycopg2.extras import execute_values
    store = Store(db_url)
    store.connect()
    last_ts = {}
    last_status = 0.0
    last_diag = 0.0
    while not stop.is_set():
        t0 = time.time()
        try:
            batch = []
            rows = list(fx.get_table(offers_table))
            if time.time() - last_diag > 300:
                last_diag = time.time()
                for row in rows:
                    if row.instrument in active:
                        log.info("offer %s time=%s bid=%s ask=%s sub=%s", row.instrument, row.time, row.bid, row.ask,
                                 getattr(row, "subscription_status", "?"))
            for row in rows:
                if row.instrument not in active:
                    continue
                ts = row.time.replace(tzinfo=dt.timezone.utc) if row.time.tzinfo is None else row.time
                if last_ts.get(row.instrument) == ts or row.bid <= 0 or row.ask < row.bid:
                    continue
                batch.append((str(uuid.uuid4()), inst_ids[our_symbol(row.instrument)], SOURCE, ts, float(row.bid), float(row.ask)))
                last_ts[row.instrument] = ts
            if batch:
                with store.conn.cursor() as c:
                    execute_values(c, "INSERT INTO market_quotes (id,instrument_id,source,ts,bid,ask) VALUES %s ON CONFLICT DO NOTHING", batch)
            if time.time() - last_status > 10:
                store.status("connected", success=True)
                last_status = time.time()
        except Exception:
            log.exception("quote loop error; reconnecting DB")
            try:
                store.connect()
            except Exception:
                time.sleep(5)
        stop.wait(max(0.0, QUOTE_EVERY - (time.time() - t0)))


# How often the most recent candles (incl. the one still forming) are re-fetched, per timeframe.
REFRESH_SECONDS = {"m5": 30, "m15": 30, "H1": 120, "H4": 600, "D1": 1800}


def refresh_recent(fx, store, active, last_refresh):
    """Re-fetch the last few candles of every due (symbol, timeframe). Runs before any backfill job,
    so charts never lag behind live quotes while history is still loading."""
    did = False
    for tf, secs in REFRESH_SECONDS.items():
        for s in active:
            key = (s, tf)
            if time.time() - last_refresh.get(key, 0) < secs:
                continue
            now = utcnow()
            try:
                start = now.replace(tzinfo=None) - dt.timedelta(minutes=TIMEFRAMES[tf] * 4)
                data = fetch_history(fx, s, tf, start, now.replace(tzinfo=None), max_bars=10)
                store.candles(store.inst_ids[our_symbol(s)], tf, history_rows(data, TIMEFRAMES[tf], now))
            except Exception:
                log.exception("refresh failed %s %s", s, tf)
            last_refresh[key] = time.time()
            did = True
    return did


def candle_loop(fx, store, active, backfill_jobs, last_candles, quoter):
    last_refresh = {}
    while quoter.is_alive():
        now = utcnow()
        if refresh_recent(fx, store, active, last_refresh):
            continue
        if backfill_jobs:
            s, tf = backfill_jobs.pop(0)
            try:
                end = utcnow().replace(tzinfo=None)
                have = store.candle_count(store.inst_ids[our_symbol(s)], tf)
                days = BACKFILL[tf] if have < 200 else max(1, TIMEFRAMES[tf] * 300 // 1440)  # top-up only if already filled
                data = fetch_history(fx, s, tf, end - dt.timedelta(days=days), end)
                n = store.candles(store.inst_ids[our_symbol(s)], tf, history_rows(data, TIMEFRAMES[tf], utcnow()))
                store.run_log(len(data), n)
                log.info("backfill %s %s: %d candles (%d jobs left)", s, tf, n, len(backfill_jobs))
            except Exception as e:  # keep going with other symbols/timeframes
                store.run_log(0, 0, "backfill %s %s: %s" % (s, tf, e))
                log.exception("backfill failed %s %s", s, tf)
            continue
        time.sleep(1)
    raise RuntimeError("quote thread stopped")


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = load_config()
    backoff = 5
    while True:  # reconnect forever with capped backoff; status is visible in the UI
        try:
            run(cfg)
        except KeyboardInterrupt:
            return
        except Exception as e:
            log.exception("bridge error; reconnecting in %ss", backoff)
            try:
                s = Store(cfg["DATABASE_URL"]); s.connect(); s.status("error: %s" % str(e)[:180]); s.run_log(0, 0, str(e)[:500])
            except Exception:
                pass
            time.sleep(backoff)
            backoff = min(backoff * 2, 300)


if __name__ == "__main__":
    main()
