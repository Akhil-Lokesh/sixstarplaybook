# Six Star Playbook API contract

The frontend talks only to the **gateway**. Every public route is under `/api`.
Base URL locally: `http://127.0.0.1:8000`. In production: wherever the gateway is
hosted (for example `https://api.sixstarplaybook.com`).

## Conventions

- **Request bodies** are JSON (`Content-Type: application/json`).
- **`X-Client-Id` header** (optional, recommended): a random id the browser keeps in
  `localStorage`, 8 to 64 characters of `A-Z a-z 0-9 _ -`. The per-visitor limits count
  both the IP and this id. Send it on `/api/ask`, `/api/limits` and `/api/feedback`.
- **CORS**: browsers may call from the origins in `CORS_ORIGINS`. Allowed methods
  `GET, POST, OPTIONS`; allowed request headers `Content-Type, X-Client-Id`; exposed
  response headers `Retry-After`.
- **Errors** (any route, before any streaming starts) are JSON with an HTTP status:

```json
{"error": {"code": "rate_limited", "message": "You've reached the limit of 10 new questions per hour. Popular answers below still work.", "retry_after": 1520, "top_questions": [{"slug": "...", "question": "...", "count": 12}]}}
```

`message` is written to be shown to players as is. `retry_after` (seconds) is present
on limit errors and is also sent as the `Retry-After` header. `top_questions` is present
on `rate_limited`, `busy` and `budget_exhausted` from `/api/ask`, so the page can offer
cached answers instead.

### Error codes

| Code | HTTP | When | What the page should do |
| --- | --- | --- | --- |
| `invalid_question` | 400 | Empty or too short after cleaning | Ask the player to type a GTA 6 question |
| `invalid_request` | 422 | Body missing or wrong shape | Developer error |
| `not_found` | 404 | No such answer page or topic | Show a not-found state with the ask box |
| `forbidden` | 403 | Internal or admin route without a token | Never reached by the frontend |
| `rate_limited` | 429 | This visitor used their hourly or daily questions | Show `message`, the `top_questions`, and the reset time |
| `busy` | 503 | Too many new AI calls this minute, or Claude is overloaded | Show `message` and `top_questions`; retry after `retry_after` |
| `budget_exhausted` | 503 | Daily or monthly spend cap reached | Show `message` and `top_questions`; cached answers still work |
| `unavailable` | 503 | An internal service is down or still starting | Show `message`; retry after `retry_after` |

Errors that happen **after** streaming started arrive as an SSE `error` event (below):
`refused`, `upstream_error`, `internal_error`, `busy`.

## POST /api/ask (streaming)

Ask a question. The response is a Server-Sent Events stream (`text/event-stream`).

Request:

```http
POST /api/ask
Content-Type: application/json
X-Client-Id: 3f9c2e7a1b8d4c6e9f0a2b4c6d8e0f12

{"question": "What time does GTA 6 unlock?"}
```

`question`: 1 to 2000 characters; the server trims it to 300 after cleaning.

If the request is refused before streaming (limits, bad input), you get a JSON error as
above with a non-200 status. Otherwise status 200 and these events, in this order:

| Event | Data | Notes |
| --- | --- | --- |
| `meta` | `{"slug", "cached", "guide_version"}` | Always first. `slug` is the answer page id (`/q/<slug>`). |
| `delta` | `{"text"}` | Zero or more. Append `text` to show the answer as it is written. A cached answer arrives as one delta. |
| `answer` | the full answer record (below) plus `"cached"` | The final answer. Replace the streamed text with `answer.answer` and render tags and sources. |
| `error` | `{"code", "message", "retry_after"?}` | Instead of `answer` when something failed mid-stream. Show `message`. |
| `done` | `{}` | Always last when the stream ends normally. |

Example stream:

```text
event: meta
data: {"slug": "what-time-does-gta-6-unlock", "cached": false, "guide_version": "g-02c9920d488e"}

event: delta
data: {"text": "GTA 6 unlocks at "}

event: delta
data: {"text": "9 PM Pacific on November 18, 2026..."}

event: answer
data: {"slug": "what-time-does-gta-6-unlock", "question": "What time does GTA 6 unlock?", "answer": "...", "status": "answered", "claims": [...], "sources": [...], "related_questions": [...], "spoiler": false, "truncated": false, "guide_version": "g-02c9920d488e", "model": "claude-haiku-5-5", "created_at": "2026-11-15T15:30:34+00:00", "cached": false}

event: done
data: {}
```

`EventSource` can't send POST bodies or headers, so read the stream with `fetch` and a
body reader (see `dev/test-page.html`, function `readSSE`). For `EventSource` there is
also `GET /api/ask?q=<question>&client_id=<id>` with the same events.

### Answer record

