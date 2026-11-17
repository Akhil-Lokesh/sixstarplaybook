"""End to end through the public gateway, with every service wired in-process and
Claude replaced by the offline fake. No network, no API key."""
import asyncio

import pytest

from sixstar.common.config import get_settings
from tests.conftest import drain_background
from tests.helpers import parse_sse

CID = "test-browser-0001"


async def ask(client, question, cid=CID, **headers):
    h = {"X-Client-Id": cid, **headers} if cid else headers
    resp = await client.post("/api/ask", json={"question": question}, headers=h)
    return resp, (parse_sse(resp.text) if resp.headers.get("content-type", "").startswith("text/event-stream") else None)


def events_of(events, name):
    return [d for e, d in events if e == name]


async def test_health(gateway):
    r = await gateway.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["services"]["answer"]["llm"] == "mock"
    assert set(body["services"]) == {"answer", "guard", "content", "analytics"}


async def test_ask_streams_a_sourced_answer(gateway, fake_llm):
    r, ev = await ask(gateway, "When does GTA 6 come out?")
    assert r.status_code == 200
    names = [e for e, _ in ev]
    assert names[0] == "meta" and names[-1] == "done" and "answer" in names
    assert names.count("delta") >= 2, "answer text should arrive in pieces"
    meta = events_of(ev, "meta")[0]
    final = events_of(ev, "answer")[0]
    assert meta["cached"] is False and meta["slug"] == final["slug"] == "when-does-gta-6-come-out"
    assert "".join(d["text"] for d in events_of(ev, "delta")) == final["answer"]
    assert final["status"] == "answered"
    assert final["sources"] and final["sources"][0]["url"].startswith("/topics/")
    assert len(final["related_questions"]) <= 3
    # The request sent to Claude
    call = fake_llm.calls[0]
    assert call["model"] == "claude-haiku-5-5"
    assert call["system"][-1]["cache_control"]["type"] == "ephemeral"
    assert "<question>When does GTA 6 come out?</question>" in call["messages"][0]["content"]


async def test_repeat_and_variant_questions_hit_the_cache(gateway, fake_llm):
    await ask(gateway, "When does GTA 6 come out?")
    r, ev = await ask(gateway, "when does GTA VI come out", cid="another-browser-1")
    assert events_of(ev, "meta")[0]["cached"] is True
    assert events_of(ev, "answer")[0]["cached"] is True
    assert len(fake_llm.calls) == 1


async def test_concurrent_identical_questions_call_claude_once(gateway, fake_llm):
    results = await asyncio.gather(*(ask(gateway, "How much does GTA 6 cost?", cid=f"browser-{i:06d}")
                                     for i in range(5)))
    assert all(r.status_code == 200 for r, _ in results)
    assert len(fake_llm.calls) == 1
    cached = [events_of(ev, "meta")[0]["cached"] for _, ev in results]
    assert cached.count(False) == 1


async def test_answer_page_and_trending(gateway):
    _, ev = await ask(gateway, "Who are the main characters in GTA 6?")
    slug = events_of(ev, "answer")[0]["slug"]
    await drain_background()
    page = await gateway.get(f"/api/q/{slug}")
    assert page.status_code == 200 and page.json()["slug"] == slug
    assert "normalized" not in page.json()
    assert (await gateway.get("/api/q/no-such-page")).status_code == 404
    trending = (await gateway.get("/api/trending")).json()["items"]
    assert trending[0]["slug"] == slug


async def test_rate_limit_returns_429_with_popular_questions(gateway):
    s = get_settings()
    questions = [f"Tell me about GTA 6 topic number {i}" for i in range(s.rate_per_hour + 1)]
    for q in questions[:-1]:
        r, _ = await ask(gateway, q)
        assert r.status_code == 200
    await drain_background()
    r, _ = await ask(gateway, questions[-1])
    assert r.status_code == 429
    err = r.json()["error"]
    assert err["code"] == "rate_limited"
    assert int(r.headers["Retry-After"]) > 0
    assert isinstance(err["top_questions"], list) and err["top_questions"]
    # Cached answers still work after the limit.
    r, ev = await ask(gateway, questions[0])
    assert r.status_code == 200 and events_of(ev, "meta")[0]["cached"] is True
    limits = (await gateway.get("/api/limits", headers={"X-Client-Id": CID})).json()
    assert limits["remaining_hour"] == 0


async def test_admin_token_bypasses_user_limits(gateway):
    for i in range(get_settings().rate_per_hour + 2):
        r, _ = await ask(gateway, f"GTA 6 prefill question {i}", **{"X-Admin-Token": "test-admin"})
        assert r.status_code == 200


