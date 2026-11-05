"""Export project reading material to sibling HTML; never traverse private/vendor data."""
from __future__ import annotations

import argparse
import hashlib
import html
import os
from pathlib import Path
import re
import sys
import time
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PATHS = (
    "README.md",
    "ToDo Stuff",
    "lichess-bot-master/README.md",
    "lichess-bot-master/Mr Bits Docs",
    "lichess-bot-master/engines/Kernels",
    "lichess-bot-master/engines/Neural Networks",
    "lichess-bot-master/database/dashboard/README.md",
    "tools/README.md",
)
SKIP_DIRS = {
    "claude docs", "calude docs", "chess dataset", "chess datasetet",
    "data", "raw", "runs", "diagnostics", "logs", "history", "input",
    "node_modules", "venv", "__pycache__", "stockfish", "sqlite",
}
SKIP_FILES = {f"{name}.md" for name in (
    "agents", "handoff", "claude", "gemini", "skill", "memory", "copilot"
)}
VERSION = "1"
BASE_CSS = """
body{font-family:Segoe UI,Arial,sans-serif;font-size:15px;line-height:1.65;
  color:#243247;background:white;max-width:1100px;margin:2rem auto;padding:0 26px;
  overflow-wrap:break-word}
h1,h2,h3,h4{line-height:1.3}h1,h2{color:#2354a5}
a{color:#2563eb}table{border-collapse:collapse;max-width:100%;margin:1em 0}
th,td{border:1px solid #cbd5e1;padding:.45em .65em;text-align:left;vertical-align:top}
th{background:#edf3fc}blockquote{border-left:4px solid #60a5fa;margin:1em 0;
  padding:.2em 1em;background:#eff6ff}pre{padding:1em;overflow:auto;background:#f3f5f8;
  border-radius:6px;line-height:1.45}code{font-family:Consolas,monospace;font-size:.9em}
img{max-width:100%}pre code{font-size:inherit}.mermaid{background:transparent}
@media print{body{max-width:none;margin:0;font-size:10.5pt}h1,h2,h3{break-after:avoid}
  pre,blockquote{break-inside:avoid}a{color:inherit}}
"""


def allowed(path: Path) -> bool:
    try:
        rel = path.resolve().relative_to(ROOT)
    except ValueError:
        return False
    return (
        path.suffix.lower() == ".md"
        and path.name.lower() not in SKIP_FILES
        and not any(part.startswith(".") or part.lower() in SKIP_DIRS for part in rel.parts[:-1])
    )


def documents(paths: list[str]) -> list[Path]:
    found = set()
    for name in paths or DEFAULT_PATHS:
        target = Path(name)
        if not target.is_absolute():
            target = ROOT / target
        target = target.resolve()
        if not target.is_relative_to(ROOT):
            raise ValueError(f"Document path is outside this project: {name}")
        if target.is_file():
            if allowed(target):
                found.add(target)
            elif paths:
                raise ValueError(f"Excluded from reader exports: {name}")
        elif target.is_dir():
            for folder, dirs, files in os.walk(target, followlinks=False):
                dirs[:] = [d for d in dirs if not d.startswith(".")
                           and d.lower() not in SKIP_DIRS
                           and not (Path(folder) / d).is_symlink()]
                for filename in files:
                    candidate = Path(folder) / filename
                    if allowed(candidate):
                        found.add(candidate)
        elif paths:
            raise FileNotFoundError(f"Document path does not exist: {name}")
    return sorted(found, key=lambda path: str(path).lower())


def fresh(source: Path) -> bool:
    output = source.with_suffix(".html")
    if not output.is_file():
        return False
    # Our exports have content fingerprints. Native extension exports have no
    # fingerprint; their modification time is the available freshness signal.
    head = output.read_text(encoding="utf-8-sig")[:1500]
    marker = re.search(r'<meta name="mrbits-source" content="([^"]+)"', head)
    if marker:
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        return marker.group(1) == f"{VERSION}:{digest}"
    return output.stat().st_mtime_ns >= source.stat().st_mtime_ns


