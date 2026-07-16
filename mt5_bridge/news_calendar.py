"""Shared prop-firm news-blackout logic.

Imported by both app_server.py (fetches the calendar once/day and writes
NEWS_WINDOWS_FILE) and mt5_worker.py (reads NEWS_WINDOWS_FILE at trade-copy
time). The two run as separate OS processes with no shared memory, so this
file only holds pure logic + the JSON file is the actual communication
channel between them, mirroring the existing ticket_map_<id>.json pattern.
"""

import os
import json
import time
import datetime
import requests

NEWS_WINDOWS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "news_windows.json")

FF_CALENDAR_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"

# Instruments whose ticker doesn't literally contain the currency code they're
# tied to for news-restriction purposes (e.g. FTMO blocks US30/NAS100/SPX500
# during USD news, UK100 during GBP news). Extend here as needed.
CURRENCY_ALIASES = {
    "US30": "USD", "DJ30": "USD", "NAS100": "USD", "US100": "USD", "USTEC": "USD",
    "SPX500": "USD", "US500": "USD",
    "UK100": "GBP",
    "GER40": "EUR", "GER30": "EUR", "DE40": "EUR", "FRA40": "EUR", "EU50": "EUR",
    "JPN225": "JPY", "NIKKEI225": "JPY",
    "AUS200": "AUD",
}


def fetch_raw_calendar(timeout: float = 10.0) -> list:
    """GET the ForexFactory-derived weekly calendar feed. Raises on any failure."""
    resp = requests.get(FF_CALENDAR_URL, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def filter_high_impact(raw_events: list) -> list:
    return [e for e in raw_events if e.get("impact") == "High"]


def parse_ff_timestamp_to_epoch(date_str: str) -> int:
    """Feed timestamps carry an explicit UTC offset, e.g. '2026-07-06T10:00:00-04:00'.
    Parsing + converting to epoch here means the local PC's timezone setting
    never matters again for any later comparison, only its clock accuracy."""
    dt = datetime.datetime.fromisoformat(date_str)
    return int(dt.timestamp())


def filter_today(events: list) -> list:
    """Keep only events whose local calendar day matches today. This is a
    single-user desktop app running on the user's own PC, so local date is
    what "today" intuitively means here."""
    today = datetime.datetime.now().date()
    kept = []
    for e in events:
        try:
            epoch = parse_ff_timestamp_to_epoch(e["date"])
        except (KeyError, ValueError):
            continue
        if datetime.datetime.fromtimestamp(epoch).date() == today:
            kept.append(e)
    return kept


def _build_window(title: str, currency: str, event_time: int, half_width_sec: int) -> dict:
    return {
        "title": title,
        "currency": currency,
        "event_time": event_time,
        "start": event_time - half_width_sec,
        "end": event_time + half_width_sec,
    }


def events_to_windows(events: list, half_width_sec: int = 120) -> list:
    windows = []
    for e in events:
        try:
            epoch = parse_ff_timestamp_to_epoch(e["date"])
        except (KeyError, ValueError):
            continue
        windows.append(_build_window(e.get("title", ""), e.get("country", ""), epoch, half_width_sec))
    return windows


def epoch_from_local_and_offset(date_str: str, offset_minutes: int) -> int:
    """Manual-entry form helper. date_str is a naive 'YYYY-MM-DDTHH:MM' value
    (as produced by an HTML datetime-local input, no offset baked in);
    offset_minutes is the UTC offset the user says that wall-clock time is in."""
    naive = datetime.datetime.fromisoformat(date_str)
    tz = datetime.timezone(datetime.timedelta(minutes=offset_minutes))
    aware = naive.replace(tzinfo=tz)
    return int(aware.timestamp())


def manual_events_to_windows(entries: list, half_width_sec: int = 120) -> list:
    windows = []
    for entry in entries:
        try:
            epoch = epoch_from_local_and_offset(entry["date"], int(entry.get("offset_minutes", 0)))
        except (KeyError, ValueError):
            continue
        windows.append(_build_window(entry.get("title", ""), entry.get("currency", ""), epoch, half_width_sec))
    return windows


def symbol_matches_currency(symbol: str, currency: str) -> bool:
    if not symbol or not currency:
        return False
    symbol = symbol.upper()
    currency = currency.upper()
    if currency in symbol:
        return True
    for alias, alias_currency in CURRENCY_ALIASES.items():
        if alias_currency == currency and symbol.startswith(alias):
            return True
    return False


def is_blocked_now(symbol: str, windows_payload: dict, now_epoch: float = None,
                    before_sec: float = None, after_sec: float = None):
    """Hot path: zero I/O, numeric loop over a small in-memory list.
    Returns (blocked: bool, window: dict|None). window is None either when
    not blocked, or when blocked because the feed status is FAILED (fail
    closed unconditionally, not tied to any specific event).

    before_sec/after_sec let a caller (a specific prop-firm instance) apply
    its OWN blackout width instead of the window's precomputed start/end —
    different prop firms restrict different amounts of time around news.
    Pass None for either to fall back to the precomputed value."""
    if windows_payload.get("status") == "FAILED":
        return True, None

    now_epoch = time.time() if now_epoch is None else now_epoch
    for w in windows_payload.get("events", []):
        start = (w["event_time"] - before_sec) if before_sec is not None else w["start"]
        end = (w["event_time"] + after_sec) if after_sec is not None else w["end"]
        if start <= now_epoch <= end and symbol_matches_currency(symbol, w["currency"]):
            return True, w
    return False, None


def _empty_failed_payload() -> dict:
    return {"status": "FAILED", "date": "", "fetched_at": 0, "events": []}


def load_windows_file(path: str = NEWS_WINDOWS_FILE) -> dict:
    """Fail CLOSED by default: a missing/corrupt file must not silently mean
    'no restrictions' the way ticket_map's fail-open {} default does."""
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return _empty_failed_payload()


def save_windows_file(payload: dict, path: str = NEWS_WINDOWS_FILE) -> None:
    with open(path, "w") as f:
        json.dump(payload, f)


def get_cached_windows(cache_state: dict, throttle_sec: float = 2.0, path: str = NEWS_WINDOWS_FILE) -> dict:
    """Cheap reload for the CONSUMER hot path. cache_state is a caller-owned
    mutable dict (pass {} at loop start) that persists across calls. Only
    stats the file once per throttle_sec, and only re-parses JSON if the
    file's mtime actually changed."""
    now = time.time()
    if "data" in cache_state and (now - cache_state.get("last_check", 0)) < throttle_sec:
        return cache_state["data"]

    cache_state["last_check"] = now
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        mtime = None

    if "data" not in cache_state or mtime != cache_state.get("mtime"):
        cache_state["data"] = load_windows_file(path)
        cache_state["mtime"] = mtime

    return cache_state["data"]
