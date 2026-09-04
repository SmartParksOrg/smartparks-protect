#!/usr/bin/env python3
"""Documentation checks beyond `mkdocs build --strict` (architecture 28.8, decision D94's docs
half): internal links and anchors in the built site, Mermaid fences that name a known diagram
type, and the MCP tool reference in `docs/mcp/index.md` naming every tool the server offers.

    uv run scripts/docs_check.py            # after `mkdocs build --strict`
"""

from __future__ import annotations

import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
DOCS = ROOT / "docs"
MERMAID_TYPES = (
    "graph",
    "flowchart",
    "sequenceDiagram",
    "classDiagram",
    "stateDiagram",
    "stateDiagram-v2",
    "erDiagram",
    "gantt",
    "pie",
    "journey",
    "gitGraph",
    "mindmap",
    "timeline",
    "quadrantChart",
    "xychart-beta",
)


class Page(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []
        self.ids: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "a" and attributes.get("href"):
            self.links.append(str(attributes["href"]))
        if attributes.get("id"):
            self.ids.add(str(attributes["id"]))
        if tag == "a" and attributes.get("name"):
            self.ids.add(str(attributes["name"]))


def check_links() -> list[str]:
    if not SITE.is_dir():
        return ["site/ is missing: run `uv run mkdocs build --strict` first"]
    pages: dict[Path, Page] = {}
    for html in SITE.rglob("*.html"):
        page = Page()
        page.feed(html.read_text(encoding="utf-8"))
        pages[html] = page
    problems: list[str] = []
    for html, page in pages.items():
        for href in page.links:
            parts = urlsplit(href)
            if parts.scheme or href.startswith(("mailto:", "tel:", "javascript:")):
                continue
            if not parts.path:
                target_path = html
            elif parts.path.startswith("/"):
                target_path = (SITE / unquote(parts.path).lstrip("/")).resolve()
            else:
                target_path = (html.parent / unquote(parts.path)).resolve()
            if parts.path:
                if target_path.is_dir():
                    target_path = target_path / "index.html"
                if not target_path.exists():
                    problems.append(f"{html.relative_to(SITE)}: broken link {href}")
                    continue
            if parts.fragment:
                target = pages.get(target_path)
                if target is None:
                    if target_path.suffix == ".html":
                        problems.append(f"{html.relative_to(SITE)}: {href} points outside the site")
                    continue
                if unquote(parts.fragment) not in target.ids:
                    problems.append(f"{html.relative_to(SITE)}: missing anchor {href}")
    return problems


def check_mermaid() -> list[str]:
    problems: list[str] = []
    fence = re.compile(r"```mermaid\s*\n(.*?)```", re.S)
    for md in DOCS.rglob("*.md"):
        for block in fence.findall(md.read_text(encoding="utf-8")):
            first = next((line.strip() for line in block.splitlines() if line.strip()), "")
            head = first.split()[0] if first else ""
            if head.rstrip(":") not in MERMAID_TYPES and not first.startswith("%%"):
                problems.append(f"{md.relative_to(ROOT)}: mermaid fence starts with {first!r}")
    return problems


def check_mcp_reference() -> list[str]:
    """Every tool the MCP server registers appears in the tool tables of docs/mcp/index.md."""
    try:
        from protect_mcp.api import ProtectApi  # type: ignore[import-not-found]
        from protect_mcp.server import build_server  # type: ignore[import-not-found]
    except Exception as exc:
        return [f"could not import the MCP server to compare its tools: {exc}"]
    import asyncio

    tools = asyncio.run(build_server(ProtectApi()).list_tools())
    names = {tool.name for tool in tools}
    text = (DOCS / "mcp" / "index.md").read_text(encoding="utf-8")
    documented = set(re.findall(r"^\| `([a-z_]+)` \|", text, re.M))
    missing = sorted(names - documented)
    stale = sorted(documented - names)
    problems = []
    if missing:
        problems.append(f"docs/mcp/index.md does not list the MCP tools: {', '.join(missing)}")
    if stale:
        problems.append(
            f"docs/mcp/index.md lists tools the server no longer has: {', '.join(stale)}"
        )
    return problems


def main() -> int:
    problems = check_links() + check_mermaid() + check_mcp_reference()
    for problem in problems:
        print(problem)
    print(f"docs check: {len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
