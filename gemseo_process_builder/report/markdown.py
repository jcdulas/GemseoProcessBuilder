"""The little Markdown the Claude copilot writes, as HTML for the report.

Headings, bullet and numbered lists, tables, paragraphs, bold and inline
code; the rest is kept as text. Everything is escaped first: the text comes
from Claude, never raw HTML in the report.
"""

import html
import re

_BOLD = re.compile(r"\*\*(.+?)\*\*")
_CODE = re.compile(r"`([^`]+)`")
_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_BULLET = re.compile(r"^\s*[-*]\s+(.*)$")
_NUMBERED = re.compile(r"^\s*\d+[.)]\s+(.*)$")
_ROW = re.compile(r"^\s*\|(.*)\|\s*$")
_SEPARATOR = re.compile(r"^[\s|:-]+$")


def _inline(text: str) -> str:
    escaped = html.escape(text)
    escaped = _CODE.sub(r"<code>\1</code>", escaped)
    return _BOLD.sub(r"<strong>\1</strong>", escaped)


def markdown_to_html(text: str, top_level: int = 4) -> str:
    """HTML for a Markdown text.

    Args:
        text: The Markdown.
        top_level: The HTML level of its first-level headings, so that they
            sit under the headings of the report.
    """
    parts: list[str] = []
    paragraph: list[str] = []
    items: list[str] = []
    list_tag = ""
    rows: list[list[str]] = []

    def close() -> None:
        nonlocal list_tag
        if paragraph:
            parts.append(f"<p>{_inline(' '.join(paragraph))}</p>")
            paragraph.clear()
        if items:
            content = "".join(f"<li>{_inline(item)}</li>" for item in items)
            parts.append(f"<{list_tag}>{content}</{list_tag}>")
            items.clear()
            list_tag = ""
        if rows:
            head, *body = rows
            cells = "".join(f"<th>{_inline(cell)}</th>" for cell in head)
            lines = "".join(
                "<tr>" + "".join(f"<td>{_inline(cell)}</td>" for cell in row) + "</tr>"
                for row in body
            )
            parts.append(
                f"<table><thead><tr>{cells}</tr></thead><tbody>{lines}</tbody></table>"
            )
            rows.clear()

    for line in text.splitlines():
        row = _ROW.match(line)
        if row:
            if not rows:
                close()
            if not _SEPARATOR.match(row.group(1)):
                rows.append([cell.strip() for cell in row.group(1).split("|")])
            continue
        if rows:
            close()
        heading = _HEADING.match(line)
        bullet = _BULLET.match(line)
        numbered = _NUMBERED.match(line)
        if heading:
            close()
            level = min(top_level + len(heading.group(1)) - 1, 6)
            parts.append(f"<h{level}>{_inline(heading.group(2))}</h{level}>")
        elif bullet or numbered:
            tag = "ul" if bullet else "ol"
            if paragraph or (items and list_tag != tag):
                close()
            list_tag = tag
            items.append((bullet or numbered).group(1))  # type: ignore[union-attr]
        elif not line.strip():
            close()
        elif items:
            items[-1] += " " + line.strip()  # The rest of a list item.
        else:
            paragraph.append(line.strip())
    close()
    return "".join(parts)
