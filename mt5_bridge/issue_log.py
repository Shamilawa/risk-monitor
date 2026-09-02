"""Append-only, human-readable issue log under mt5_bridge/logs/issues_<date>.txt.

This is the curated record you read weeks later to find a pattern -- NOT the raw
firehose. Raw subprocess output goes to logs/worker_<id>.log separately.

Single-writer by design. Issues originate in two different processes (the
reconciler inside app_server.py, and the mt5_worker.py consumer subprocesses),
and two processes appending to one file on Windows will interleave and corrupt
lines. So workers never touch this file: they report outcomes over localhost
HTTP to app_server.py, which is the only writer, serialised behind _lock.

Every write is append + flush, because a power cut is exactly when you want the
last line to have survived. Nothing in here may ever raise into the trading
path -- all IO is wrapped and failures are swallowed.

Dates and timestamps are LOCAL time (not UTC like the rest of the app): this
file exists for a human asking "what broke on Tuesday", and Tuesday means the
local one.
"""
import os
import re
import threading
from datetime import datetime, timedelta

LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs')
RETENTION_DAYS = 90

_lock = threading.Lock()
# Date string of the file we last wrote to, so a rollover can footer the old file.
_current_date = None

_FILE_RE = re.compile(r'^issues_(\d{4}-\d{2}-\d{2})\.txt$')


def _today():
    return datetime.now().strftime("%Y-%m-%d")


def _path_for(date_str):
    return os.path.join(LOG_DIR, f"issues_{date_str}.txt")


def _raw_append(date_str, text):
    """Write with no locking and no rollover logic. Callers must hold _lock."""
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        with open(_path_for(date_str), 'a', encoding='utf-8') as f:
            f.write(text)
            f.flush()
    except Exception:
        pass


def _purge_old():
    """Drop issue logs past retention. Callers must hold _lock."""
    try:
        cutoff = (datetime.now() - timedelta(days=RETENTION_DAYS)).strftime("%Y-%m-%d")
        for name in os.listdir(LOG_DIR):
            m = _FILE_RE.match(name)
            if m and m.group(1) < cutoff:
                try:
                    os.remove(os.path.join(LOG_DIR, name))
                except Exception:
                    pass
    except Exception:
        pass


def _write(text):
    """Append to today's file, footering yesterday's on a date rollover."""
    global _current_date
    date_str = _today()
    with _lock:
        if _current_date is None:
            _current_date = date_str
            _purge_old()
        elif _current_date != date_str:
            prev = _current_date
            _current_date = date_str
            _footer_locked(prev, None)
            _purge_old()
        _raw_append(date_str, text)


def _fmt_details(details):
    """Indented `key : value` block. Key column is padded to the widest key so
    the block stays scannable, capped so one long key can't wreck alignment."""
    if not details:
        return ""
    width = min(max((len(k) for k in details), default=0), 12)
    out = []
    for k, v in details.items():
        if v is None or v == "":
            continue
        out.append(f"    {k.ljust(width)} : {v}\n")
    return "".join(out)


def log_issue(severity, category, itype, instance_name, instance_id=None,
              signal_id=None, fingerprint=None, details=None):
    """Record one issue. `details` is an ordered dict of context lines.

    severity: CRITICAL | WARN | INFO
    category: COPIER | CONNECTION | RISK | NEWS | SYSTEM
    itype:    stable machine-ish name, e.g. COPY_MISSING
    """
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    inst = instance_name or "-"
    if instance_id is not None:
        inst = f"{inst} (id={instance_id})"
    head = f"{ts} | {severity} | {category} | {itype} | {inst}"
    if signal_id:
        head += f" | signal={signal_id}"
    # fp goes through _fmt_details too, so it shares the same key-column padding.
    body = dict(details or {})
    if fingerprint:
        body['fp'] = fingerprint
    _write(head + "\n" + _fmt_details(body))


