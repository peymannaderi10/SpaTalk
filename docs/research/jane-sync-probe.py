"""Measure how fast a Jane private calendar feed reflects a change, and whether it is cached.

Standard library only. Run it against ONE practitioner's private "Appointments" feed URL from
their Jane staff profile (Staff Profile -> Create calendar feeds). The feed can carry client
names and notes, so this probe never prints or stores event titles: it logs event UIDs
(hashed), start and end times, and the HTTP cache headers, nothing else.

    python jane-sync-probe.py <feed_url> --every 10 --minutes 30 --log probe.log
    python jane-sync-probe.py --mark "booked Dana Thu 14:00 in Jane"      # from a second terminal

Read docs/runbooks/jane-sync-test.md for the full test.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime

HEADERS_OF_INTEREST = (
    "date", "cache-control", "etag", "last-modified", "age", "expires",
    "cf-cache-status", "x-cache", "x-cache-hits", "via", "server", "content-length",
)
UA = "SpaTalk-sync-probe/1 (+measuring feed latency for the clinic's own account)"


def now() -> str:
    return datetime.now().astimezone().strftime("%H:%M:%S")


def log(path: str, line: str) -> None:
    stamped = f"{now()}  {line}"
    print(stamped, flush=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(stamped + "\n")


def fetch(url: str) -> tuple[int, dict[str, str], bytes]:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Cache-Control": "no-cache"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            headers = {k.lower(): v for k, v in resp.headers.items()}
            return resp.status, headers, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, {k.lower(): v for k, v in e.headers.items()}, e.read()


def unfold(text: str) -> list[str]:
    """iCalendar folds long lines with CRLF + space; join them back."""
    out: list[str] = []
    for line in text.replace("\r\n", "\n").split("\n"):
        if line.startswith((" ", "\t")) and out:
            out[-1] += line[1:]
        else:
            out.append(line)
    return out


def events(body: bytes) -> dict[str, tuple[str, str]]:
    """UID hash -> (DTSTART, DTEND). Titles, descriptions and locations are never read."""
    found: dict[str, tuple[str, str]] = {}
    uid = start = end = None
    for line in unfold(body.decode("utf-8", "replace")):
        if line == "BEGIN:VEVENT":
            uid = start = end = None
        elif line.startswith("UID:"):
            uid = hashlib.sha256(line[4:].encode()).hexdigest()[:10]
        elif line.startswith("DTSTART"):
            start = line.split(":", 1)[1]
        elif line.startswith("DTEND"):
            end = line.split(":", 1)[1]
        elif line == "END:VEVENT" and uid:
            found[uid] = (start or "?", end or "?")
    return found


def stable_hash(body: bytes) -> str:
    """Hash of the feed with per-request noise removed, so 'changed' means an event changed."""
    kept = [
        ln for ln in unfold(body.decode("utf-8", "replace"))
        if not ln.startswith(("DTSTAMP", "LAST-MODIFIED", "CREATED", "SEQUENCE", "PRODID"))
    ]
    return hashlib.sha256("\n".join(kept).encode()).hexdigest()[:12]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("url", nargs="?", help="private Jane calendar feed URL (webcal:// or https://)")
    ap.add_argument("--every", type=float, default=10, help="seconds between fetches (default 10)")
    ap.add_argument("--minutes", type=float, default=30, help="how long to run (default 30)")
    ap.add_argument("--log", default="jane-sync-probe.log", help="shared log file")
    ap.add_argument("--mark", help="append a timestamped note to the log and exit")
    args = ap.parse_args()

    if args.mark:
        log(args.log, f"MARK  {args.mark}")
        return 0
    if not args.url:
        ap.error("a feed url is required unless --mark is used")
    url = re.sub(r"^webcal://", "https://", args.url.strip())

    log(args.log, f"probe start  every={args.every}s  for={args.minutes}min  feed=...{url[-24:]}")
    previous_hash = None
    previous_events: dict[str, tuple[str, str]] = {}
    deadline = time.time() + args.minutes * 60
    tick = 0
    while time.time() < deadline:
        tick += 1
        t0 = time.time()
        status, headers, body = fetch(url)
        ms = int((time.time() - t0) * 1000)
        if status != 200:
            log(args.log, f"HTTP {status} in {ms}ms; headers: " + "; ".join(f"{k}={headers[k]}" for k in HEADERS_OF_INTEREST if k in headers))
            time.sleep(args.every)
            continue
        h = stable_hash(body)
        evs = events(body)
        cache_bits = "; ".join(f"{k}={headers[k]}" for k in HEADERS_OF_INTEREST if k in headers)
        if tick == 1:
            log(args.log, f"first fetch: {len(evs)} events, {len(body)} bytes, {ms}ms")
            log(args.log, f"cache headers: {cache_bits or '(none of interest)'}")
            if "age" in headers and headers["age"] not in ("0", ""):
                log(args.log, "NOTE: an Age header above 0 means a cache in front of Jane served this copy")
            if "cf-cache-status" in headers or "x-cache" in headers:
                log(args.log, "NOTE: a CDN cache status header is present; watch whether it says HIT")
        if previous_hash is not None and h != previous_hash:
            added = sorted(set(evs) - set(previous_events))
            removed = sorted(set(previous_events) - set(evs))
            moved = sorted(u for u in set(evs) & set(previous_events) if evs[u] != previous_events[u])
            parts = []
            for u in added:
                parts.append(f"+{u} {evs[u][0]}..{evs[u][1]}")
            for u in removed:
                parts.append(f"-{u} {previous_events[u][0]}..{previous_events[u][1]}")
            for u in moved:
                parts.append(f"~{u} {previous_events[u][0]}..{previous_events[u][1]} -> {evs[u][0]}..{evs[u][1]}")
            log(args.log, f"CHANGE  {len(evs)} events now ({' '.join(parts) or 'same events, other fields changed'})  [{cache_bits}]")
        elif tick % 6 == 0:
            log(args.log, f"unchanged ({len(evs)} events, {ms}ms) [{cache_bits}]")
        previous_hash, previous_events = h, evs
        time.sleep(max(0.0, args.every - (time.time() - t0)))
    log(args.log, "probe end")
    return 0


if __name__ == "__main__":
    sys.exit(main())
