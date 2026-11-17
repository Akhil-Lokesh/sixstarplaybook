"""Converting a Claude Docs XML export of the guide into guide/guide.md.

Usage: python tools/docs_xml_to_markdown.py guide.xml guide/guide.md

Every level-2 heading becomes a section with a stable id, written as
`## Title {#section-id}` so the content service can cite it.
"""
import re
import sys
import xml.etree.ElementTree as ET


def slugify(text: str) -> str:
    text = text.lower().replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def render_inline(el) -> str:
    out = []
    for child in el:
        if child.tag == "text":
            out.append(render_text(child))
        elif child.tag == "date":
            out.append(child.get("value", ""))
        elif child.tag == "mention":
            out.append(child.get("name", ""))
    return "".join(out).strip()


def render_text(el) -> str:
    parts = [el.text or ""]
    for child in el:
        inner = render_text(child)
        if child.tag == "bold":
            parts.append(f"**{inner}**")
        elif child.tag == "link":
            parts.append(f"[{inner}]({child.get('href', '')})")
        else:
            parts.append(inner)
        parts.append(child.tail or "")
    return "".join(parts)


def render_table(table) -> list[str]:
    rows = []
    for row in table.findall("row"):
        cells = []
        for cell in row.findall("cell"):
            paras = [render_inline(p) for p in cell.findall("paragraph")]
            cells.append(" ".join(p for p in paras if p).replace("|", "\\|"))
        rows.append(cells)
    if not rows:
        return []
    lines = ["| " + " | ".join(rows[0]) + " |", "| " + " | ".join("---" for _ in rows[0]) + " |"]
    lines += ["| " + " | ".join(r) + " |" for r in rows[1:]]
    return lines


def render_list(lst, depth=0) -> list[str]:
    ordered = lst.get("kind") in ("ordered", "number", "numbered")
    lines = []
    for i, item in enumerate(lst.findall("listItem"), 1):
        marker = f"{i}." if ordered else "-"
        first = True
        for child in item:
            if child.tag == "paragraph":
                prefix = "  " * depth + (marker + " " if first else "  ")
                lines.append(prefix + render_inline(child))
                first = False
            elif child.tag == "list":
                lines += render_list(child, depth + 1)
    return lines


def convert(xml_text: str) -> str:
    root = ET.fromstring(xml_text)
    lines: list[str] = []
    seen: set[str] = set()
    for block in root:
        if block.tag == "paragraph":
            text = render_inline(block)
            level = block.get("heading")
            if level:
                n = int(level)
                if n == 2:
                    sid = slugify(text)
                    while sid in seen:
                        sid += "-2"
                    seen.add(sid)
                    lines += ["", f"## {text} {{#{sid}}}", ""]
                else:
                    lines += ["", "#" * n + " " + text, ""]
            elif text:
                lines += [text, ""]
        elif block.tag == "table":
            lines += render_table(block) + [""]
        elif block.tag == "list":
            lines += render_list(block) + [""]
    md = "\n".join(lines)
    md = re.sub(r"\n{3,}", "\n\n", md).strip() + "\n"
    return md


if __name__ == "__main__":
    src, dst = sys.argv[1], sys.argv[2]
    with open(src, encoding="utf-8") as f:
        md = convert(f.read())
    with open(dst, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"wrote {dst}: {len(md)} chars")
