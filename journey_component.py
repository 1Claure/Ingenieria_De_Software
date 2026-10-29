"""Self-contained browser journey; predictions and Streamlit widgets stay in Python.

The checked-in JavaScript bundle is served by Streamlit itself. No CDN, Node
process or external rendering service is required to run the dashboard.
"""

import base64
from functools import lru_cache
from pathlib import Path

import streamlit as st


_ROOT = Path(__file__).resolve().parent
_FRONTEND = _ROOT / "frontend" / "journey"
_FILES = ("template.html", "style.css", "journey.bundle.js")


@lru_cache(maxsize=2)
def _register(version: tuple):
    # The file fingerprint makes a browser reload pick up rebuilt assets.
    html, css, js = ((_FRONTEND / name).read_text(encoding="utf-8") for name in _FILES)
    return st.components.v2.component(
        "agua_fractura_journey", html=html, css=css, js=js, isolate_styles=True
    )


@lru_cache(maxsize=2)
def _hero_data(path: str, modified: int) -> str:
    encoded = base64.b64encode(Path(path).read_bytes()).decode("ascii")
    return f"data:image/webp;base64,{encoded}"


def render_journey(hero: Path) -> None:
    """Mount Inicio without an iframe or Python updates on scroll."""
    version = tuple((_FRONTEND / name).stat().st_mtime_ns for name in _FILES)
    component = _register(version)
    world_path = _ROOT / "static" / "journey" / "world" / "manifest.json"
    world_url = "app/static/journey/world/manifest.json"
    if world_path.is_file():
        world_url += f"?v={world_path.stat().st_mtime_ns}"
    # A single photograph is only the low-motion/mobile/WebGL fallback.
    # The desktop journey is one GLB world, never a sequence of images.
    poster_url = "app/static/journey/poster.webp"
    surface_path = _ROOT / "static" / "journey" / "photography" / "vaca-muerta.jpg"
    surface_url = "app/static/journey/photography/vaca-muerta.jpg"
    if surface_path.is_file():
        surface_url += f"?v={surface_path.stat().st_mtime_ns}"
        poster_url = surface_url
    component(
        key="agua_inicio_journey",
        data={
            "hero_image": _hero_data(str(hero), hero.stat().st_mtime_ns),
            "world_manifest": world_url,
            "render_poster": poster_url,
        },
        height="content",
        width="stretch",
    )
