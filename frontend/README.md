# Six Star Playbook frontend

Static site (Vite + plain TypeScript, no framework). Talks to the backend gateway over
`/api/*`; see `../HANDOFF.md` and `../docs/API.md`.

## Run locally

```bash
# 1. backend with fake answers (from the repo root, no API key needed)
MOCK_LLM=true .venv/bin/python -m sixstar.run_all      # http://127.0.0.1:8000

# 2. frontend
cd frontend
npm install
npm run dev                                            # http://localhost:5173
```

Open `http://localhost:5173` (not `127.0.0.1:5173`): the backend's default CORS list
allows the `localhost` origin.

## Build

```bash
npm run build      # type-checks, then writes static files to dist/
npm run preview    # serve dist/ locally
```

## Cloudflare Pages settings

| Setting | Value |
| --- | --- |
| Root directory | `frontend` |
| Build command | `npm run build` |
| Build output directory | `dist` |
| Environment variable | `VITE_API_BASE=https://api.sixstarplaybook.com` (your gateway URL, no trailing slash) |
| Environment variable (optional) | `VITE_SITE_URL=https://sixstarplaybook.com` (used for Copy link and canonical URLs) |

`public/_redirects` sends every unknown path to `index.html`, so `/q/<slug>` and
`/topics/<id>` load directly. The backend must list the site's origin in `CORS_ORIGINS`.

## Layout

| File | What it does |
| --- | --- |
| `index.html` | Shell: header, footer with the required disclaimer, meta and Open Graph tags |
| `src/main.ts` | Router, pages, the ask flow and all event handling |
| `src/api.ts` | API base URL, browser id (`X-Client-Id`), JSON helpers, SSE reader for `/api/ask` |
| `src/md.ts` | Small Markdown renderer; escapes all HTML first |
| `src/scene.ts` | Hero art drawn in code (sun, skyline, palms). Original, no game assets |
| `src/pages.ts` | About, Accuracy, Privacy, Terms, Contact text. **Drafts and placeholders are marked in gold boxes; replace them before launch** |
| `src/styles.css` | Design tokens from `HANDOFF.md` and all styles |
| `public/` | `_redirects`, `robots.txt`, `favicon.svg`, `og.png` (share image) |

## Routes

`/`, `/q/<slug>`, `/topics`, `/topics/<id>`, `/cheat-codes`, `/whats-new`, `/about`,
`/about/accuracy`, `/privacy`, `/terms`, `/contact`. `/ask?q=...` asks a question on
load; the URL becomes `/q/<slug>` once the answer starts.
