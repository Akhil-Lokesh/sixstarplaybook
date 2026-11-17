# Prompt for Claude Code

Paste everything below the line into Claude Code, opened in the unzipped
`sixstarplaybook` folder (or a repo containing it).

---

You're working on **Six Star Playbook** (sixstarplaybook.com), a free GTA 6
question-and-answer website. A player types a question. Claude Haiku 5.5 answers from
our GTA 6 A to Z guide, streaming, with cited guide sections and Confirmed / Rumor / Not
confirmed tags.

GTA 6 unlocks **Wednesday Nov 18, 2026 at 9 PM Pacific**. The goal is to be live by then,
so prioritize a working, good-looking v1 over extras.

## What already exists (this folder)

The backend is finished and tested. Don't rewrite it; change it only where a task below
needs it.

- `sixstar/`: five FastAPI services.
  - **gateway** (port 8000) is the only public one, serving `/api/*`.
  - **answer** (8001) handles the Claude call: streaming, prompt caching and structured output.
  - **guard** (8002) handles rate limits and the daily and monthly spend caps.
  - **content** (8003) serves the guide, topics, cheat codes, starters and what's new.
  - **analytics** (8004) handles trending, feedback and reports.
  - `python -m sixstar.run_all` runs all five in one process.
- `guide/guide.md`: the knowledge base. `data/*.json`: cheat codes, starters, what's new.
- `tests/`: 33 offline tests (`python -m pytest -q`). `tests/eval_questions.jsonl` is the
  answer-quality set.
- `scripts/`:
  - `smoke_test.sh`: curl checks
  - `run_eval.py`: quality eval against a running API
  - `prefill_cache.py`: pre-answers likely questions
- `Dockerfile`, `docker-compose.yml`, `.env.example`.
- Read these first:
  - `HANDOFF.md`: the frontend brief, with pages, design tokens and required text
  - `docs/API.md`: the full API contract, including SSE events and error codes
  - `docs/ARCHITECTURE.md`
  - `docs/DEPLOY.md`
  - `dev/test-page.html`: a bare page that already streams answers. Its `readSSE`
    function is the reference.

## Ground rules

- Never put an API key or any secret in code or in git. Keys come from environment
  variables only; `.env` is gitignored.
- Don't sign up for, buy, register or deploy anything yourself. When a step needs an
  account (Cloudflare, a host, Upstash, the domain), stop and give me exact steps to do it.
- Use original visuals only. No Rockstar or GTA logos, fonts, key art, screenshots or
  trailer frames, and no copy of the official site's layout. Writing "GTA 6" in page text
  is fine.
- After each task, run the backend tests and check the site in a browser against the
  mock backend before moving on.

## Tasks, in order

### 1. Get it running
1. Install `requirements-dev.txt` and run `python -m pytest -q`. All 33 tests should pass.
2. Start the backend with `MOCK_LLM=true python -m sixstar.run_all` (no key needed; it
   returns fake but well-formed answers).
3. Run `bash scripts/smoke_test.sh` to confirm it works.

### 2. Build the frontend in `frontend/`
Build exactly what `HANDOFF.md` describes:
- **Stack:** a static site (Vite with plain TypeScript, or a light framework if you
  strongly prefer one). It must deploy to Cloudflare Pages as static files.
- **API base URL:** read from `VITE_API_BASE`, default `http://127.0.0.1:8000`.
- **Pages:**
  - Home: countdown, ask box with starter chips, trending, topic tiles, what's new
  - Answer page `/q/<slug>`
  - Topic pages `/topics/<id>`
  - `/cheat-codes`, `/whats-new`
  - About, Accuracy, Privacy, Terms, Contact. Use short placeholder text and mark it
    clearly for me to fill in.
- **Asking:**
  - `POST /api/ask` with an `X-Client-Id` kept in localStorage, read as SSE with fetch.
  - Show deltas live, then render the final `answer` event with:
    - claim tags (green / amber / gray)
    - teal source links
    - related-question chips
    - spoiler tap
    - Helpful / Not helpful, Report and Copy link
    - the AI notice
  - Update the URL to `/q/<slug>` from the `meta` event.
- **Errors:** handle every code in `docs/API.md`. On `rate_limited`, `busy` and
  `budget_exhausted`, show the message plus `top_questions` as links.
- **Design:**
  - Use the tokens and fonts in `HANDOFF.md`: night-drive neon coast look; Big Shoulders
    Display, Archivo, JetBrains Mono.
  - Mobile first: full-width ask box and button, answers under one screen.
  - Accessible: focus states, contrast, labels, reduced motion.
- **Footer disclaimer and AI notice:** on every page, word for word from `HANDOFF.md`.
- **Routing:** add a `public/_redirects` SPA fallback so `/q/*` and `/topics/*` load on
  Cloudflare Pages.
- **SEO basics:** per-page `<title>` and description, Open Graph tags, `robots.txt`.
- **Check:** test the whole flow in a browser against the mock backend, including phone
  width.

### 3. Real model, when I give you the key
1. I'll set `ANTHROPIC_API_KEY` in my shell. Never ask me to paste it into chat or a
   file you commit.
2. Run the backend without `MOCK_LLM`, set an `ADMIN_TOKEN`, then run
   `python scripts/run_eval.py --admin-token <token>`. Each question is one real Claude
   call, well under a cent each.
3. If answers are wrong, too long or badly labeled, tune the rules in
   `sixstar/answer/prompt.py`. Don't loosen the "guide only" rule.
4. Grow `tests/eval_questions.jsonl` toward 50 questions: 25 answerable, 10 rumor,
   10 not covered, 5 off-topic. Re-run after every prompt or guide change.

### 4. Get ready to deploy (prepare; I do the account steps)
1. Write `frontend/README.md` with the build command and output dir for Cloudflare Pages.
2. Walk me through `docs/DEPLOY.md` step by step:
   - pick an always-on host for the backend (a small VM with docker compose is the
     default)
   - Redis (bundled, or Upstash)
   - `.env` values: caps, tokens, `CORS_ORIGINS` with my real domain,
     `TRUST_PROXY_HEADERS=true` behind Cloudflare
3. After I deploy, run the smoke test and `scripts/prefill_cache.py` against the live
   API, then check the live site end to end.

### 5. If time allows, after launch
- A sitemap for answer pages, generated from `/api/trending`.
- An admin view of `/admin/stats` and reports, behind the admin token.
- Cheat codes: once codes are verified, I'll add them to `data/cheat_codes.json` and set
  `"status": "live"`.

Start with task 1, tell me what you found, then go on to task 2.

---

## Steps only I (Akhil) can do

- Create an Anthropic API key in the Claude Console, and set a monthly spend limit and
  alerts there.
- Decide the daily and monthly spend caps (defaults: $25 / $150).
- Register sixstarplaybook.com.
- Create the Cloudflare account (Pages for the site, DNS), the backend host and, if
  wanted, Upstash.
- Write the About page (a real name helps trust) and a contact email for corrections and
  takedowns.
