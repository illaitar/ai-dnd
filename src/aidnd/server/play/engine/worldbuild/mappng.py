"""World-map raster pipeline: the city SVG is rendered ONCE at world build, recolored into a
few day-phase palettes (fills only — building borders/walls/ink stay untouched) and rasterized
to PNG. The client never receives the 5k-element SVG: it pans/zooms a single <image> and
resolves clicks through a raster ID-map (each clickable polygon painted a unique index color).

Key functions
-------------
phase_of(gt_min) -> str : Day phase bucket ("morning"|"day"|"evening"|"night") for game minutes.
build_map_rasters(wid, vis) -> dict : Write data/maps/w<wid>/{phase}.png + idmap.png;
    return {"png": {phase: url}, "idmap": url, "ids": [house ids by index]}.
"""

from __future__ import annotations

import os
import re

# raster scale: world-units → px. 4× keeps streets crisp at street-level zoom; the id-map only
# needs click precision, 2× is plenty and keeps the client canvas small.
_SCALE = 4
_ID_SCALE = 2

_MAPS_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "..", "..", "..", "data", "maps"
)

# phase → (brightness, tint rgb 0..1, tint amount, saturation of the ORIGINAL component).
# "Moonlight" model: a fill moves toward the phase color proportionally to its own luminance —
# hue never rotates, so the river stays a river at any hour. The sat factor greys the surviving
# original hue: at night warm roofs must sink into the blue, not glow against it.
# Strokes are NOT touched (ink/borders/walls constant in every palette).
PHASES = {
    "morning": (0.97, (1.00, 0.88, 0.78), 0.14, 0.95),  # рассветная розоватость
    "day": (1.00, (1.00, 1.00, 1.00), 0.00, 1.00),      # авторская палитра как есть
    "evening": (0.88, (1.00, 0.76, 0.50), 0.26, 0.90),  # янтарный предзакат
    "night": (0.55, (0.52, 0.64, 0.86), 0.62, 0.45),    # лунная синь, приглушённая
}


def phase_of(gt_min: int) -> str:
    h = (gt_min // 60) % 24
    if h < 5 or h >= 22:
        return "night"
    if h < 10:
        return "morning"
    if h < 17:
        return "day"
    return "evening"


def _tint_hex(hexcol: str, br: float, tint: tuple, amt: float, sat: float = 1.0) -> str:
    s = hexcol.lstrip("#")
    if len(s) == 3:
        s = "".join(c * 2 for c in s)
    try:
        r, g, b = (int(s[i : i + 2], 16) / 255.0 for i in (0, 2, 4))
    except ValueError:
        return hexcol
    r, g, b = r * br, g * br, b * br
    lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
    r, g, b = (lum + (v - lum) * sat for v in (r, g, b))  # grey the surviving hue
    out = [(v * (1 - amt) + lum * t * amt) for v, t in zip((r, g, b), tint)]
    return "#" + "".join(f"{max(0, min(255, round(v * 255))):02x}" for v in out)


_FILL_RE = re.compile(
    r'fill="(#[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3})?|rgb\(\s*\d+\s*,\s*\d+\s*,\s*\d+\s*\))"'
)


def _palette_inner(inner: str, phase: str) -> str:
    """Recolor FILLS only — stroke attributes (building borders, walls, ridges) untouched.
    Handles both hex and rgb(r,g,b) fills (house roofs come from shade() as rgb)."""
    br, tint, amt, sat = PHASES[phase]
    if amt == 0 and br == 1.0 and sat == 1.0:
        return inner

    def _sub(mt):
        col = mt.group(1)
        if col.startswith("rgb"):
            r, g, b = (int(x) for x in re.findall(r"\d+", col))
            col = f"#{r:02x}{g:02x}{b:02x}"
        return f'fill="{_tint_hex(col, br, tint, amt, sat)}"'

    return _FILL_RE.sub(_sub, inner)


def _idx_color(i: int) -> str:
    """Index (1-based) → unique flat color: R = low byte, G = high byte, B = 0."""
    return f"#{i & 255:02x}{(i >> 8) & 255:02x}00"


def _poly_d(p) -> str:
    return "M" + "L".join(f"{q[0]:.2f} {q[1]:.2f}" for q in p) + "Z"


def _idmap_svg(polys: list, w: int, h: int) -> str:
    """Hit-test raster: black = nothing, polygon i painted its index color. crispEdges keeps
    anti-aliasing off so a sampled pixel is (nearly) always an exact index color."""
    e = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" '
        'shape-rendering="crispEdges">',
        f'<rect width="{w}" height="{h}" fill="#000000"/>',
    ]
    for i, p in enumerate(polys):
        e.append(f'<path d="{_poly_d(p["poly"])}" fill="{_idx_color(i + 1)}"/>')
    e.append("</svg>")
    return "".join(e)


def build_map_rasters(wid: int, vis: dict, fresh: bool = False, ver: str = "0") -> dict:
    """Render phase PNGs + id-map for a world (idempotent by file presence).
    fresh=True wipes the world's raster dir first — a NEW world reuses the wid, and stale
    PNGs of the previous city must not survive the file-presence check."""
    import cairosvg

    w, h = vis["W"], vis["H"]
    out_dir = os.path.join(_MAPS_DIR, f"w{wid}")
    if fresh and os.path.isdir(out_dir):
        import shutil

        shutil.rmtree(out_dir, ignore_errors=True)
    os.makedirs(out_dir, exist_ok=True)
    urls = {}
    for phase in PHASES:
        path = os.path.join(out_dir, f"{phase}.png")
        if not os.path.exists(path):
            svg = (
                f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}">'
                + _palette_inner(vis["inner"], phase)
                + "</svg>"
            )
            cairosvg.svg2png(
                bytestring=svg.encode("utf-8"), write_to=path, output_width=w * _SCALE
            )
        urls[phase] = f"/api/play/mapimg/{phase}.png?v={ver}"  # ?v busts browser cache on new world
    idpath = os.path.join(out_dir, "idmap.png")
    if not os.path.exists(idpath):
        cairosvg.svg2png(
            bytestring=_idmap_svg(vis["polys"], w, h).encode("utf-8"),
            write_to=idpath,
            output_width=w * _ID_SCALE,
        )
    return {
        "png": urls,
        "idmap": f"/api/play/mapimg/idmap.png?v={ver}",
        "ids": [p["id"] for p in vis["polys"]],
    }


def map_file(wid: int, name: str) -> str | None:
    """Absolute path of a served map raster; None unless it's a known safe name."""
    if not re.fullmatch(r"(morning|day|evening|night|idmap)\.png", name):
        return None
    path = os.path.join(_MAPS_DIR, f"w{wid}", name)
    return path if os.path.exists(path) else None
