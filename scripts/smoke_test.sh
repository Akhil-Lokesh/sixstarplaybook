#!/usr/bin/env bash
# Quick checks against a running gateway. Usage: scripts/smoke_test.sh [base_url]
set -eu
BASE="${1:-http://127.0.0.1:8000}"
CID="smoke-test-0001"

echo "== health";        curl -fsS "$BASE/api/health"; echo
echo "== guide version"; curl -fsS "$BASE/api/guide/version"; echo
echo "== starters";      curl -fsS "$BASE/api/starters" | head -c 300; echo
echo "== topics";        curl -fsS "$BASE/api/topics" | head -c 300; echo
echo "== cheat codes";   curl -fsS "$BASE/api/cheat-codes"; echo
echo "== limits";        curl -fsS -H "X-Client-Id: $CID" "$BASE/api/limits"; echo

echo "== ask (streams Server-Sent Events)"
curl -sS -N -X POST "$BASE/api/ask" \
  -H "Content-Type: application/json" -H "X-Client-Id: $CID" \
  -d '{"question":"What time does GTA 6 unlock?"}'

echo "== same question again (should say cached: true)"
curl -sS -N -X POST "$BASE/api/ask" \
  -H "Content-Type: application/json" -H "X-Client-Id: $CID" \
  -d '{"question":"what time does gta vi unlock"}' | head -n 2 || true

echo "== answer page"
curl -fsS "$BASE/api/q/what-time-does-gta-6-unlock" | head -c 300; echo
echo "== trending";      curl -fsS "$BASE/api/trending"; echo
echo "== feedback";      curl -fsS -X POST "$BASE/api/feedback" -H "Content-Type: application/json" \
  -H "X-Client-Id: $CID" -d '{"slug":"what-time-does-gta-6-unlock","helpful":true}'; echo
echo "smoke test done"
