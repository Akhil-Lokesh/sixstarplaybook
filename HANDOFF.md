# Frontend handoff: Six Star Playbook

For the Claude Code session building the frontend. The backend in this folder is done
and tested; build the website against it. The full contract is `docs/API.md`; this file
is the short version plus the design tokens.

## Run the backend locally (no API key needed)

```bash
cd sixstarplaybook
python3 -m pip install -r requirements.txt
MOCK_LLM=true python3 -m sixstar.run_all     # API on http://127.0.0.1:8000
```

`MOCK_LLM=true` gives fake but well-formed streamed answers built from the guide, so the
whole UI can be built and tested offline. Dev origins already allowed by CORS:
`http://localhost:5173`, `http://localhost:3000`, `http://localhost:8080`,
`http://127.0.0.1:8080`. Add others with `CORS_ORIGINS`.

`dev/test-page.html` is a bare working page that streams answers, shows starters and
sends feedback. Its `readSSE` function is the reference for reading the stream.

## What to build

The plan's pages, mobile first:

| Page | Path | Data |
| --- | --- | --- |
| Home | `/` | Unlock countdown (client side; the guide says midnight local time Nov 19, with the whole US on Eastern: 2026-11-19T05:00:00Z, which is 9 PM PT on Nov 18), ask box with starter chips (`GET /api/starters`), trending (`GET /api/trending`), topic tiles (`GET /api/topics`), what's new (`GET /api/whats-new`) |
| Answer page | `/q/<slug>` | `GET /api/q/<slug>`; after asking, stream into the same layout and update the URL to `/q/<slug>` from the `meta` event |
| Topic pages | `/topics/<id>` | `GET /api/topics/<id>` (render `markdown`); show a Rumor banner when `is_rumor` |
| Cheat codes hub | `/cheat-codes` | `GET /api/cheat-codes`; show `message` while `platforms` lists are empty, else a table per platform: code, effect, Verified/Unverified, date checked |
| What's new | `/whats-new` | `GET /api/whats-new` |
| About, Accuracy, Privacy, Terms, Contact | `/about`, `/about/accuracy`, `/privacy`, `/terms`, `/contact` | Static text (Akhil writes the content) |

The site is static (Cloudflare Pages), so `/q/<slug>` and `/topics/<id>` need a fallback
to the app shell (for example a `_redirects` rule `/q/* /index.html 200`) or a static
page per route that fetches on load.

## Asking a question

1. Keep a browser id: `crypto.randomUUID()` without dashes, stored in `localStorage`
   (wrap in try/catch). Send it as `X-Client-Id` on `/api/ask`, `/api/limits`,
   `/api/feedback`.
2. `POST /api/ask` with `{"question": "..."}` and read the body as SSE with `fetch`.
3. If the status isn't 200, it's a JSON error: show `error.message`; on `rate_limited`,
   `busy` or `budget_exhausted` also list `error.top_questions` as links to `/q/<slug>`.
4. Events: `meta` (slug, cached) → `delta` (append text) → `answer` (final record) or
   `error` (show its message) → `done`.
5. On `answer`: replace the streamed text with `answer.answer` rendered as light Markdown
   (bold, bullets; disable raw HTML), then show:
   - a tag per claim: `confirmed` green, `rumor` amber, `not_confirmed` gray
   - sources as teal links to `source.url` (`/topics/<id>`)
   - related questions as chips that ask that question
   - a "Show spoiler" tap when `spoiler` is true
   - Helpful / Not helpful (`POST /api/feedback`), Report (`POST /api/report` with an
     optional note), Copy link (`https://sixstarplaybook.com/q/<slug>`)
   - the AI notice under the answer (text below)
6. `status` other than `answered`: `not_confirmed` reads as "That isn't confirmed yet"
   (the text says so already); `off_topic` and `not_allowed` should show the starter
   chips again. These two never get an answer page.

Optional: `GET /api/limits` to show "7 questions left this hour".

## Error codes to handle

`invalid_question` 400, `rate_limited` 429, `busy` 503, `budget_exhausted` 503,
`unavailable` 503, `not_found` 404. In-stream `error` events: `refused`,
`upstream_error`, `internal_error`, `busy`. Every `message` is player-ready text.

## Design tokens (from the plan's Site design section)

Look: a night drive along a neon coast. Deep violet night sky, a striped sunset sun on
the horizon, palm and skyline silhouettes, hot pink, orange and gold accents. Original
art only.

```css
:root {
  --night:  #0F0B1C;  /* page background */
  --panel:  #1E1738;  /* answer cards, tiles */
  --pink:   #FF3D7F;  /* primary accent, focus, logo */
  --orange: #FF8A3D;  /* Ask button gradient, sunset */
  --gold:   #FFD166;  /* countdown, hot topics, highlights */
  --teal:   #29E0C9;  /* links and sources */
  --tag-confirmed:     #3EE08F;  /* green */
  --tag-rumor:         #FFB547;  /* amber */
  --tag-not-confirmed: #8E84AD;  /* gray */
}
```

Type (all free Google Fonts):

- **Big Shoulders Display**: headings and the logo
- **Archivo**: body text
- **JetBrains Mono**: tags, dates and sources

Brand: "Six Star Playbook" in the tall condensed display face, with six small stars
fading from gold to pink as the logo mark (drawn from scratch). Voice: quick, confident,
plain ("Unlocks in 4d 9h", "That isn't confirmed yet."). Never hype or clickbait.

Mobile: the ask box stacks full width, the Ask button spans the screen, answers stay
under one screen of text.

Mockup from the plan: the clickable homepage mockup linked in the A to Z plan's Site
design section.

## Required text

Footer, every page:

> Six Star Playbook is an unofficial fan site. It is not affiliated with, endorsed by or
> sponsored by Rockstar Games or Take-Two Interactive. Grand Theft Auto and related marks
> belong to their owners.

Under every answer:

> Written by AI from our guide. Can be wrong; check the linked source.

## Guardrails

No Rockstar or GTA logos, the game's fonts, key art, screenshots, trailer frames or
music, and no copy of the official site's layout. "GTA 6" in page text is fine.

## Wiring to production

Set the API base URL from an environment variable at build time (for example
`VITE_API_BASE=https://api.sixstarplaybook.com`). The backend must list the site's
origin in `CORS_ORIGINS`. See `docs/DEPLOY.md`.
