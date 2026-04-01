from datetime import datetime

from PIL import ImageDraw

from frame.utils import get_font


CLOCK_SIZES = {"S": 280, "M": 420, "L": 560}


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


def _draw_retro_flip_date(
    draw: ImageDraw.Draw,
    body_left: int,
    body_top: int,
    body_right: int,
    body_bottom: int,
    date_str: str,
    font_path: str = None,
) -> None:
    """Lay out date_str as retro flip segments; scales to fit the body rect."""
    gap = 8
    max_w = body_right - body_left
    max_h = body_bottom - body_top
    if max_w <= 0 or max_h <= 0 or not date_str:
        return

    def _total_w(font, font_size):
        w = 0
        first = True
        for c in date_str:
            if c == " ":
                w += (gap if not first else 0) + int(font_size * 0.4)
                first = False
                continue
            if not first:
                w += gap
            first = False
            w += int(draw.textlength(c, font=font)) + 20
        return w

    chosen = None
    for font_size in range(120, 20, -2):
        cell_h = int(font_size * 1.38)
        if cell_h > max_h:
            continue
        font = get_font(font_size, font_path)
        if _total_w(font, font_size) <= max_w:
            chosen = (font, font_size, cell_h)
            break

    if chosen is None:
        font_size = 20
        font = get_font(font_size, font_path)
        cell_h = int(font_size * 1.38)
        chosen = (font, font_size, cell_h)

    font, font_size, cell_h = chosen
    total_w = _total_w(font, font_size)
    cy = body_top + (max_h - cell_h) // 2

    x = body_left + max(0, (max_w - total_w) // 2)
    first = True
    for c in date_str:
        if c == " ":
            x += (gap if not first else 0) + int(font_size * 0.4)
            first = False
            continue
        if not first:
            x += gap
        first = False
        cw = int(draw.textlength(c, font=font)) + 20
        _draw_flip_cell(draw, x, cy, cw, cell_h, c, font)
        x += cw


def render_clock(
    draw: ImageDraw.Draw,
    widget: dict,
    body_left: int,
    body_top: int,
    body_right: int,
    body_bottom: int,
    font_path: str = None,
) -> None:
    """Render clock content into the given body rect (card background and title already drawn)."""
    now = datetime.now()
    time_fmt = widget.get("format", "%H:%M")
    date_fmt = widget.get("date_format", "%A, %b %d")
    show_date = widget.get("show_date", True)
    time_text = now.strftime(time_fmt)

    date_font = get_font(72, font_path)
    flip_bottom = body_bottom
    if show_date:
        flip_bottom -= int(date_font.getbbox("Ag")[3] - date_font.getbbox("Ag")[1]) + 16

    _draw_retro_flip_clock(draw, body_left, body_top, body_right, flip_bottom, time_text, font_path)

    if show_date:
        _draw_retro_flip_date(
            draw, body_left, flip_bottom + 16, body_right, body_bottom, now.strftime(date_fmt).upper(), font_path
        )
