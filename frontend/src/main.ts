import "./styles.css";
import {
  ApiError, AnswerRecord, CheatCodes, Limits, NewsItem, SITE_URL, StreamError, Topic, TopicDetail, TopQuestion,
  askStream, getJSON, postJSON,
} from "./api";
import { esc, inline, md } from "./md";
import { STATIC_PAGES } from "./pages";
import { sceneHTML } from "./scene";

const UNLOCK = Date.parse("2026-11-19T05:00:00Z"); // midnight Eastern on Nov 19 = 9 PM PT on Nov 18
const SITE_NAME = "Six Star Playbook";
const AI_NOTICE = "Written by AI from our guide. Can be wrong; check the linked source.";
const LIMIT_CODES = new Set(["rate_limited", "busy", "budget_exhausted"]);
const TAG_LABEL: Record<string, string> = { confirmed: "Confirmed", rumor: "Rumor", not_confirmed: "Not confirmed" };
const PLATFORM_LABEL: Record<string, string> = { ps5: "PS5", xbox_series: "Xbox Series X|S" };

const app = document.getElementById("app")!;
let view = 0;                              // bumped on every navigation; stale async work checks it
let stream: AbortController | null = null; // the answer being streamed, if any
let ticker: number | undefined;
let starters: string[] | null = null;
let topics: Topic[] | null = null;

// ---------- small helpers ----------

const $ = <T extends Element = HTMLElement>(sel: string, root: ParentNode = document) => root.querySelector<T>(sel);

function setMeta(title: string, description: string, opts: { noindex?: boolean } = {}): void {
  const full = title ? `${title} | ${SITE_NAME}` : `${SITE_NAME}: GTA 6 questions, answered fast`;
  const url = SITE_URL + location.pathname;
  document.title = full;
  const set = (sel: string, attr: string, value: string) => $(sel, document.head)?.setAttribute(attr, value);
  set('meta[name="description"]', "content", description);
  set('meta[property="og:title"]', "content", full);
  set('meta[property="og:description"]', "content", description);
  set('meta[property="og:url"]', "content", url);
  set('link[rel="canonical"]', "href", url);
  let robots = $('meta[name="robots"]', document.head);
  if (opts.noindex) {
    if (!robots) { robots = document.createElement("meta"); robots.setAttribute("name", "robots"); document.head.append(robots); }
    robots.setAttribute("content", "noindex");
  } else robots?.remove();
}

function fmtDate(iso: string): string {
  const d = new Date(iso.length === 10 ? iso + "T00:00:00Z" : iso);
  if (isNaN(d.getTime())) return iso;
  return new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" }).format(d);
}

function fmtWait(seconds: number): string {
  if (seconds < 90) return `${Math.max(1, Math.round(seconds))} seconds`;
  if (seconds < 5400) return `${Math.round(seconds / 60)} minutes`;
  return `${Math.round(seconds / 3600)} hours`;
}

function askForm(placeholder = "Ask a GTA 6 question", value = ""): string {
  return `
<form class="ask-form" novalidate>
  <label class="sr-only" for="ask-input">Your GTA 6 question</label>
  <input id="ask-input" name="q" type="text" maxlength="300" autocomplete="off" enterkeyhint="send"
         placeholder="${esc(placeholder)}" value="${esc(value)}">
  <button type="submit">Ask</button>
</form>
<p class="limits" data-limits aria-live="polite"></p>`;
}

function chips(questions: string[]): string {
  return `<ul class="chips">${questions.map((q) =>
    `<li><button type="button" class="chip" data-ask="${esc(q)}">${esc(q)}</button></li>`).join("")}</ul>`;
}

function topQuestionLinks(items: TopQuestion[]): string {
  if (!items.length) return "";
  return `<div class="top-questions"><h2 class="label">Already answered</h2><ul class="link-list">${items.map((t) =>
    `<li><a href="/q/${encodeURIComponent(t.slug)}">${esc(t.question)}</a></li>`).join("")}</ul></div>`;
}

function errorBox(message: string, extra = ""): string {
  return `<div class="notice-box" role="alert"><p>${esc(message)}</p>${extra}</div>`;
}

async function loadStarters(): Promise<string[]> {
  if (!starters) starters = (await getJSON<{ starters: string[] }>("/api/starters")).starters;
  return starters;
}

