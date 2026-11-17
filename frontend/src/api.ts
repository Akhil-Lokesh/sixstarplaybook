// Talking to the gateway: JSON routes, the /api/ask SSE stream, and the browser id.

export const API_BASE: string = (import.meta.env.VITE_API_BASE ?? "http://127.0.0.1:8000").replace(/\/$/, "");
export const SITE_URL: string = (import.meta.env.VITE_SITE_URL ?? "https://sixstarplaybook.com").replace(/\/$/, "");

export interface TopQuestion { slug: string; question: string; count: number }
export interface Claim { text: string; label: "confirmed" | "rumor" | "not_confirmed" }
export interface Source { id: string; title: string; url: string }
export interface AnswerRecord {
  slug: string;
  question: string;
  answer: string;
  status: "answered" | "not_confirmed" | "off_topic" | "not_allowed";
  claims: Claim[];
  sources: Source[];
  related_questions: string[];
  spoiler: boolean;
  truncated: boolean;
  guide_version: string;
  model: string;
  created_at: string;
  cached?: boolean;
}
export interface Topic { id: string; title: string; summary: string; url: string }
export interface TopicDetail { id: string; title: string; summary: string; markdown: string; is_rumor: boolean; guide_version: string }
export interface CheatCode { name: string; code: string; effect: string; verified: boolean; checked_on: string; notes?: string }
export interface CheatCodes { status: string; message: string; updated_at: string; platforms: Record<string, CheatCode[]> }
export interface NewsItem { date: string; title: string; body: string }
export interface Limits { remaining_hour: number; remaining_day: number; limit_hour: number; limit_day: number; resets_in_seconds: number }

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public retryAfter?: number,
    public topQuestions: TopQuestion[] = [],
  ) {
    super(message);
  }
}

const NETWORK_MESSAGE = "Can't reach the answer service. Check your connection and try again.";

// A random id kept in localStorage; the API counts it with the IP for per-visitor limits.
export const clientId: string = (() => {
  const KEY = "ssp_client_id";
  let id: string | null = null;
  try { id = localStorage.getItem(KEY); } catch { /* storage blocked */ }
  if (!id || !/^[A-Za-z0-9_-]{8,64}$/.test(id)) {
    if (typeof crypto.randomUUID === "function") {
      id = crypto.randomUUID().replace(/-/g, "");
    } else {
      id = Array.from(crypto.getRandomValues(new Uint8Array(16)), (b) => b.toString(16).padStart(2, "0")).join("");
    }
    try { localStorage.setItem(KEY, id); } catch { /* storage blocked */ }
  }
  return id;
})();

async function toError(resp: Response): Promise<ApiError> {
  try {
    const err = (await resp.json()).error ?? {};
    return new ApiError(
      resp.status,
      err.code ?? "unavailable",
      err.message ?? "Something went wrong. Try again.",
      typeof err.retry_after === "number" ? err.retry_after : undefined,
      Array.isArray(err.top_questions) ? err.top_questions : [],
    );
  } catch {
    return new ApiError(resp.status, "unavailable", "Answers are briefly unavailable. Try again in a minute.");
  }
}

async function request(path: string, init: RequestInit): Promise<Response> {
  let resp: Response;
  try {
    resp = await fetch(API_BASE + path, init);
  } catch (e) {
    if ((e as Error).name === "AbortError") throw e;
    throw new ApiError(0, "network", NETWORK_MESSAGE);
  }
  if (!resp.ok) throw await toError(resp);
  return resp;
}

export async function getJSON<T>(path: string, signal?: AbortSignal, withClientId = false): Promise<T> {
  const headers: Record<string, string> = withClientId ? { "X-Client-Id": clientId } : {};
  return (await request(path, { headers, signal })).json();
}

export async function postJSON<T>(path: string, body: unknown): Promise<T> {
  return (await request(path, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Client-Id": clientId },
    body: JSON.stringify(body),
  })).json();
}

export interface StreamError { code: string; message: string; retry_after?: number }
export interface AskHandlers {
  meta(data: { slug: string; cached: boolean; guide_version: string }): void;
  delta(text: string): void;
  answer(record: AnswerRecord): void;
  error(err: StreamError): void;
}

// Reading a text/event-stream body from fetch, one event per blank-line-separated block.
async function readSSE(response: Response, onEvent: (name: string, data: any) => void): Promise<void> {
  const reader = response.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");
    let cut: number;
    while ((cut = buffer.indexOf("\n\n")) !== -1) {
      const block = buffer.slice(0, cut);
      buffer = buffer.slice(cut + 2);
      let name = "message";
      let data = "";
      for (const line of block.split("\n")) {
        if (line.startsWith("event: ")) name = line.slice(7);
        else if (line.startsWith("data: ")) data += line.slice(6);
      }
      onEvent(name, data ? JSON.parse(data) : {});
    }
  }
}

/** Asking a question. Throws ApiError when refused before streaming; resolves when the stream ends. */
export async function askStream(question: string, handlers: AskHandlers, signal: AbortSignal): Promise<void> {
  const resp = await request("/api/ask", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Client-Id": clientId },
    body: JSON.stringify({ question }),
    signal,
  });
  let finished = false;
  try {
    await readSSE(resp, (name, data) => {
      if (name === "meta") handlers.meta(data);
      else if (name === "delta") handlers.delta(data.text ?? "");
      else if (name === "answer") { finished = true; handlers.answer(data); }
      else if (name === "error") { finished = true; handlers.error(data); }
    });
  } catch (e) {
    if ((e as Error).name === "AbortError") throw e;
    if (!finished) { finished = true; handlers.error({ code: "network", message: "The connection dropped mid-answer. Try again." }); }
  }
  if (!finished) handlers.error({ code: "upstream_error", message: "Something went wrong getting that answer. Try again." });
}
