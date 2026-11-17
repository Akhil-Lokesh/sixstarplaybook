# Six Star Playbook: backend

The API behind sixstarplaybook.com, a free GTA 6 question-and-answer site. A player types
a question; Claude Haiku 5.5 answers from the GTA 6 A to Z guide, streaming, with cited
sections and Confirmed / Rumor / Not confirmed tags.

This folder is the whole backend: five services, tests, Docker setup and docs. The
website frontend is not included; `HANDOFF.md` is the brief for building it.

| Doc | What's in it |
| --- | --- |
| `CLAUDE_CODE_PROMPT.md` | Prompt to paste into Claude Code: the frontend build and the remaining launch steps |
| `HANDOFF.md` | Brief for the frontend build: pages, how to call the API, design tokens, required text |
| `docs/API.md` | The API contract: every route, the SSE events, the answer record, error codes |
| `docs/ARCHITECTURE.md` | The five services, one request step by step, cost controls, failure behavior |
| `docs/DEPLOY.md` | Hosting, Redis, Cloudflare, updating the guide, before-launch checklist |

## Services

| Service | Port | Job |
| --- | --- | --- |
| gateway | 8000 | The only public service: `/api/*`, CORS, visitor id, coarse rate cap |
| answer | 8001 | Answer cache, Claude call (streaming, prompt caching, structured output) |
| guard | 8002 | Per-visitor limits, global calls per minute, daily and monthly spend caps |
| content | 8003 | The guide and its version, topics, cheat codes, starters, what's new |
| analytics | 8004 | Question log, trending, feedback, reports, daily stats |

## Run it locally

Needs Python 3.12+ (built and tested on 3.13). No API key needed with the mock.

```bash
python3 -m pip install -r requirements-dev.txt

# All five services in one process, fake Claude, in-memory store:
MOCK_LLM=true python3 -m sixstar.run_all
# In another terminal:
bash scripts/smoke_test.sh
```

Then open the bare test page from a second origin to check CORS and streaming:

```bash
python3 -m http.server 8080 --directory dev
# open http://localhost:8080/test-page.html
```

With Redis (closer to production):

```bash
redis-server --port 6379 &
MOCK_LLM=true REDIS_URL=redis://127.0.0.1:6379/0 python3 -m sixstar.run_all
```

With the real model, put your key in the environment (never in code) and drop
`MOCK_LLM`:

```bash
export ANTHROPIC_API_KEY=...        # from the Claude Console
ADMIN_TOKEN=pick-something python3 -m sixstar.run_all
python3 scripts/run_eval.py --admin-token pick-something
```

With Docker (needs a running Docker daemon):

```bash
cp .env.example .env    # fill in the key, tokens, caps
docker compose up -d --build
curl http://127.0.0.1:8000/api/health
```

## Tests

```bash
python3 -m pytest -q
```

33 tests, all offline: text normalization, the guide parser, the streaming JSON
extractor, request parameters and cost math, the store against memory and a real
`redis-server` (skipped if not installed), and end to end through the gateway with all
services wired in-process and Claude mocked: streaming, cache hits for reworded
questions, one Claude call for five identical concurrent questions, rate limits with
popular-question fallbacks, admin bypass, spend caps and settlement, refusals, upstream
errors, off-topic, answer pages, trending, content routes, feedback, CORS, internal
auth, guide-version cache invalidation, and a downed service failing closed.

`tests/eval_questions.jsonl` is a 16-question quality set (answerable, rumor, not
covered, off-topic, not allowed, prompt injection). Run it against the real model with
`scripts/run_eval.py`; the plan calls for growing it to 50.

## Layout

```text
sixstar/
  common/     settings, Redis or memory store, text normalization, errors, service clients
  gateway/    public API
  answer/     prompt, schema, Claude client, stream extractor, offline mock
  guard/      limits and spend caps
  content/    guide parser and content routes
  analytics/  stats, trending, feedback
  run_all.py  all five services in one process
guide/guide.md          the knowledge (exported from the GTA 6 A to Z doc)
data/                   cheat codes, starters, what's new, prefill questions
scripts/                smoke test, eval runner, cache prefill
dev/test-page.html      bare streaming test page (not the real frontend)
tools/                  Claude Docs XML → guide.md converter
tests/
```

## Key settings

All settings are environment variables; `.env.example` lists every one with notes.
The ones to decide before launch: `ANTHROPIC_API_KEY`, `DAILY_SPEND_CAP_USD`,
`MONTHLY_SPEND_CAP_USD`, `CORS_ORIGINS`, `INTERNAL_TOKEN`, `ADMIN_TOKEN`,
`ANALYTICS_SALT`, `REDIS_URL`, `TRUST_PROXY_HEADERS`.

Model settings: `ANTHROPIC_MODEL=claude-haiku-5-5`, `LLM_EFFORT=low`,
`LLM_THINKING=disabled`, `MAX_OUTPUT_TOKENS=700`, `PROMPT_CACHE_TTL=1h`. Switching to
Opus 5.5 later is `ANTHROPIC_MODEL=claude-opus-5-5` plus the matching `PRICE_*`
values; Opus always thinks, so set `LLM_THINKING=adaptive` with it.
