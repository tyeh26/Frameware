"""Layout helpers: Keep widget source paths, grid row counts, anchor-based placement."""

from __future__ import annotations

import re
from typing import Any


def resolve_widget_sources(layout: dict) -> dict:
    """Resolve keep_title/keep_label references in widgets to their output file paths."""
    widgets = []
    for w in layout.get("widgets", []):
        w = dict(w)
        keep_title = w.get("keep_title")
        keep_label = w.get("keep_label")
        if (keep_title or keep_label) and not w.get("source"):
            slug_key = keep_title or keep_label
            slug = re.sub(r"[^a-z0-9]+", "_", slug_key.lower().strip()).strip("_") or "unnamed"
            w["source"] = f"data/keep/{slug}.json"
        widgets.append(w)
    return {**layout, "widgets": widgets}


def row_slots(layout: dict, canvas_h: int) -> int:
    """Number of grid row positions (for h=1) that fit vertically; matches renderer grid math.

    If ``layout.rows`` is set, that value is used (lets you align anchors with a known grid).
    Otherwise derived from ``cell_height``, ``margin``, and ``gutter`` like ``widget_rect_from_grid``.
    """
    explicit = layout.get("rows")
    if explicit is not None:
        return max(1, int(explicit))
    cell_h = int(layout.get("cell_height", 200))
    margin = int(layout.get("margin", 120))
    gutter = int(layout.get("gutter", 40))
    step = cell_h + gutter
    if step <= 0:
        return 1
    return max(1, (canvas_h - 2 * margin - cell_h) // step + 1)


def _norm_anchor(raw: str | None) -> str | None:
    if not raw:
        return None
    a = str(raw).strip().lower().replace(" ", "-")
    aliases = {
        "nw": "top-left",
        "tl": "top-left",
        "ne": "top-right",
        "tr": "top-right",
        "sw": "bottom-left",
        "bl": "bottom-left",
        "se": "bottom-right",
        "br": "bottom-right",
    }
    return aliases.get(a, a)


def apply_widget_anchors(
    widgets: list[dict[str, Any]],
    layout: dict,
    canvas_w: int,
    canvas_h: int,
) -> list[dict[str, Any]]:
    """Fill ``x`` / ``y`` from ``anchor`` + ``w`` / ``h`` when those grid keys are omitted.

    Uses the same column count and vertical slot count as ``widget_rect_from_grid``.
    Horizontal: ``left`` / ``right`` / ``center`` align within the row (``w`` columns wide).
    Vertical: ``top`` / ``bottom`` / ``middle`` using ``row_slots`` and ``h``.
    Corners: ``top-left``, ``top-right``, ``bottom-left``, ``bottom-right``.
    """
    cols = max(1, int(layout.get("columns", 12)))
    rows = row_slots(layout, canvas_h)
    out: list[dict[str, Any]] = []
    for w in widgets:
        w = dict(w)
        anchor = _norm_anchor(w.get("anchor"))
        has_xy = "x" in w and "y" in w
        if not anchor or has_xy:
            out.append(w)
            continue
        gw = int(w.get("w", cols))
        gh = int(w.get("h", 1))
        gw = min(gw, cols)
        gh = max(1, gh)

        x, y = 0, 0
        if anchor in ("top-left",):
            x, y = 0, 0
        elif anchor in ("top-right",):
            x, y = cols - gw, 0
        elif anchor in ("bottom-left",):
            x, y = 0, max(0, rows - gh)
        elif anchor in ("bottom-right",):
            x, y = cols - gw, max(0, rows - gh)
        elif anchor in ("top",):
            x, y = (cols - gw) // 2, 0
        elif anchor in ("bottom",):
            x, y = (cols - gw) // 2, max(0, rows - gh)
        elif anchor in ("left",):
            x, y = 0, max(0, (rows - gh) // 2)
        elif anchor in ("right",):
            x, y = cols - gw, max(0, (rows - gh) // 2)
        elif anchor in ("center", "middle"):
            x, y = (cols - gw) // 2, max(0, (rows - gh) // 2)
        else:
            out.append(w)
            continue

        w["x"] = max(0, x)
        w["y"] = max(0, y)
        if "w" not in w:
            w["w"] = gw
        if "h" not in w:
            w["h"] = gh
        out.append(w)
    return out