| Field | Type | Meaning |
| --- | --- | --- |
| `slug` | string | Answer page id; the page lives at `/q/<slug>` |
| `question` | string | The cleaned question |
| `answer` | string | The answer text, about 120 words at most: one or two sentences, then up to 4 `- ` bullets. Light Markdown only (`**bold**`, bullets), no headings, links or HTML. Render it as Markdown with HTML disabled |
| `status` | `answered` \| `not_confirmed` \| `off_topic` \| `not_allowed` | `not_confirmed`: the guide doesn't confirm it. `off_topic`: not about GTA 6. `not_allowed`: hacks, piracy, mod menus |
| `claims` | `[{"text", "label"}]` | Key claims with `label` `confirmed` \| `rumor` \| `not_confirmed` (green, amber, gray tags) |
| `sources` | `[{"id", "title", "url"}]` | Guide sections used. `url` is the topic page path, e.g. `/topics/launch-essentials` |
| `related_questions` | string[] (0 to 3) | Follow-up questions to show as chips |
| `spoiler` | boolean | True when the answer reveals story details; hide behind a "Show spoiler" tap |
| `truncated` | boolean | True when the answer hit the length cap (rare) |
| `guide_version` | string | Version of the guide the answer came from |
| `model` | string | Model that wrote it |
| `created_at` | ISO 8601 UTC | When it was written |
| `cached` | boolean | Only in the stream: true when served from the answer cache |

Only `answered` and `not_confirmed` answers get an answer page.

## GET /api/q/{slug}

The saved answer record for an answer page (same fields as above, no `cached`).
404 `not_found` if there is no page yet. Cached for 5 minutes (`Cache-Control`).

## GET /api/limits

How many new questions this visitor has left. Send `X-Client-Id`.

```json
{"remaining_hour": 7, "remaining_day": 27, "limit_hour": 10, "limit_day": 30, "resets_in_seconds": 1695}
```

Cached answers never count against the limit.

## Content

| Route | Response |
| --- | --- |
| `GET /api/starters` | `{"starters": ["What time does GTA 6 unlock?", ...]}` |
| `GET /api/topics` | `{"guide_version", "topics": [{"id", "title", "summary", "url"}]}` |
| `GET /api/topics/{id}` | `{"id", "title", "summary", "markdown", "is_rumor", "guide_version"}` (`markdown` is the section body in Markdown; render it) |
| `GET /api/cheat-codes` | `{"status": "none_confirmed", "message", "updated_at", "platforms": {"ps5": [], "xbox_series": []}, "entry_shape": {...}}`. When codes exist each platform list holds `{"name", "code", "effect", "verified", "checked_on", "notes"}` (set `status` to `"live"` in `data/cheat_codes.json` when you add the first codes) |
| `GET /api/whats-new` | `{"items": [{"date", "title", "body"}]}` (newest first) |
| `GET /api/guide/version` | `{"version", "loaded_at", "sections"}` |

Topic ids today: `launch-essentials`, `price-editions-and-preorders`,
`trailers-and-reveals`, `setting-leonida`, `characters-and-story`, `gameplay-systems`,
`map-online-and-technical-details`, `rumors-and-conflicts`. Read them from
`/api/topics` rather than hardcoding.

## Trending, feedback, reports

| Route | Body | Response |
| --- | --- | --- |
| `GET /api/trending?limit=10` | | `{"items": [{"slug", "question", "count"}]}`, most asked answered questions today and yesterday (UTC) |
| `POST /api/feedback` | `{"slug", "helpful": true}` + `X-Client-Id` | `{"ok": true}`, or `{"ok": true, "duplicate": true}` if this browser already voted on that page |
| `POST /api/report` | `{"slug", "note": "optional, up to 500 chars"}` | `{"ok": true}` |

## Health

`GET /api/health` returns 200 `{"status": "ok", "services": {...}}`, or 503
`{"status": "degraded", ...}` when any internal service is down. The answer service's
entry shows `"llm": "ok" | "mock" | "missing_api_key"`.

## Edge limit

Every `/api` route also has a coarse per-IP cap (`EDGE_REQUESTS_PER_MINUTE`, default
120). Past it the gateway returns 429 `rate_limited` with `Retry-After`.

## Admin (not for the frontend)

Send `X-Admin-Token: <ADMIN_TOKEN>`. These run on the internal services, so call them
from the host (docker compose exec, or the service port), not through the public site.

| Service | Route | What it does |
| --- | --- | --- |
| guard | `GET /admin/spend` | Today's and this month's spend against the caps |
| analytics | `GET /admin/stats?days=7` | Daily counts, cache hits, cost, thumbs up rate, recent questions and reports |
| content | `POST /admin/reload` | Re-read `guide.md` and data files; new guide version starts a fresh answer cache |

The gateway's `/api/ask` also accepts `X-Admin-Token` to skip the per-visitor limits
(used by `scripts/prefill_cache.py`). Spend caps still apply. It is not in the CORS
allow list, so browsers can't send it.