async function loadTopics(): Promise<Topic[]> {
  if (!topics) topics = (await getJSON<{ topics: Topic[] }>("/api/topics")).topics;
  return topics;
}

async function refreshLimits(): Promise<void> {
  const slots = document.querySelectorAll<HTMLElement>("[data-limits]");
  if (!slots.length) return;
  try {
    const l = await getJSON<Limits>("/api/limits", undefined, true);
    const left = Math.min(l.remaining_hour, l.remaining_day);
    const text = left <= 0
      ? `No questions left for now. Resets in about ${fmtWait(l.resets_in_seconds)}. Answered questions still open.`
      : `${left} question${left === 1 ? "" : "s"} left this ${l.remaining_day < l.remaining_hour ? "day" : "hour"}`;
    document.querySelectorAll<HTMLElement>("[data-limits]").forEach((el) => { el.textContent = text; });
  } catch { /* optional nicety; stay quiet */ }
}

// ---------- countdown ----------

function countdownHTML(): string {
  return `<div class="countdown" data-countdown role="timer" aria-label="Time until GTA 6 unlocks"></div>`;
}

function tick(): void {
  const el = $("[data-countdown]");
  if (!el) return;
  const left = UNLOCK - Date.now();
  if (left <= 0) {
    el.innerHTML = `<p class="out-now">GTA 6 is out.</p>`;
    $("[data-countdown-label]")?.replaceChildren("Unlocked Nov 19, 2026");
    return;
  }
  const s = Math.floor(left / 1000);
  const parts: [number, string][] = [
    [Math.floor(s / 86400), "days"], [Math.floor(s / 3600) % 24, "hrs"], [Math.floor(s / 60) % 60, "min"], [s % 60, "sec"],
  ];
  el.innerHTML = parts.map(([n, unit]) =>
    `<span class="cd-cell"><span class="cd-num">${String(n).padStart(2, "0")}</span><span class="cd-unit">${unit}</span></span>`).join("");
  el.setAttribute("aria-label", `GTA 6 unlocks in ${parts[0][0]} days ${parts[1][0]} hours ${parts[2][0]} minutes`);
}