def render(source: Path) -> str:
    try:
        from markdown_it import MarkdownIt
        from pygments import highlight
        from pygments.formatters import HtmlFormatter
        from pygments.lexers import get_lexer_by_name
        from pygments.util import ClassNotFound
    except ImportError as error:
        raise RuntimeError("Install documentation dependencies with: "
                           "python -m pip install -r tools/docs-requirements.in") from error

    formatter = HtmlFormatter(nowrap=True)

    def highlighted(code: str, language: str, _attributes: str = "") -> str:
        try:
            return highlight(code, get_lexer_by_name(language), formatter) if language else ""
        except ClassNotFound:
            return ""

    md = MarkdownIt("commonmark", {"html": True, "highlight": highlighted})
    md.enable(["table", "strikethrough"])
    default_fence = md.renderer.rules["fence"]
    mermaid = False

    def fence(tokens, index, options, env):
        nonlocal mermaid
        token = tokens[index]
        if token.info.strip().lower() == "mermaid":
            mermaid = True
            return '<pre class="mermaid">' + html.escape(token.content) + '</pre>\n'
        return default_fence(tokens, index, options, env)

    md.renderer.rules["fence"] = fence
    original = source.read_text(encoding="utf-8-sig")
    tokens = md.parse(original)
    seen_ids: dict[str, int] = {}
    for index, token in enumerate(tokens):
        if token.type == "heading_open" and index + 1 < len(tokens):
            text = tokens[index + 1].content
            slug = re.sub(r"[^\w\- ]", "", text.lower()).replace(" ", "-")
            duplicate = seen_ids.get(slug, 0)
            seen_ids[slug] = duplicate + 1
            token.attrSet("id", slug + (f"-{duplicate}" if duplicate else ""))
        if token.children:
            for child in token.children:
                if child.type != "link_open":
                    continue
                href = child.attrGet("href") or ""
                parsed = urlsplit(href)
                if parsed.scheme or parsed.netloc or not parsed.path.lower().endswith(".md"):
                    continue
                destination = source.parent / unquote(parsed.path)
                if allowed(destination) and destination.is_file():
                    child.attrSet("href", parsed._replace(path=parsed.path[:-3] + ".html").geturl())
    content = md.renderer.render(tokens, md.options, {})
    scripts = ""
    if mermaid:
        scripts = ('<script src="https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js"></script>\n'
                   '<script>mermaid.initialize({startOnLoad:true,securityLevel:"strict"});</script>\n')
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    return ('<!DOCTYPE html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
            f'<meta name="mrbits-source" content="{VERSION}:{digest}">\n'
            f'<title>{html.escape(source.name)}</title>\n'
            f'<style>\n{BASE_CSS}\n{formatter.get_style_defs("pre")}\n</style>\n'
            f'</head>\n<body>\n{content}{scripts}</body>\n</html>\n')


def update(paths: list[str], check: bool, force: bool) -> int:
    sources = documents(paths)
    stale = [source for source in sources if force or not fresh(source)]
    for source in stale:
        relative = source.relative_to(ROOT)
        if check:
            print(f"STALE {relative}")
            continue
        output = source.with_suffix(".html")
        temporary = output.with_suffix(".html.tmp")
        try:
            temporary.write_text(render(source), encoding="utf-8")
            os.replace(temporary, output)
        finally:
            temporary.unlink(missing_ok=True)
        print(f"HTML  {relative}")
    print(f"{len(sources)} reader documents; {len(stale)} " + ("need export." if check else "exported."))
    return 1 if check and stale else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", help="Markdown files/directories, relative to the project root")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="Report missing/stale HTML without writing")
    mode.add_argument("--watch", action="store_true", help="Keep checking for changed Markdown every two seconds")
    parser.add_argument("--force", action="store_true", help="Regenerate all selected HTML")
    args = parser.parse_args()
    try:
        result = update(args.paths, args.check, args.force)
        if args.watch:
            print("Watching project reader documents. Press Ctrl+C to stop.")
            while True:
                time.sleep(2)
                sources = documents(args.paths)
                if any(not fresh(source) for source in sources):
                    update(args.paths, False, False)
        return result
    except KeyboardInterrupt:
        return 0
    except (ValueError, OSError, RuntimeError) as error:
        print(f"Documentation export failed: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
