"""Asking every question in tests/eval_questions.jsonl through a running gateway and
checking the answer's status and cited sections.

    python scripts/run_eval.py --base http://127.0.0.1:8000 [--admin-token ...]

Against MOCK_LLM=true it checks wiring only. Against the real model each question is
one Claude call (about a fraction of a cent each with Haiku 5.5 and a warm cache), so
pass --admin-token to skip the per-visitor limits.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]


def ask(base: str, question: str, admin_token: str | None) -> dict:
    req = urllib.request.Request(
        f"{base}/api/ask", data=json.dumps({"question": question}).encode(), method="POST",
        headers={"Content-Type": "application/json", "X-Client-Id": "eval-runner-0001",
                 **({"X-Admin-Token": admin_token} if admin_token else {})},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        text = resp.read().decode()
    event = None
    out: dict = {}
    for line in text.splitlines():
        if line.startswith("event: "):
            event = line[7:]
        elif line.startswith("data: ") and event in ("answer", "error"):
            out[event] = json.loads(line[6:])
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--admin-token")
    ap.add_argument("--file", default=str(ROOT / "tests" / "eval_questions.jsonl"))
    args = ap.parse_args()
    passed = failed = 0
    for line in pathlib.Path(args.file).read_text().splitlines():
        if not line.strip():
            continue
        case = json.loads(line)
        result = ask(args.base, case["q"], args.admin_token)
        ans = result.get("answer")
        problems = []
        if not ans:
            problems.append(f"no answer ({result.get('error')})")
        else:
            if ans["status"] not in case["expect_status"]:
                problems.append(f"status {ans['status']}")
            cited = {s["id"] for s in ans["sources"]}
            if case["expect_sources"] and not cited & set(case["expect_sources"]):
                problems.append(f"sources {sorted(cited)}")
            if len(ans["answer"].split()) > 140:
                problems.append("too long")
        mark = "ok  " if not problems else "FAIL"
        passed += not problems
        failed += bool(problems)
        print(f"{mark} {case['q']}" + (f"  -> {'; '.join(problems)}" if problems else ""))
        if ans:
            print(f"     [{ans['status']}] {ans['answer'][:160]}")
    print(f"\n{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