def log_resolution(itype, instance_name, instance_id=None, signal_id=None, details=None):
    """Resolutions append their own entry rather than editing the original, so
    the file stays strictly append-only and safe to tail."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    inst = instance_name or "-"
    if instance_id is not None:
        inst = f"{inst} (id={instance_id})"
    head = f"{ts} | RESOLVED | COPIER | {itype} | {inst}"
    if signal_id:
        head += f" | signal={signal_id}"
    _write(head + "\n" + _fmt_details(details))


def _scan_file(date_str):
    """Parse one day's file into (issues, resolutions, fingerprints).

    issues: list of dicts with severity/type/instance. fingerprints: {fp: count}.
    Tolerant by design -- a malformed line is skipped, never raised.
    """
    issues, resolutions, fps = [], 0, {}
    try:
        with open(_path_for(date_str), 'r', encoding='utf-8') as f:
            for line in f:
                if line.startswith('    fp'):
                    fp = line.split(':', 1)[1].strip() if ':' in line else ''
                    if fp:
                        fps[fp] = fps.get(fp, 0) + 1
                    continue
                if line.startswith(' ') or line.startswith('=') or not line.strip():
                    continue
                parts = [p.strip() for p in line.split('|')]
                if len(parts) < 5:
                    continue
                if parts[1] == 'RESOLVED':
                    resolutions += 1
                elif parts[1] in ('CRITICAL', 'WARN', 'INFO'):
                    issues.append({
                        'severity': parts[1], 'category': parts[2],
                        'type': parts[3], 'instance': parts[4],
                        'signal': parts[5].replace('signal=', '') if len(parts) > 5 else None,
                    })
    except FileNotFoundError:
        pass
    except Exception:
        pass
    return issues, resolutions, fps


def recurring_history(fingerprint, days=30, before_date=None):
    """Prior days where this fingerprint also appeared -> [(date, count), ...].

    This is what turns the log from readable into trackable: it answers "is this
    a config problem or bad luck?" without any pattern-matching cleverness.
    """
    out = []
    try:
        end = datetime.strptime(before_date, "%Y-%m-%d") if before_date else datetime.now()
        for i in range(1, days + 1):
            d = (end - timedelta(days=i)).strftime("%Y-%m-%d")
            if not os.path.exists(_path_for(d)):
                continue
            _, _, fps = _scan_file(d)
            if fingerprint in fps:
                out.append((d, fps[fingerprint]))
    except Exception:
        pass
    return out


def _footer_locked(date_str, stats):
    """Append the end-of-day summary block. Callers must hold _lock."""
    try:
        issues, resolutions, fps = _scan_file(date_str)
        if not issues and not stats:
            return
        # Never footer twice (a restart mid-day would otherwise duplicate it).
        try:
            with open(_path_for(date_str), 'r', encoding='utf-8') as f:
                if 'END OF DAY' in f.read():
                    return
        except FileNotFoundError:
            pass

        by_type, by_inst = {}, {}
        open_ids = []
        resolved_sigs = set()
        for it in issues:
            by_type[it['type']] = by_type.get(it['type'], 0) + 1
            by_inst[it['instance']] = by_inst.get(it['instance'], 0) + 1

        lines = [f"\n{'=' * 16} END OF DAY {date_str} {'=' * 16}\n"]
        if stats:
            lines.append(
                f"Signals: {stats.get('signals', 0)}   "
                f"Mirrored: {stats.get('mirrored', 0)}/{stats.get('expected', 0)}   "
                f"Issues: {len(issues)} ({resolutions} resolved)\n"
            )
        else:
            lines.append(f"Issues: {len(issues)} ({resolutions} resolved)\n")

        if by_type:
            lines.append("By type     : " + ", ".join(f"{k} {v}" for k, v in sorted(by_type.items(), key=lambda x: -x[1])) + "\n")
        if by_inst:
            lines.append("By instance : " + ", ".join(f"{k} {v}" for k, v in sorted(by_inst.items(), key=lambda x: -x[1])) + "\n")

        for fp, count in sorted(fps.items(), key=lambda x: -x[1]):
            hist = recurring_history(fp, days=30, before_date=date_str)
            if count > 1 or hist:
                hist_str = ""
                if hist:
                    hist_str = "  <-- also seen " + ", ".join(
                        f"{datetime.strptime(d, '%Y-%m-%d').strftime('%d %b')} (x{n})" for d, n in hist[:4]
                    )
                lines.append(f"Recurring   : {fp} x{count}{hist_str}\n")

        if stats and stats.get('open_incidents'):
            for oi in stats['open_incidents']:
                lines.append(f"Still open  : {oi}\n")

        lines.append("=" * (34 + len(date_str)) + "\n\n")
        _raw_append(date_str, "".join(lines))
    except Exception:
        pass


def finalize_day(date_str, stats=None):
    """Public entry for the daily footer, called by the heartbeat at rollover."""
    with _lock:
        _footer_locked(date_str, stats)


def day_summary(date_str=None):
    """Counts for the Telegram heartbeat / UI, read back off the file."""
    date_str = date_str or _today()
    issues, resolutions, fps = _scan_file(date_str)
    return {
        'issues': len(issues),
        'resolved': resolutions,
        'critical': sum(1 for i in issues if i['severity'] == 'CRITICAL'),
        'fingerprints': fps,
    }
