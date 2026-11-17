# Deploy notes

Nothing here has been registered, bought or deployed. Each step that needs an account
is marked **(you)**: Akhil does it.

Target layout (from the plan): static site on Cloudflare Pages, this backend on a small
always-on host, Redis on the same host or Upstash, Cloudflare DNS in front.

## 1. Before anything

- **(you)** Create an Anthropic API key in the Claude Console and set a monthly spend
  limit and alerts there as the backstop.
- **(you)** Register the domain.
- Decide the caps: `DAILY_SPEND_CAP_USD`, `MONTHLY_SPEND_CAP_USD`.
- Generate secrets:
  `python3 -c "import secrets;print(secrets.token_urlsafe(32))"` three times, for
  `INTERNAL_TOKEN`, `ADMIN_TOKEN` and `ANALYTICS_SALT`.

## 2. Backend: option A, one VM with docker compose (recommended)

Any small always-on Linux VM (1 vCPU, 1 GB RAM is enough to start) **(you)**.

```bash
git clone <your repo> && cd sixstarplaybook   # or copy the folder up
cp .env.example .env && nano .env              # key, tokens, caps, CORS_ORIGINS
docker compose up -d --build
curl http://127.0.0.1:8000/api/health
```

The gateway is published on `127.0.0.1:8000` only. Put it on the internet one of two
ways:

- **Cloudflare Tunnel** (no open ports): `cloudflared` maps `api.sixstarplaybook.com` to
  `http://127.0.0.1:8000`. Set `TRUST_PROXY_HEADERS=true`.
- **Caddy or nginx** on the VM with TLS, proxying to `127.0.0.1:8000`, with Cloudflare
  DNS proxied in front. Set `TRUST_PROXY_HEADERS=true`, and firewall the VM so only
  Cloudflare can reach 443. Turn off proxy buffering for `/api/ask`
  (`X-Accel-Buffering: no` is already sent; for Caddy add `flush_interval -1`).

Only set `TRUST_PROXY_HEADERS=true` when every request really comes through your proxy;
otherwise visitors could fake their IP and dodge the limits.

## 3. Backend: option B, a PaaS (Railway, Fly.io, Render paid)

Two ways:

- **Simple:** one service running `python -m sixstar.run_all` with `HOST=0.0.0.0` and
  the gateway port exposed. All five services run in one container.
- **Split:** five services from the same Docker image, each with `SERVICE=<name>` and
  `PORT`, the four internal ones on the private network, and `ANSWER_URL`, `GUARD_URL`,
  `CONTENT_URL`, `ANALYTICS_URL` pointing at their private addresses.

Avoid hosts that sleep when idle for launch night (the plan's note on free Render).

## 4. Redis

The compose file includes Redis with persistence. To use Upstash instead **(you)**,
set `REDIS_URL` to its `rediss://` URL in `.env`; the code uses only basic commands and
small Lua scripts, which Upstash supports. With `APP_ENV=production` the services refuse
to start without `REDIS_URL` (compose supplies one).

## 5. Before launch

```bash
# Eval: each question is one real Claude call (well under a cent each on Haiku 5.5)
python3 scripts/run_eval.py --base https://api.sixstarplaybook.com --admin-token "$ADMIN_TOKEN"
# Pre-fill the answer cache (42 questions in data/prefill_questions.txt; add more)
ADMIN_TOKEN=... python3 scripts/prefill_cache.py --base https://api.sixstarplaybook.com
bash scripts/smoke_test.sh https://api.sixstarplaybook.com
```

Run the eval after every prompt or guide change. With `MOCK_LLM=true` the eval only
checks wiring; a few questions fail there by design because the fake answerer is a
keyword matcher.

## 6. Frontend on Cloudflare Pages

- **(you)** Connect the frontend repo to Cloudflare Pages.
- Set the build variable for the API base (for example `VITE_API_BASE`).
- Add the Pages domain(s) to `CORS_ORIGINS` on the backend, including the
  `*.pages.dev` preview domain if you want previews to work, then restart.

## 7. Updating the guide

1. Edit or re-export `guide/guide.md` (the `tools/docs_xml_to_markdown.py` converter
   turns a Claude Docs XML export into this format; H2 headings become `{#section-id}`).
2. Redeploy, or with the guide mounted as a volume, `POST /admin/reload` on the content
   service with `X-Admin-Token`.
3. The answer service picks up the new version within 60 seconds; old cached answers
   stop matching automatically. Re-run the prefill script.

Cheat codes, starters and what's new live in `data/*.json` and update the same way.
Cheat codes feed the prompt too, so answers about codes stay in sync with the hub page.

## 8. Watching it

```bash
docker compose exec guard python -c "import urllib.request,os;print(urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:8002/admin/spend',headers={'X-Admin-Token':os.environ['ADMIN_TOKEN']})).read().decode())"
docker compose logs -f answer
```

`/admin/stats` on analytics (port 8004) shows questions, cache hit counts, cost, thumbs
up rate, recent questions and reports.
