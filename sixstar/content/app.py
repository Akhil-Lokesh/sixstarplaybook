"""Content service: the guide (ingestion and versioning), topic pages, cheat codes,
starter questions and the what's-new feed.

Owns: guide/guide.md and the JSON files in data/. Stateless otherwise.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Any

from fastapi import Depends

from ..common.config import get_settings
from ..common.web import ApiError, make_app, require_admin, require_internal
from .guide import Guide, Section, parse_guide

log = logging.getLogger(__name__)

_state: dict[str, Any] = {"guide": None, "loaded_at": 0.0}


def load_guide(force: bool = False) -> Guide:
    if _state["guide"] is None or force:
        settings = get_settings()
        text = Path(settings.guide_path).read_text(encoding="utf-8")
        guide = parse_guide(text, settings.exclude_sections)
        if not guide.sections:
            raise RuntimeError(f"No sections found in {settings.guide_path}")
        _state["guide"] = guide
        _state["loaded_at"] = time.time()
        log.info("guide loaded: %s sections, version %s", len(guide.sections), guide.version)
    return _state["guide"]


def _data(name: str) -> Any:
    path = Path(get_settings().data_dir) / name
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ApiError(404, "not_found", f"{name} is missing") from None


async def _health() -> dict[str, Any]:
    version, sections, _ = combined()
    return {"guide_version": version, "sections": len(sections)}


app = make_app("content", _health)


def _topic_url(section_id: str) -> str:
    return f"/topics/{section_id}"


def cheat_codes_section() -> Section:
    """The cheat codes data as a guide section, so answers about codes cite it."""
    try:
        data = _data("cheat_codes.json")
    except ApiError:
        data = {"platforms": {}}
    lines = ["Single-player cheat codes. Only codes listed here exist as far as this guide knows."]
    any_codes = False
    for platform, codes in (data.get("platforms") or {}).items():
        for c in codes:
            any_codes = True
            mark = "Verified" if c.get("verified") else "Unverified"
            lines.append(
                f"- {platform}: {c.get('name', '')}: `{c.get('code', '')}` ({c.get('effect', '')}; "
                f"{mark}, checked {c.get('checked_on', 'n/a')})"
            )
    if not any_codes:
        lines.append(f"No codes confirmed yet (as of {data.get('updated_at', 'launch')}). "
                     "Codes get added after two independent checks.")
    return Section(id="cheat-codes", title="Cheat codes", markdown="\n".join(lines))


def combined() -> tuple[str, list[Section], str]:
    """Guide sections plus the cheat codes section; the version covers both."""
    guide = load_guide()
    sections = guide.sections + [cheat_codes_section()]
    prompt_text = "\n\n".join(
        f'<section id="{s.id}" title="{s.title}">\n{s.markdown}\n</section>' for s in sections
    )
    version = "g-" + hashlib.sha256(prompt_text.encode("utf-8")).hexdigest()[:12]
    return version, sections, prompt_text


# Internal: the full prompt text for the answer service.
@app.get("/internal/guide", dependencies=[Depends(require_internal)])
async def internal_guide() -> dict[str, Any]:
    guide = load_guide()
    version, sections, prompt_text = combined()
    return {
        "version": version,
        "title": guide.title,
        "sections": [{"id": s.id, "title": s.title} for s in sections],
        "prompt_text": prompt_text,
    }


@app.get("/guide/version")
async def guide_version() -> dict[str, Any]:
    version, sections, _ = combined()
    return {"version": version, "loaded_at": int(_state["loaded_at"]), "sections": len(sections)}


@app.get("/topics")
async def topics() -> dict[str, Any]:
    guide = load_guide()
    return {
        "guide_version": combined()[0],
        "topics": [
            {"id": s.id, "title": s.title, "summary": s.summary, "url": _topic_url(s.id)}
            for s in guide.sections
            if s.id != "sources"
        ],
    }


@app.get("/topics/{topic_id}")
async def topic(topic_id: str) -> dict[str, Any]:
    guide = load_guide()
    section = guide.section(topic_id)
    if not section:
        raise ApiError(404, "not_found", "No such topic")
    return {
        "id": section.id,
        "title": section.title,
        "summary": section.summary,
        "markdown": section.markdown,
        "is_rumor": section.id == "rumors-and-conflicts",
        "guide_version": combined()[0],
    }


@app.get("/cheat-codes")
async def cheat_codes() -> Any:
    return _data("cheat_codes.json")


@app.get("/starters")
async def starters() -> Any:
    return _data("starters.json")


@app.get("/whats-new")
async def whats_new() -> Any:
    return _data("whats_new.json")


@app.post("/admin/reload", dependencies=[Depends(require_admin)])
async def reload_guide() -> dict[str, Any]:
    """Re-reading guide.md after an edit; the answer service picks up the new version
    within GUIDE_REFRESH_SECONDS and old cached answers stop matching."""
    old = combined()[0] if _state["guide"] else None
    load_guide(force=True)
    version, sections, _ = combined()
    return {"previous_version": old, "version": version, "sections": len(sections)}
