"""Parsing guide/guide.md into sections with stable ids and a version.

A section starts at a level-2 heading written as `## Title {#section-id}`.
The version is a hash of the text sent to the model, so any edit to the guide
produces a new version and the answer cache starts fresh.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

_H2 = re.compile(r"^## (?P<title>.+?)\s*\{#(?P<id>[a-z0-9-]+)\}\s*$")
_H2_PLAIN = re.compile(r"^## (?P<title>.+?)\s*$")


@dataclass
class Section:
    id: str
    title: str
    markdown: str

    @property
    def summary(self) -> str:
        """The section's first prose paragraph, for topic tiles."""
        for block in self.markdown.split("\n\n"):
            block = block.strip()
            if block and not block.startswith(("|", "#", "-", "1.")):
                return block
        return ""


@dataclass
class Guide:
    title: str
    sections: list[Section] = field(default_factory=list)
    version: str = ""
    prompt_text: str = ""

    def section(self, section_id: str) -> Section | None:
        return next((s for s in self.sections if s.id == section_id), None)


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def parse_guide(markdown: str, exclude: list[str] | None = None) -> Guide:
    exclude_set = set(exclude or [])
    title = "Guide"
    sections: list[Section] = []
    current: tuple[str, str] | None = None
    body: list[str] = []

    def flush() -> None:
        if current and current[0] not in exclude_set:
            sections.append(Section(id=current[0], title=current[1], markdown="\n".join(body).strip()))

    for line in markdown.splitlines():
        if line.startswith("# ") and title == "Guide":
            title = line[2:].strip()
            continue
        m = _H2.match(line) or _H2_PLAIN.match(line)
        if m and line.startswith("## "):
            flush()
            sid = m.groupdict().get("id") or _slug(m.group("title"))
            current = (sid, m.group("title").strip())
            body = []
        elif current:
            body.append(line)
    flush()

    prompt_text = "\n\n".join(
        f'<section id="{s.id}" title="{s.title}">\n{s.markdown}\n</section>' for s in sections
    )
    version = "g-" + hashlib.sha256(prompt_text.encode("utf-8")).hexdigest()[:12]
    return Guide(title=title, sections=sections, version=version, prompt_text=prompt_text)
