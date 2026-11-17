# Architecture

Five small FastAPI services share one Python package (`sixstar/`) and one Redis.
Only the gateway is public.

```text
 browser (Cloudflare Pages site)
        │  HTTPS, /api/*
        ▼
 ┌──────────────┐  X-Internal-Token on every internal call
 │   gateway    │──────────────┬──────────────┬──────────────┐
 │   :8000      │              │              │              │
 └──────┬───────┘              ▼              ▼              ▼
        │ /internal/ask   ┌─────────┐    ┌─────────┐    ┌───────────┐
        ▼                 │  guard  │    │ content │    │ analytics │
 ┌──────────────┐ ──────▶ │  :8002  │    │  :8003  │    │   :8004   │
 │    answer    │ authorize/settle  │    └────▲────┘    └─────▲─────┘
 │    :8001     │ ─────────────────────────────┘ guide        │ events
 │              │ ──────────────────────────────────────────────┘
 └──────┬───────┘
        │ HTTPS (streaming)
        ▼
  Claude API (claude-haiku-5-5)

 All five read and write Redis, each under its own key prefix.
```

## Services

| Service | Port | Job | Redis keys (prefix `ssp:<service>:`) |
| --- | --- | --- | --- |
| **gateway** | 8000 | Public API. CORS, visitor IP and browser id, coarse per-IP cap, forwards to the others, streams answers through | `edge:*` |
| **answer** | 8001 | Question → answer. Normalizes, checks the answer cache, coalesces identical in-flight questions, asks guard, calls Claude with streaming, saves answer and answer page, settles cost, logs | `ans:*` (answer cache), `page:*` (answer pages) |
| **guard** | 8002 | Per-visitor limits (IP and browser id, hourly and daily), global AI calls per minute, daily and monthly spend caps | `rl:*`, `global:*`, `spend:*` |
| **content** | 8003 | Loads `guide/guide.md` and `data/*.json`, versions the guide, serves topics, cheat codes, starters, what's new; hands the guide to answer | none (files) |
| **analytics** | 8004 | Question log (IP hashed), daily stats, trending, feedback, reports | `stats:*`, `trend:*`, `qmeta:*`, `log:*`, `fb*`, `reports` |

Shared code in `sixstar/common/`: settings from env (`config.py`), the store
(`store.py`: Redis or in-memory), text normalization (`text.py`), errors, internal auth
and service clients (`web.py`).

## One question, step by step

1. **gateway** gets `POST /api/ask`, counts the IP against the edge cap, and forwards
   `{question, ip, client_id}` to answer.
2. **answer** cleans the question (Unicode NFKC, control chars, 300 chars max) and
   normalizes it (lowercase, "GTA VI" / "Grand Theft Auto 6" → "gta 6", no punctuation).
3. It gets the current guide from **content** (re-checked every 60 s). The cache key is
   `ans:<guide_version>:<sha256(normalized)>`, so editing the guide starts a fresh cache.
4. **Cache hit** → stream the saved answer (`cached: true`). No limits are charged.
5. **Same question already being answered** → wait for it, then serve it from cache.
   Launch-night bursts of the same question cost one Claude call.
6. **guard** `/internal/authorize`: reserve an estimate against the daily and monthly
   spend caps, check the global calls-per-minute, then the visitor's hourly and daily
   limits. Any refusal undoes whatever it had counted.
7. **Claude call** (`messages.stream`): system = [answer rules, whole guide with a 1-hour
   `cache_control` breakpoint]; user message = today's date + the question in
   `<question>` tags. Structured output (JSON schema): `answer` first so it streams,
   then `status`, `claims`, `sources` (enum of real section ids), `related_questions`,
   `spoiler`. Effort `low`, thinking off, 700 max tokens.
8. As JSON arrives, an incremental parser pulls out the `answer` string and sends it as
   `delta` events; the gateway passes the stream straight through.
9. On completion: build the record, save the answer cache (24 h) and, for `answered` /
   `not_confirmed`, the answer page (30 days). Send `answer`, then `done`.
10. In the background: **guard** `/internal/settle` swaps the reserved estimate for the
    real cost from the usage block; **analytics** logs the event.

## Cost controls

| Control | Where | Default |
| --- | --- | --- |
| Prompt caching of the whole guide | answer | 1 h TTL; guide reads at the cache-read price |
| Answer cache | answer | 24 h per guide version |
| Single-flight | answer | identical concurrent questions share one call |
| Per-visitor limits | guard | 10/hour, 30/day, by IP and by browser id |
| Global AI calls | guard | 300/minute |
| Daily / monthly spend caps | guard | $25 / $150 |
| Edge cap | gateway | 120 requests/minute per IP |
| Max output | answer | 700 tokens |

Prices for the cap math are in env (`PRICE_*_PER_MTOK`), set to Haiku 5.5 list prices
as of this build. Keep the Anthropic Console's own spend limit as a backstop.

## Failure behavior

- Claude overloaded or rate limited → in-stream `error: busy`; timeout or API error →
  `upstream_error`; refusal (`stop_reason: refusal`) → `refused`. Haiku 5.5 has no
  server-side refusal fallback, so the client handles it. The reserved spend is still
  settled (to the real cost, often 0).
- Content down → answer keeps the guide it last loaded.
- Analytics down → answers still work; events are dropped with a log line.
- Guard (or any internal service the request needs) down → 503 `unavailable` with
  `Retry-After: 30`; no Claude call is made (fails closed). Cached answers still work
  while guard is down, because the cache is checked first.
- Redis down → services report `store: down` in health.

## Why separate services

They scale and fail independently: answer is the only one that waits on Claude, so it
can run more replicas; guard and content are tiny. For a small launch, `run_all` runs
all five in one process on one machine with the same code and the same Redis keys.

## Adding retrieval later (v2)

When the knowledge base outgrows one prompt, the change is inside **content** (serve
the top sections for a question instead of the whole guide) and **answer** (ask content
for those sections). The API and the frontend don't change.
