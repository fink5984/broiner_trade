"""GDELT DOC 2.0 article list (keyless). GDELT allows one request per 5 seconds; HTTP 429 is surfaced as an error."""
from __future__ import annotations

from datetime import datetime, timezone

import httpx

from .common import RawArticle, TIMEOUT, USER_AGENT

NAME = "GDELT"
URL = "https://api.gdeltproject.org/api/v2/doc/doc"
POLL_SECONDS = 900
QUERY = '("interest rate" OR inflation OR "central bank" OR forex OR currency OR shekel OR "gold price") sourcelang:eng'


def fetch(client: httpx.Client | None = None) -> dict:
    own = client is None
    client = client or httpx.Client(timeout=TIMEOUT, headers={"User-Agent": USER_AGENT})
    try:
        r = client.get(URL, params={"query": QUERY, "mode": "artlist", "format": "json", "maxrecords": 75,
                                    "timespan": "2h", "sort": "datedesc"})
        r.raise_for_status()
        return r.json()
    finally:
        if own:
            client.close()


def parse(payload: dict) -> list[RawArticle]:
    out = []
    for a in payload.get("articles", []):
        try:
            t = datetime.strptime(a["seendate"], "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        except (KeyError, ValueError):
            continue
        if a.get("url") and a.get("title"):
            out.append(RawArticle(a["url"], a["title"], t))
    return out
