"""Static website layer (landing page, API tester, custom docs).

Templates are plain HTML files with a tiny placeholder syntax rendered at
startup — no template-engine dependency. Dynamic values that depend on the
deployment host (e.g. the API base URL) are filled in the browser from
``window.location`` so no production domain is ever hardcoded.
"""

from __future__ import annotations

import html
from functools import lru_cache
from pathlib import Path

_WEB_DIR = Path(__file__).resolve().parent
TEMPLATE_DIR = _WEB_DIR / "templates"
STATIC_DIR = _WEB_DIR / "static"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


@lru_cache(maxsize=8)
def _base_template() -> str:
    return _read(TEMPLATE_DIR / "base.html")


@lru_cache(maxsize=8)
def _content(name: str) -> str:
    return _read(TEMPLATE_DIR / f"{name}.html")


def render_page(name: str, title: str, active: str) -> str:
    """Render a page from base.html + <name>.html content partial."""
    page = _base_template().replace("{{ title }}", html.escape(title)).replace("{{ content }}", _content(name))
    for section in ("home", "tester", "docs", "openapi", "health"):
        marker = "{{ active_%s }}" % section
        page = page.replace(marker, ' class="active"' if section == active else "")
    return page
