# FXCM market-data bridge for Linux. ForexConnect ships a manylinux1 wheel for CPython 3.7 only,
# and its native libs expect OpenSSL 1.1 -> Debian bullseye (not bookworm, which only has OpenSSL 3).
# Railway: create a service from this repo with Root Directory = fxcm_bridge.
FROM python:3.7-slim-bullseye
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt && python -c "from forexconnect import ForexConnect, fxcorepy; print('forexconnect import OK')"
COPY bridge.py .
# Config comes from environment variables (FXCM_USERNAME, FXCM_PASSWORD, FXCM_CONNECTION, FXCM_URL, FXCM_SYMBOLS, DATABASE_URL).
CMD ["python", "-u", "bridge.py"]