async def test_budget_cap_blocks_new_calls(gateway, monkeypatch):
    monkeypatch.setenv("DAILY_SPEND_CAP_USD", "0.001")
    get_settings.cache_clear()
    try:
        r, _ = await ask(gateway, "Is GTA 6 on PC?")
        assert r.status_code == 503
        assert r.json()["error"]["code"] == "budget_exhausted"
    finally:
        monkeypatch.delenv("DAILY_SPEND_CAP_USD")
        get_settings.cache_clear()
    # The refused request did not leave a reservation behind.
    spend = (await gateway.get("/api/limits", headers={"X-Client-Id": CID})).json()
    assert spend["remaining_hour"] == get_settings().rate_per_hour


async def test_spend_is_settled_to_actual_cost(gateway):
    from sixstar.guard import app as guard_mod
    from sixstar.common.web import service_client

    await ask(gateway, "What is the Leonida setting in GTA 6?")
    await drain_background()
    r = await service_client("guard").get("/admin/spend", headers={"X-Admin-Token": "test-admin"})
    today = r.json()["today_usd"]
    assert 0 < today < get_settings().cost_estimate_usd, "estimate replaced by the (smaller) real cost"
    assert guard_mod  # imported for clarity


async def test_refusal_upstream_error_and_off_topic(gateway):
    _, ev = await ask(gateway, "GTA 6 __refuse__")
    assert events_of(ev, "error")[0]["code"] == "refused"
    assert not events_of(ev, "answer")

    _, ev = await ask(gateway, "GTA 6 __fail__")
    assert events_of(ev, "error")[0]["code"] == "upstream_error"

    _, ev = await ask(gateway, "best pizza dough recipe")
    final = events_of(ev, "answer")[0]
    assert final["status"] == "off_topic" and final["sources"] == []
    await drain_background()
    assert (await gateway.get(f"/api/q/{final['slug']}")).status_code == 404, "off-topic gets no page"


async def test_bad_input(gateway):
    r, _ = await ask(gateway, "??")
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_question"
    r = await gateway.post("/api/ask", json={})
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_request"


async def test_get_ask_for_eventsource(gateway):
    r = await gateway.get("/api/ask", params={"q": "When does GTA 6 come out?", "client_id": CID})
    assert r.status_code == 200
    assert [e for e, _ in parse_sse(r.text)][-1] == "done"


async def test_content_endpoints(gateway):
    topics = (await gateway.get("/api/topics")).json()
    ids = [t["id"] for t in topics["topics"]]
    assert "launch-essentials" in ids and "sources" not in ids and "site-name-ideas" not in ids
    t = (await gateway.get("/api/topics/rumors-and-conflicts")).json()
    assert t["is_rumor"] is True and t["markdown"]
    assert (await gateway.get("/api/topics/nope")).status_code == 404
    codes = await gateway.get("/api/cheat-codes")
    assert codes.json()["status"] == "none_confirmed"
    assert "max-age" in codes.headers["cache-control"]
    assert (await gateway.get("/api/starters")).json()
    assert (await gateway.get("/api/whats-new")).status_code == 200
    assert (await gateway.get("/api/guide/version")).json()["version"].startswith("g-")


async def test_feedback_and_report(gateway):
    body = {"slug": "when-does-gta-6-come-out", "helpful": True}
    assert (await gateway.post("/api/feedback", json=body, headers={"X-Client-Id": CID})).json() == {"ok": True}
    dup = await gateway.post("/api/feedback", json=body, headers={"X-Client-Id": CID})
    assert dup.json()["duplicate"] is True
    assert (await gateway.post("/api/report", json={"slug": "x", "note": "wrong date"})).json()["ok"]


async def test_cors(gateway):
    r = await gateway.options("/api/ask", headers={
        "Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type,x-client-id"})
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == "http://localhost:5173"
    r = await gateway.options("/api/ask", headers={
        "Origin": "https://evil.example", "Access-Control-Request-Method": "POST"})
    assert "access-control-allow-origin" not in r.headers


async def test_internal_routes_need_the_token(gateway):
    from sixstar.answer import app as answer_mod
    import httpx2 as httpx

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=answer_mod.app), base_url="http://a") as c:
        r = await c.post("/internal/ask", json={"question": "x"})
        assert r.status_code == 403


async def test_guide_change_invalidates_cached_answers(gateway, fake_llm, monkeypatch):
    from sixstar.content import app as content_mod

    await ask(gateway, "When does GTA 6 come out?")
    real = content_mod.combined

    def bumped():
        version, sections, text = real()
        return version + "x", sections, text

    monkeypatch.setattr(content_mod, "combined", bumped)
    _, ev = await ask(gateway, "When does GTA 6 come out?", cid="another-browser-2")
    assert events_of(ev, "meta")[0]["cached"] is False
    assert len(fake_llm.calls) == 2


async def test_guard_down_fails_closed_with_a_clean_error(gateway):
    import httpx2 as httpx
    from sixstar.common.web import set_transport

    class Down(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            raise httpx.ConnectError("down", request=request)

    set_transport("guard", Down())
    r, _ = await ask(gateway, "Is GTA 6 on PC at launch?")
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "unavailable"
    assert r.headers["Retry-After"] == "30"
