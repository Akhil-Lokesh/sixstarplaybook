"""Asking every question in data/prefill_questions.txt once so the answers are cached
before launch traffic arrives (and become answer pages at /q/<slug>).

    ADMIN_TOKEN=... python scripts/prefill_cache.py --base http://127.0.0.1:8000

The admin token skips the per-visitor limits; the daily and monthly spend caps still
apply. Questions already cached for the current guide version cost nothing.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import time
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--file", default=str(ROOT / "data" / "prefill_questions.txt"))
    ap.add_argument("--delay", type=float, default=0.3, help="seconds between questions")
    args = ap.parse_args()
    token = os.environ.get("ADMIN_TOKEN")
    if not token:
        print("Set ADMIN_TOKEN (the same value the services use).", file=sys.stderr)
        return 2
    questions = [q.strip() for q in pathlib.Path(args.file).read_text().splitlines()
                 if q.strip() and not q.lstrip().startswith("#")]
    new = cached = errors = 0
    for q in questions:
        req = urllib.request.Request(
            f"{args.base}/api/ask", data=json.dumps({"question": q}).encode(), method="POST",
            headers={"Content-Type": "application/json", "X-Admin-Token": token},
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                body = resp.read().decode()
        except urllib.error.HTTPError as exc:
            errors += 1
            print(f"ERR  {q}  -> {exc.code} {exc.read().decode()[:200]}")
            if exc.code == 503:
                break
            continue
        was_cached = '"cached": true' in body.split("\n\n", 1)[0]
        failed = "event: error" in body
        if failed:
            errors += 1
        elif was_cached:
            cached += 1
        else:
            new += 1
        print(f"{'ERR ' if failed else 'hit ' if was_cached else 'new '} {q}")
        time.sleep(args.delay)
    print(f"\n{new} answered, {cached} already cached, {errors} errors")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