function localUnlock(): string {
  try {
    return new Intl.DateTimeFormat(undefined, { weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit", timeZoneName: "short" }).format(UNLOCK);
  } catch { return "Nov 18, 9:00 PM PT"; }
}

// ---------- pages ----------

function renderHome(token: number): void {
  setMeta("", "Ask anything about GTA 6. Short, sourced answers from our A to Z guide, with Confirmed, Rumor and Not confirmed tags. Unofficial fan site.");
  app.innerHTML = `
<section class="hero">
  ${sceneHTML()}
  <div class="hero-inner wrap">
    <p class="eyebrow" data-countdown-label>GTA 6 unlocks in</p>
    ${countdownHTML()}
    <p class="unlock-local">${esc(localUnlock())} where you are</p>
    <h1>Ask anything about GTA&nbsp;6.</h1>
    <p class="lede">Short answers from our A to Z guide. Every claim tagged, every answer sourced.</p>
    <div class="ask-card">
      ${askForm()}
      <div data-starters></div>
    </div>
  </div>
</section>
<div class="wrap home-grid">
  <section class="block" data-trending hidden>
    <h2>Trending now</h2>
    <ol class="trending"></ol>
  </section>
  <section class="block">
    <h2>Browse the guide</h2>
    <div class="tiles" data-tiles>${'<div class="tile skeleton"></div>'.repeat(4)}</div>
  </section>
  <section class="block" data-news hidden>
    <div class="block-head"><h2>What's new</h2><a class="more" href="/whats-new">All updates</a></div>
    <ul class="news"></ul>
  </section>
</div>`;
  tick();
  ticker = window.setInterval(tick, 1000);
  refreshLimits();

  loadStarters().then((list) => {
    if (token === view) $("[data-starters]")!.innerHTML = chips(list);
  }).catch(() => { /* the ask box still works without chips */ });

  getJSON<{ items: TopQuestion[] }>("/api/trending?limit=8").then(({ items }) => {
    if (token !== view || !items.length) return;
    const box = $("[data-trending]")!;
    $(".trending", box)!.innerHTML = items.map((t) =>
      `<li><a href="/q/${encodeURIComponent(t.slug)}">${esc(t.question)}</a></li>`).join("");
    box.hidden = false;
  }).catch(() => {});

  loadTopics().then((list) => {
    if (token === view) $("[data-tiles]")!.innerHTML = tiles(list);
  }).catch((e) => {
    if (token === view) $("[data-tiles]")!.innerHTML = errorBox(e instanceof ApiError ? e.message : "Couldn't load the guide. Try again.");
  });

  getJSON<{ items: NewsItem[] }>("/api/whats-new").then(({ items }) => {
    if (token !== view || !items.length) return;
    const box = $("[data-news]")!;
    $(".news", box)!.innerHTML = items.slice(0, 3).map(newsItem).join("");
    box.hidden = false;
  }).catch(() => {});
}

function tiles(list: Topic[]): string {
  return list.map((t, n) => `
<a class="tile${t.id.includes("rumor") ? " tile-rumor" : ""}" href="/topics/${encodeURIComponent(t.id)}">
  <span class="tile-num">${String(n + 1).padStart(2, "0")}</span>
  <span class="tile-title">${esc(t.title)}</span>
  <span class="tile-sum">${inline(t.summary, { links: false })}</span>
</a>`).join("");
}

function newsItem(item: NewsItem): string {
  return `<li><time datetime="${esc(item.date)}">${esc(fmtDate(item.date))}</time><h3>${esc(item.title)}</h3><p>${inline(item.body)}</p></li>`;
}

function pageShell(title: string, body: string, eyebrow = ""): string {
  return `<article class="page wrap">${eyebrow ? `<p class="eyebrow">${eyebrow}</p>` : ""}<h1>${esc(title)}</h1>${body}</article>`;
}

function loading(title: string): void {
  app.innerHTML = pageShell(title, `<div class="skeleton-lines" aria-hidden="true"><i></i><i></i><i></i></div><p class="sr-only" role="status">Loading</p>`);
}

function failed(title: string, e: unknown): void {
  const message = e instanceof ApiError ? e.message : "Something went wrong. Try again.";
  app.innerHTML = pageShell(title, errorBox(message, `<p><a class="btn-ghost" href="${esc(location.pathname)}">Try again</a> <a class="btn-ghost" href="/">Home</a></p>`));
}

async function renderTopics(token: number): Promise<void> {
  setMeta("Topics", "Browse the GTA 6 A to Z guide by topic: launch, editions, trailers, Leonida, characters, gameplay and labeled rumors.");
  loading("The guide, by topic");
  try {
    const list = await loadTopics();
    if (token !== view) return;
    app.innerHTML = pageShell("The guide, by topic", `<div class="tiles">${tiles(list)}</div>`, "A to Z");
  } catch (e) { if (token === view) failed("The guide, by topic", e); }
}

async function renderTopic(token: number, id: string): Promise<void> {
  setMeta("Topic", "A section of the GTA 6 A to Z guide.");
  loading("Loading topic");
  try {
    const t = await getJSON<TopicDetail>(`/api/topics/${encodeURIComponent(id)}`);
    if (token !== view) return;
    setMeta(t.title, inline(t.summary, { links: false }).replace(/<[^>]+>/g, "").replace(/&amp;/g, "&").replace(/&#39;/g, "'").replace(/&quot;/g, '"').slice(0, 200));
    const banner = t.is_rumor
      ? `<p class="rumor-banner"><span class="tag tag-rumor">Rumor</span> Nothing on this page is confirmed. Treat it as a maybe.</p>` : "";
    app.innerHTML = `
<article class="page wrap">
  <p class="eyebrow"><a href="/topics">Topics</a></p>
  <h1>${esc(t.title)}</h1>
  ${banner}
  <div class="prose">${md(t.markdown)}</div>
  <section class="ask-more">
    <h2>Still wondering?</h2>
    ${askForm(`Ask about ${t.title.toLowerCase()}`)}
  </section>
</article>`;
    refreshLimits();
  } catch (e) {
    if (token !== view) return;
    if (e instanceof ApiError && e.code === "not_found") notFound("That topic isn't in the guide.");
    else failed("Topic", e);
  }
}

async function renderCheats(token: number): Promise<void> {
  setMeta("Cheat codes", "GTA 6 cheat codes for PS5 and Xbox Series X|S, added only after two independent checks.");
  loading("Cheat codes");
  try {
    const data = await getJSON<CheatCodes>("/api/cheat-codes");
    if (token !== view) return;
    const platforms = Object.entries(data.platforms ?? {}).filter(([, codes]) => codes.length);
    const updated = data.updated_at ? `<p class="stamp">Last checked ${esc(fmtDate(data.updated_at))}</p>` : "";
    const body = platforms.length
      ? platforms.map(([key, codes]) => `
<section class="platform">
  <h2>${esc(PLATFORM_LABEL[key] ?? key)}</h2>
  <div class="table-wrap" tabindex="0" role="region" aria-label="${esc(PLATFORM_LABEL[key] ?? key)} cheat codes"><table class="codes">
    <thead><tr><th scope="col">Cheat</th><th scope="col">Code</th><th scope="col">Effect</th><th scope="col">Status</th><th scope="col">Checked</th></tr></thead>
    <tbody>${codes.map((c) => `<tr>
      <td>${esc(c.name)}</td><td><code>${esc(c.code)}</code></td>
      <td>${esc(c.effect)}${c.notes ? `<br><small>${esc(c.notes)}</small>` : ""}</td>
      <td><span class="tag ${c.verified ? "tag-confirmed" : "tag-not_confirmed"}">${c.verified ? "Verified" : "Unverified"}</span></td>
      <td><time datetime="${esc(c.checked_on)}">${esc(fmtDate(c.checked_on))}</time></td></tr>`).join("")}</tbody>
  </table></div>
</section>`).join("")
      : `<div class="empty-state"><p class="empty-big">${esc(data.message || "No codes confirmed yet.")}</p><p>Check back after launch. Codes land here the moment they pass.</p></div>`;
    app.innerHTML = pageShell("Cheat codes", (platforms.length && data.message ? `<p class="lede">${esc(data.message)}</p>` : "") + body + updated, "PS5 · Xbox Series X|S");
  } catch (e) { if (token === view) failed("Cheat codes", e); }
}

async function renderNews(token: number): Promise<void> {
  setMeta("What's new", "Updates to the Six Star Playbook GTA 6 guide.");
  loading("What's new");
  try {
    const { items } = await getJSON<{ items: NewsItem[] }>("/api/whats-new");
    if (token !== view) return;
    app.innerHTML = pageShell("What's new", items.length
      ? `<ul class="news news-full">${items.map(newsItem).join("")}</ul>`
      : `<div class="empty-state"><p class="empty-big">Nothing new yet.</p></div>`, "Guide updates");
  } catch (e) { if (token === view) failed("What's new", e); }
}

function renderStatic(path: string): void {
  const page = STATIC_PAGES[path];
  setMeta(page.title, page.description);
  app.innerHTML = pageShell(page.title, `<div class="prose">${page.html}</div>`);
}

function notFound(message = "That page doesn't exist."): void {
  setMeta("Not found", "Page not found.", { noindex: true });
  app.innerHTML = pageShell("Wrong turn.", `
<p class="lede">${esc(message)}</p>
<section class="ask-more"><h2>Ask instead</h2>${askForm()}</section>
<p><a class="btn-ghost" href="/">Back home</a></p>`, "404");
  refreshLimits();
}

// ---------- answers ----------

function answerShell(question: string): void {
  app.innerHTML = `
<article class="page wrap answer-page">
  <p class="eyebrow">Question</p>
  <h1 class="question" data-question>${esc(question)}</h1>
  <section class="answer-card" data-card aria-busy="true">
    <p class="answer-state" data-state role="status">Checking the guide…</p>
    <div class="answer-body" data-body></div>
    <div data-extra></div>
  </section>
  <div data-after></div>
  <section class="ask-more">
    <h2>Ask another</h2>
    ${askForm()}
  </section>
</article>`;
}

function showAnswer(a: AnswerRecord): void {
  const card = $("[data-card]");
  if (!card) return;
  const hasPage = (a.status === "answered" || a.status === "not_confirmed") && !a.truncated;
  card.setAttribute("aria-busy", "false");
  card.dataset.slug = a.slug;
  card.classList.remove("streaming");
  $("[data-question]")!.textContent = a.question;

  const state = $("[data-state]")!;
  const stateText: Record<string, string> = {
    answered: "", not_confirmed: "Not confirmed", off_topic: "Off topic", not_allowed: "Can't help with that",
  };
  state.innerHTML = stateText[a.status] ? `<span class="tag tag-not_confirmed">${stateText[a.status]}</span>` : "";
  state.hidden = !stateText[a.status];

  const body = $("[data-body]")!;
  body.innerHTML = md(a.answer);
  let spoilerGate = "";
  if (a.spoiler) {
    body.hidden = true;
    spoilerGate = `<div class="spoiler-gate" data-spoiler><p>This answer has story spoilers.</p><button type="button" class="btn-ghost" data-action="spoiler">Show spoiler</button></div>`;
  }

  const claims = a.claims.length ? `<ul class="claims"${a.spoiler ? " hidden" : ""} data-claims>${a.claims.map((c) =>
    `<li><span class="tag tag-${esc(c.label)}">${TAG_LABEL[c.label] ?? esc(c.label)}</span><span>${inline(c.text, { links: false })}</span></li>`).join("")}</ul>` : "";
  const sources = a.sources.length ? `<p class="sources"><span class="label">Source${a.sources.length > 1 ? "s" : ""}</span>${a.sources.map((s) =>
    `<a href="/topics/${encodeURIComponent(s.id)}">${esc(s.title)}</a>`).join("")}</p>` : "";
  const cut = a.truncated ? `<p class="cut-note">This answer was cut short. Ask again for the full version.</p>` : "";
  const actions = hasPage ? `
<div class="actions" data-actions>
  <span class="label" id="fb-label">Was this helpful?</span>
  <button type="button" class="btn-ghost" data-action="vote" data-helpful="1" aria-describedby="fb-label">Helpful</button>
  <button type="button" class="btn-ghost" data-action="vote" data-helpful="0" aria-describedby="fb-label">Not helpful</button>
  <span class="spacer"></span>
  <button type="button" class="btn-ghost" data-action="copy">Copy link</button>
  <button type="button" class="btn-ghost" data-action="report-toggle" aria-expanded="false" aria-controls="report-form">Report</button>
</div>
<form class="report-form" id="report-form" hidden>
  <label for="report-note">What's wrong with this answer? (optional)</label>
  <textarea id="report-note" maxlength="500" rows="3"></textarea>
  <button type="submit" class="btn-ghost">Send report</button>
</form>
<p class="action-status" data-action-status role="status"></p>` : "";

  $("[data-extra]")!.innerHTML = `${spoilerGate}${cut}${claims}${sources}<p class="ai-notice">${AI_NOTICE}</p>${actions}`;

  const after = $("[data-after]")!;
  if (a.status === "off_topic" || a.status === "not_allowed") {
    after.innerHTML = `<section class="related"><h2 class="label">Try one of these</h2><div data-retry-starters></div></section>`;
    loadStarters().then((list) => { const slot = $("[data-retry-starters]"); if (slot) slot.innerHTML = chips(list); }).catch(() => {});
  } else if (a.related_questions.length) {
    const related = a.related_questions.filter((q) => q.toLowerCase() !== a.question.toLowerCase());
    after.innerHTML = related.length ? `<section class="related"><h2 class="label">Related</h2>${chips(related)}</section>` : "";
  }

  const plain = a.answer.replace(/[*_`#]/g, "").replace(/\[([^\]]+)\]\([^)]*\)/g, "$1").replace(/\s+/g, " ").trim();
  setMeta(a.question, a.spoiler ? "A sourced GTA 6 answer (contains spoilers)." : plain.slice(0, 200), { noindex: !hasPage });
}

function showAskError(question: string, err: StreamError, top: TopQuestion[] = []): void {
  const card = $("[data-card]");
  if (!card) return;
  card.setAttribute("aria-busy", "false");
  card.classList.remove("streaming");
  card.classList.add("failed");
  $("[data-state]")!.hidden = true;
  $("[data-body]")!.innerHTML = "";
  const limited = LIMIT_CODES.has(err.code);
  const wait = err.retry_after ? `<p class="wait">Try again in about ${fmtWait(err.retry_after)}.</p>` : "";
  const retry = err.code === "invalid_question" || err.code === "invalid_request" || err.code === "refused"
    ? "" : `<p><button type="button" class="btn-ghost" data-ask="${esc(question)}">Try again</button></p>`;
  $("[data-extra]")!.innerHTML = errorBox(err.message || "Something went wrong. Try again.", wait + retry) + (limited ? topQuestionLinks(top) : "");
  if (!limited || !top.length) {
    const after = $("[data-after]")!;
    after.innerHTML = `<section class="related"><h2 class="label">Popular questions</h2><div data-retry-starters></div></section>`;
    loadStarters().then((list) => { const slot = $("[data-retry-starters]"); if (slot) slot.innerHTML = chips(list); }).catch(() => { after.innerHTML = ""; });
  }
  setMeta("Ask", "Ask a GTA 6 question.", { noindex: true });
}

async function ask(raw: string, push = true): Promise<void> {
  const question = raw.replace(/\s+/g, " ").trim().slice(0, 300);
  if (!question) { $<HTMLInputElement>("#ask-input")?.focus(); return; }
  const token = leaveView();
  const ctl = stream = new AbortController();
  const askUrl = "/ask?q=" + encodeURIComponent(question);
  if (push && location.pathname + location.search !== askUrl) history.pushState(null, "", askUrl);
  setMeta("Ask", "Ask a GTA 6 question.", { noindex: true });
  answerShell(question);
  arrive();

  let text = "";
  const body = $("[data-body]")!;
  const live = () => token === view;
  try {
    await askStream(question, {
      meta(m) {
        if (!live()) return;
        history.replaceState(null, "", "/q/" + encodeURIComponent(m.slug));
        $("[data-state]")!.textContent = m.cached ? "From the playbook" : "Writing your answer…";
        $("[data-card]")!.classList.add("streaming");
      },
      delta(t) {
        if (!live()) return;
        text += t;
        body.textContent = text;
      },
      answer(record) {
        if (!live()) return;
        if (record.status === "off_topic" || record.status === "not_allowed" || record.truncated) history.replaceState(null, "", askUrl);
        showAnswer(record);
      },
      error(err) {
        if (!live()) return;
        history.replaceState(null, "", askUrl);
        showAskError(question, err);
      },
    }, ctl.signal);
  } catch (e) {
    if (!live() || (e as Error).name === "AbortError") return;
    if (e instanceof ApiError) showAskError(question, { code: e.code, message: e.message, retry_after: e.retryAfter }, e.topQuestions);
    else showAskError(question, { code: "internal_error", message: "Something went wrong. Try again." });
  } finally {
    if (stream === ctl) stream = null;
    if (live()) refreshLimits();
  }
}

async function renderAnswerPage(token: number, slug: string): Promise<void> {
  setMeta("Answer", "A sourced GTA 6 answer.");
  answerShell(slug.replace(/-/g, " "));
  $("[data-state]")!.textContent = "Opening the playbook…";
  try {
    const record = await getJSON<AnswerRecord>(`/api/q/${encodeURIComponent(slug)}`);
    if (token !== view) return;
    showAnswer(record);
    refreshLimits();
  } catch (e) {
    if (token !== view) return;
    if (e instanceof ApiError && e.code === "not_found") {
      setMeta("No answer yet", "No answer page for that question yet.", { noindex: true });
      app.innerHTML = pageShell("No answer here yet.", `
<p class="lede">That answer page doesn't exist or has expired. Ask the question and we'll write it fresh.</p>
<section class="ask-more">${askForm("Ask a GTA 6 question", slug.replace(/-/g, " "))}</section>`, "404");
      refreshLimits();
    } else failed("Answer", e);
  }
}

// ---------- router ----------

function leaveView(): number {
  stream?.abort();
  stream = null;
  window.clearInterval(ticker);
  return ++view;
}

function arrive(): void {
  window.scrollTo(0, 0);
  app.focus({ preventScroll: true });
  const path = location.pathname;
  document.querySelectorAll<HTMLAnchorElement>(".site-nav a").forEach((a) => {
    const href = a.getAttribute("href")!;
    if (path === href || path.startsWith(href + "/")) a.setAttribute("aria-current", "page");
    else a.removeAttribute("aria-current");
  });
}

function route(): void {
  const path = location.pathname.replace(/\/+$/, "") || "/";
  if (path === "/ask") {
    const q = new URLSearchParams(location.search).get("q") ?? "";
    if (q.trim()) { void ask(q, false); return; }
    history.replaceState(null, "", "/");
    return route();
  }
  const token = leaveView();
  let m: RegExpExecArray | null;
  if (path === "/") renderHome(token);
  else if ((m = /^\/q\/([^/]+)$/.exec(path))) void renderAnswerPage(token, safeDecode(m[1]));
  else if (path === "/topics") void renderTopics(token);
  else if ((m = /^\/topics\/([^/]+)$/.exec(path))) void renderTopic(token, safeDecode(m[1]));
  else if (path === "/cheat-codes") void renderCheats(token);
  else if (path === "/whats-new") void renderNews(token);
  else if (path in STATIC_PAGES) renderStatic(path);
  else notFound();
  arrive();
}

function safeDecode(part: string): string {
  try { return decodeURIComponent(part); } catch { return part; }
}

function navigate(href: string): void {
  if (href !== location.pathname + location.search) history.pushState(null, "", href);
  route();
}

// ---------- events ----------

document.addEventListener("click", (e) => {
  const target = e.target as Element;

  const askBtn = target.closest<HTMLElement>("[data-ask]");
  if (askBtn) { e.preventDefault(); void ask(askBtn.dataset.ask ?? ""); return; }

  const action = target.closest<HTMLButtonElement>("[data-action]");
  if (action) { e.preventDefault(); void handleAction(action); return; }

  const link = target.closest<HTMLAnchorElement>("a[href]");
  if (!link || e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
  const href = link.getAttribute("href")!;
  if (link.target === "_blank" || !href.startsWith("/") || href.startsWith("//")) return;
  e.preventDefault();
  navigate(href);
});

document.addEventListener("submit", (e) => {
  const form = e.target as HTMLFormElement;
  if (form.matches(".ask-form")) {
    e.preventDefault();
    void ask(form.querySelector<HTMLInputElement>("input[name=q]")!.value);
  } else if (form.matches(".report-form")) {
    e.preventDefault();
    void sendReport(form);
  }
});

function actionStatus(text: string): void {
  const el = $("[data-action-status]");
  if (el) el.textContent = text;
}

async function handleAction(btn: HTMLButtonElement): Promise<void> {
  const card = btn.closest<HTMLElement>("[data-card]");
  const slug = card?.dataset.slug ?? "";
  switch (btn.dataset.action) {
    case "spoiler": {
      $("[data-body]")!.hidden = false;
      $("[data-claims]")?.removeAttribute("hidden");
      $("[data-spoiler]")?.remove();
      $("[data-body]")!.setAttribute("tabindex", "-1");
      $("[data-body]")!.focus();
      break;
    }
    case "vote": {
      const buttons = card!.querySelectorAll<HTMLButtonElement>('[data-action="vote"]');
      buttons.forEach((b) => { b.disabled = true; });
      btn.classList.add("picked");
      try {
        await postJSON("/api/feedback", { slug, helpful: btn.dataset.helpful === "1" });
        actionStatus("Thanks. Noted.");
      } catch (err) {
        buttons.forEach((b) => { b.disabled = false; });
        btn.classList.remove("picked");
        actionStatus(err instanceof ApiError ? err.message : "Couldn't send that. Try again.");
      }
      break;
    }
    case "copy": {
      const url = `${SITE_URL}/q/${encodeURIComponent(slug)}`;
      try {
        await navigator.clipboard.writeText(url);
        actionStatus("Link copied.");
      } catch {
        actionStatus(url);
      }
      break;
    }
    case "report-toggle": {
      const form = $<HTMLFormElement>("#report-form")!;
      form.hidden = !form.hidden;
      btn.setAttribute("aria-expanded", String(!form.hidden));
      if (!form.hidden) form.querySelector("textarea")!.focus();
      break;
    }
  }
}

async function sendReport(form: HTMLFormElement): Promise<void> {
  const slug = form.closest<HTMLElement>("[data-card]")?.dataset.slug ?? "";
  const submit = form.querySelector<HTMLButtonElement>("button")!;
  submit.disabled = true;
  try {
    await postJSON("/api/report", { slug, note: form.querySelector("textarea")!.value.trim().slice(0, 500) });
    form.hidden = true;
    const toggle = $<HTMLButtonElement>('[data-action="report-toggle"]');
    if (toggle) { toggle.disabled = true; toggle.setAttribute("aria-expanded", "false"); }
    actionStatus("Report sent. Thanks for flagging it.");
  } catch (err) {
    submit.disabled = false;
    actionStatus(err instanceof ApiError ? err.message : "Couldn't send the report. Try again.");
  }
}

window.addEventListener("popstate", route);
route();
