"""An offline stand-in for anthropic.AsyncAnthropic, used when MOCK_LLM=true and in tests.

It mirrors the parts of the SDK the answer service touches
(`messages.stream(...)` -> `text_stream`, `get_final_message()`), and answers by
matching question words against the guide sections in the system prompt. It is
for wiring and load tests only; answer quality comes from the real model.

Test hooks: a question containing "__refuse__" returns stop_reason "refusal";
"__fail__" raises an API timeout.
"""
from __future__ import annotations

import asyncio
import json
import re
from types import SimpleNamespace
from typing import Any, AsyncIterator

import anthropic
import httpx2 as httpx

_SECTION = re.compile(r'<section id="([^"]+)" title="([^"]+)">\n(.*?)\n</section>', re.S)
_QUESTION = re.compile(r"<question>(.*?)</question>", re.S)
_STOP = set(
    "what when where which who whom whose why how does do did is are was were the a an of in on to for "
    "and or with about can could will would there their they you your gta game get much many".split()
)


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 1 and w not in _STOP}


def _first_sentences(markdown: str, n: int = 2) -> str:
    for block in markdown.split("\n\n"):
        block = block.strip()
        if block and not block.startswith(("|", "#", "-")):
            sentences = re.split(r"(?<=[.!?])\s+", block)
            return " ".join(sentences[:n])
    return "The guide covers this in the linked section."


def mock_answer(system_text: str, question: str) -> dict[str, Any]:
    sections = _SECTION.findall(system_text)
    q_words = _words(question)
    if re.search(r"ignore (your|all|previous|the) (rules|instructions)", question, re.I):
        q_words = set()
    best, best_score = None, 0
    for sid, title, body in sections:
        score = len(q_words & _words(title)) * 3 + len(q_words & _words(body))
        if score > best_score:
            best, best_score = (sid, title, body), score
    if re.search(r"\b(hack|hacks|mod menu|money glitch tool|cheat engine|aimbot)\b", question, re.I):
        return {"answer": "I can't help with hacks or mod menus. Ask about single-player cheat codes instead.",
                "status": "not_allowed", "claims": [], "sources": [], "related_questions": [], "spoiler": False}
    on_topic = bool(re.search(r"gta|grand theft|leonida|vice city|jason|lucia|rockstar", question, re.I))
    if not best and on_topic:
        return {
            "answer": "That isn't confirmed yet. The guide's launch essentials cover the release date, "
                      "platforms and price.",
            "status": "not_confirmed", "claims": [], "sources": ["launch-essentials"],
            "related_questions": ["When does GTA 6 come out?", "Is GTA 6 on PC?", "How much does GTA 6 cost?"],
            "spoiler": False,
        }
    if not best or (best_score < 2 and not on_topic):
        return {
            "answer": "I only cover GTA 6. Try asking when it unlocks or what's in the Ultimate Edition.",
            "status": "off_topic", "claims": [], "sources": [], "related_questions": [], "spoiler": False,
        }
    sid, title, body = best
    text = _first_sentences(body)
    label = "rumor" if sid == "rumors-and-conflicts" else "confirmed"
    if label == "rumor":
        text = "Reports say: " + text
    return {
        "answer": text,
        "status": "answered" if best_score >= 2 else "not_confirmed",
        "claims": [{"text": text[:80], "label": label}],
        "sources": [sid],
        "related_questions": [f"What else is in {title.lower()}?", "Is GTA 6 on PC?", "How much does GTA 6 cost?"],
        "spoiler": False,
    }


class _FakeStream:
    def __init__(self, params: dict[str, Any]) -> None:
        system_text = "\n".join(block["text"] for block in params["system"])
        user = params["messages"][-1]["content"]
        m = _QUESTION.search(user)
        self.question = m.group(1) if m else user
        self.refuse = "__refuse__" in self.question
        self.fail = "__fail__" in self.question
        self.payload = "" if self.refuse else json.dumps(mock_answer(system_text, self.question))
        self.system_chars = len(system_text)

    async def __aenter__(self) -> "_FakeStream":
        if self.fail:
            raise anthropic.APITimeoutError(request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"))
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None

    @property
    async def text_stream(self) -> AsyncIterator[str]:  # type: ignore[override]
        for i in range(0, len(self.payload), 16):
            await asyncio.sleep(0.002)
            yield self.payload[i : i + 16]

    async def get_final_message(self) -> Any:
        usage = SimpleNamespace(
            input_tokens=60,
            output_tokens=max(1, len(self.payload) // 4),
            cache_read_input_tokens=self.system_chars // 4,
            cache_creation_input_tokens=0,
        )
        content = [] if self.refuse else [SimpleNamespace(type="text", text=self.payload)]
        return SimpleNamespace(
            content=content, usage=usage, stop_reason="refusal" if self.refuse else "end_turn",
            stop_details=None, model="mock",
        )


class _FakeMessages:
    def __init__(self, owner: "FakeAsyncAnthropic") -> None:
        self.owner = owner

    def stream(self, **params: Any) -> _FakeStream:
        self.owner.calls.append(params)
        return _FakeStream(params)


class FakeAsyncAnthropic:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.messages = _FakeMessages(self)
