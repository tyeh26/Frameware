import io
import json
import os

from PIL import Image, ImageDraw

from frame.utils import get_font, wrap_text
from frame.widgets.clock import CLOCK_SIZES, render_clock


def load_list_items(source: str, base_dir: str) -> list[str]:
    if not source:
        return []
    path = os.path.join(base_dir, source)
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r") as f:
            data = json.load(f)
    except Exception:
        return []
    if isinstance(data, dict) and "items" in data:
        data = data["items"]
    if isinstance(data, list):
        items = []
        for item in data:
            if isinstance(item, str):
                items.append(item)
            elif isinstance(item, dict) and "text" in item:
                items.append(item["text"])
        return items
    return []


def resolve_widget_height(widget: dict, default: int) -> int:
    """Return pixel height for a widget, resolving S/M/L size aliases for clocks."""
    if widget.get("type") == "clock":
        size = str(widget.get("size", "")).upper()
        if size in CLOCK_SIZES:
            return CLOCK_SIZES[size]
    explicit = widget.get("height")
    return int(explicit) if explicit is not None else default


def compute_grid_cells(
    layout: dict, count: int, width: int, height: int, widgets: list = None
) -> list[tuple[int, int, int, int]]:
    cols = max(1, int(layout.get("columns", 2)))
    margin = int(layout.get("margin", 120))
    gutter = int(layout.get("gutter", 40))

    cell_w = (width - (margin * 2) - (gutter * (cols - 1))) / cols
    max_widget_width = layout.get("max_widget_width")
    if max_widget_width:
        cell_w = min(cell_w, int(max_widget_width))
    panel_w = cols * cell_w + gutter * (cols - 1)
    x_start = width - margin - panel_w

    default_cell_h = int(layout.get("default_height", 500))

    col_y = [margin] * cols
    cells = []
    for i in range(count):
        c = i % cols
        widget = widgets[i] if widgets and i < len(widgets) else {}
        cell_h_actual = resolve_widget_height(widget, default_cell_h)

        x1 = int(x_start + c * (cell_w + gutter))
        y1 = int(col_y[c])
        x2 = int(x1 + cell_w)
        y2 = y1 + cell_h_actual

        cells.append((x1, y1, x2, y2))
        col_y[c] = y2 + gutter

    return cells


def render_widget(
    draw: ImageDraw.Draw,
    widget: dict,
    rect: tuple,
    base_dir: str,
    font_path: str = None,
):
    x1, y1, x2, y2 = rect
    pad = 24
    title_font = get_font(96, font_path)
    body_font = get_font(72, font_path)

    draw.rounded_rectangle([x1, y1, x2, y2], radius=24, fill=(20, 20, 20))

    title = widget.get("title", "").strip()
    if title:
        draw.text((x1 + pad, y1 + pad), title, fill="white", font=title_font)
        title_h = title_font.getbbox(title)[3] - title_font.getbbox(title)[1]
    else:
        title_h = 0

    body_top = y1 + pad + title_h + 16
    body_left = x1 + pad
    body_right = x2 - pad

    wtype = widget.get("type", "note")

    if wtype == "clock":
        render_clock(draw, widget, body_left, body_top, body_right, y2 - pad, font_path)
        return

    if wtype == "list":
        items = load_list_items(widget.get("source"), base_dir)
        if not items:
            items = ["(empty)"]
        y = body_top
        for item in items:
            lines = wrap_text(draw, f"• {item}", body_font, body_right - body_left)
            for line in lines:
                draw.text((body_left, y), line, fill="white", font=body_font)
                y += body_font.getbbox(line)[3] - body_font.getbbox(line)[1] + 8
            y += 6
        return

    # note / fallback: supports inline text or a source file
    text = widget.get("text", "")
    if not text and widget.get("source"):
        items = load_list_items(widget.get("source"), base_dir)
        text = "\n".join(items)
    lines = wrap_text(draw, text, body_font, body_right - body_left)
    y = body_top
    for line in lines:
        draw.text((body_left, y), line, fill="white", font=body_font)
        y += body_font.getbbox(line)[3] - body_font.getbbox(line)[1] + 8


def create_dashboard_frame(
    base_image_path: str,
    layout: dict,
    base_dir: str,
    preview_path: str,
) -> bytes:
    """Generates a 4K dashboard JPEG from a base image and layout config."""
    font_path = os.path.join(base_dir, "fonts", "Roboto-Bold.ttf")

    img = Image.open(base_image_path).convert("RGB")
    if img.size != (3840, 2160):
        img = img.resize((3840, 2160), Image.Resampling.LANCZOS)

    draw = ImageDraw.Draw(img)
    widgets = layout.get("widgets", [])
    cells = compute_grid_cells(layout, len(widgets), 3840, 2160, widgets)
    for widget, rect in zip(widgets, cells):
        render_widget(draw, widget, rect, base_dir, font_path)

    img.save(preview_path, quality=85)

    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()
