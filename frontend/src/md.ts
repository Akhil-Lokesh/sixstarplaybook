// A small, safe Markdown renderer for answers and guide sections.
// Everything is HTML-escaped first, so raw HTML in the source is shown as text, never run.

export function esc(text: string): string {
  return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

interface Options { links?: boolean }

export function inline(raw: string, opts: Options = {}): string {
  let s = esc(raw);
  s = s.replace(/`([^`]+)`/g, "<code>$1</code>");
  s = s.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (_m, text: string, href: string) => {
    if (opts.links === false) return text;
    if (href.startsWith("/") && !href.startsWith("//")) return `<a href="${href}">${text}</a>`;
    if (/^https?:\/\//i.test(href)) return `<a href="${href}" target="_blank" rel="noopener noreferrer">${text}</a>`;
    return text;
  });
  s = s.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  s = s.replace(/(^|[\s(])\*([^*\s][^*]*)\*(?=[\s).,;:!?]|$)/g, "$1<em>$2</em>");
  return s;
}

function cells(line: string): string[] {
  const body = line.trim().replace(/^\|/, "").replace(/\|$/, "");
  return body.split(/(?<!\\)\|/).map((c) => c.trim().replace(/\\\|/g, "|"));
}

const LIST_ITEM = /^(\s*)(-|\*|\d+\.)\s+(.*)$/;

export function md(source: string, opts: Options = {}): string {
  const lines = source.replace(/\r\n/g, "\n").split("\n");
  const out: string[] = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) { i++; continue; }

    const heading = /^(#{1,6})\s+(.*)$/.exec(line);
    if (heading) {
      const level = Math.min(Math.max(heading[1].length, 3), 4); // sections sit under the page h1/h2
      out.push(`<h${level}>${inline(heading[2], opts)}</h${level}>`);
      i++;
      continue;
    }

    if (line.trim().startsWith("|") && i + 1 < lines.length && /^\s*\|?[\s:|-]+\|?\s*$/.test(lines[i + 1]) && lines[i + 1].includes("-")) {
      const head = cells(line);
      i += 2;
      const rows: string[][] = [];
      while (i < lines.length && lines[i].trim().startsWith("|")) rows.push(cells(lines[i++]));
      out.push(
        `<div class="table-wrap" tabindex="0" role="region" aria-label="Table"><table><thead><tr>` +
        head.map((c) => `<th scope="col">${inline(c, opts)}</th>`).join("") +
        `</tr></thead><tbody>` +
        rows.map((r) => `<tr>${r.map((c, n) => `<td data-label="${esc(head[n] ?? "")}">${inline(c, opts)}</td>`).join("")}</tr>`).join("") +
        `</tbody></table></div>`,
      );
      continue;
    }

    if (LIST_ITEM.test(line)) {
      // Nested lists by indent: each deeper indent opens a list inside the previous item.
      const stack: { indent: number; tag: string }[] = [];
      let html = "";
      while (i < lines.length && LIST_ITEM.test(lines[i])) {
        const m = LIST_ITEM.exec(lines[i])!;
        const indent = m[1].length;
        const tag = /\d/.test(m[2]) ? "ol" : "ul";
        while (stack.length && indent < stack[stack.length - 1].indent) html += `</li></${stack.pop()!.tag}>`;
        if (!stack.length || indent > stack[stack.length - 1].indent) {
          html += `<${tag}>`;
          stack.push({ indent, tag });
        } else {
          html += "</li>";
        }
        html += `<li>${inline(m[3], opts)}`;
        i++;
      }
      while (stack.length) html += `</li></${stack.pop()!.tag}>`;
      out.push(html);
      continue;
    }

    const para: string[] = [];
    while (i < lines.length && lines[i].trim() && !/^#{1,6}\s/.test(lines[i]) && !LIST_ITEM.test(lines[i]) && !lines[i].trim().startsWith("|")) {
      para.push(lines[i++].trim());
    }
    if (para.length) out.push(`<p>${inline(para.join(" "), opts)}</p>`);
    else i++; // a stray table-looking line with no separator: skip rather than loop
  }
  return out.join("\n");
}
