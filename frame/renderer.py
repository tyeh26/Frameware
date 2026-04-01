import io
import json
import math
import os
from datetime import datetime

from PIL import Image, ImageDraw, ImageFont


def get_font(size: int, font_path: str = None) -> ImageFont.FreeTypeFont:
    candidates = []
    if font_path and os.path.exists(font_path):
        candidates.append(font_path)
    candidates += [
        "/Library/Fonts/Arial Bold.ttf",
        "/Library/Fonts/Arial.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
    ]
    for path in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                pass
    return ImageFont.load_default()


def wrap_text(draw: ImageDraw.Draw, text: str, font, max_width: int) -> list[str]:
    words = text.split()
    if not words:
        return []
    lines = []
    current = words[0]
    for word in words[1:]:
        test = f"{current} {word}"
        if draw.textlength(test, font=font) <= max_width:
            current = test
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


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


def _draw_flip_cell(
    draw: ImageDraw.Draw,
    x: int,
    y: int,
    w: int,
    h: int,
    char: str,
    font,
) -> None:
    """Single split-flap style card (retro flip clock)."""
    r = max(6, min(14, h // 12))
    bg = (38, 38, 42)
    edge = (72, 72, 78)
    hinge = (12, 12, 14)
    top_shade = (48, 48, 52)
    digit = (245, 240, 232)

    draw.rounded_rectangle([x, y, x + w, y + h], radius=r, fill=bg, outline=edge, width=2)
    mid = y + h // 2
    draw.rectangle([x + 3, y + 3, x + w - 3, mid], fill=top_shade)
    draw.line([(x + r, mid), (x + w - r, mid)], fill=hinge, width=3)

    bbox = draw.textbbox((0, 0), char, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    tx = x + (w - tw) // 2 - bbox[0]
    ty = y + (h - th) // 2 - bbox[1]
    draw.text((tx, ty), char, fill=digit, font=font)


def _draw_retro_flip_clock(
    draw: ImageDraw.Draw,
    body_left: int,
    body_top: int,
    body_right: int,
    body_bottom: int,
    time_str: str,
    font_path: str = None,
) -> None:
    """Lay out time_str as retro flip segments; scales to fit the body rect."""
    gap = 16
    max_w = body_right - body_left
    max_h = body_bottom - body_top
    if max_w <= 0 or max_h <= 0 or not time_str:
        return

    chosen = None
    for font_size in range(220, 36, -4):
        font = get_font(font_size, font_path)
        dw = max(int(draw.textlength(str(d), font=font)) for d in "0123456789")
        cell_w = dw + 28
        colon_w = max(int(cell_w * 0.42), int(font_size * 0.3))
        cell_h = int(font_size * 1.38)

        total_w = 0
        first = True
        for c in time_str:
            if c == " ":
                total_w += (gap if not first else 0) + int(cell_w * 0.35)
                first = False
                continue
            if not first:
                total_w += gap
            first = False
            total_w += colon_w if c == ":" else cell_w

        if total_w <= max_w and cell_h <= max_h:
            chosen = (font, cell_w, colon_w, cell_h)
            break

    if chosen is None:
        font = get_font(36, font_path)
        dw = max(int(draw.textlength(str(d), font=font)) for d in "0123456789")
        cell_w = dw + 28
        colon_w = max(int(cell_w * 0.42), 12)
        cell_h = int(36 * 1.38)
        chosen = (font, cell_w, colon_w, cell_h)

    font, cell_w, colon_w, cell_h = chosen

    total_w = 0
    first = True
    for c in time_str:
        if c == " ":
            total_w += (gap if not first else 0) + int(cell_w * 0.35)
            first = False
            continue
        if not first:
            total_w += gap
        first = False
        total_w += colon_w if c == ":" else cell_w

    x = body_left + max(0, (max_w - total_w) // 2)
    first = True
    for c in time_str:
        if c == " ":
            x += (gap if not first else 0) + int(cell_w * 0.35)
            first = False
            continue
        if not first:
            x += gap
        first = False
        w = colon_w if c == ":" else cell_w
        _draw_flip_cell(draw, x, body_top, w, cell_h, c, font)
        x += w


def compute_grid_cells(
    layout: dict, count: int, width: int, height: int
) -> list[tuple[int, int, int, int]]:
    cols = max(1, int(layout.get("columns", 2)))
    margin = int(layout.get("margin", 120))
    gutter = int(layout.get("gutter", 40))
    if layout.get("rows") == "auto" or not layout.get("rows"):
        rows = max(1, math.ceil(count / cols))
    else:
        rows = max(1, int(layout.get("rows", 1)))
    cell_w = (width - (margin * 2) - (gutter * (cols - 1))) / cols
    max_widget_width = layout.get("max_widget_width")
    if max_widget_width:
        cell_w = min(cell_w, int(max_widget_width))
    panel_w = cols * cell_w + gutter * (cols - 1)
    x_start = width - margin - panel_w
    cell_h = (height - (margin * 2) - (gutter * (rows - 1))) / rows
    cells = []
    for i in range(count):
        r = i // cols
        c = i % cols
        x1 = int(x_start + c * (cell_w + gutter))
        y1 = int(margin + r * (cell_h + gutter))
        x2 = int(x1 + cell_w)
        y2 = int(y1 + cell_h)
        cells.append((x1, y1, x2, y2))
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
        now = datetime.now()
        time_fmt = widget.get("format", "%H:%M")
        date_fmt = widget.get("date_format", "%A, %b %d")
        show_date = widget.get("show_date", True)
        time_text = now.strftime(time_fmt)
        date_font = get_font(72, font_path)
        body_bottom = y2 - pad
        if show_date:
            body_bottom -= int(date_font.getbbox("Ag")[3] - date_font.getbbox("Ag")[1]) + 16
        _draw_retro_flip_clock(
            draw, body_left, body_top, body_right, body_bottom, time_text, font_path
        )
        if show_date:
            sample = now.strftime(date_fmt)
            dh = date_font.getbbox(sample)[3] - date_font.getbbox(sample)[1]
            flip_bottom = body_bottom
            date_y = flip_bottom + 16
            draw.text(
                (body_left, date_y),
                sample,
                fill=(220, 218, 212),
                font=date_font,
            )
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
    cells = compute_grid_cells(layout, len(widgets), 3840, 2160)
    for widget, rect in zip(widgets, cells):
        render_widget(draw, widget, rect, base_dir, font_path)

    img.save(preview_path, quality=85)

    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()
