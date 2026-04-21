"""Weather bug: current conditions + today's high/low from OpenWeather One Call 3.0."""

from __future__ import annotations

import math

from PIL import ImageDraw

from frame.openweather import fetch_onecall_payload, get_openweather_config
from frame.utils import get_font, wrap_text


def _round_temp(v) -> str:
    if v is None:
        return "—"
    try:
        return str(int(round(float(v))))
    except (TypeError, ValueError):
        return "—"


def _condition_bucket(weather_id: int | None, main: str) -> str:
    """Visual bucket for icon drawing."""
    if weather_id is None:
        m = (main or "").lower()
        if m == "clear":
            return "clear"
        if m in ("clouds",):
            return "cloudy"
        if m in ("rain", "drizzle"):
            return "rain"
        if m == "snow":
            return "snow"
        if m == "thunderstorm":
            return "storm"
        if m in ("mist", "fog", "haze"):
            return "fog"
        return "cloudy"
    wid = int(weather_id)
    if wid == 800:
        return "clear"
    if wid == 801:
        return "partly"
    if 802 <= wid <= 804:
        return "cloudy"
    if wid // 100 == 2:
        return "storm"
    if wid // 100 == 3:
        return "drizzle"
    if wid // 100 == 5:
        return "rain"
    if wid // 100 == 6:
        return "snow"
    if 700 <= wid <= 781:
        return "fog"
    return "cloudy"


def _draw_sun(draw: ImageDraw.Draw, cx: int, cy: int, r: int, fill) -> None:
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=fill)
    for i in range(8):
        a = i * math.pi / 4
        x1 = cx + int((r + 4) * math.cos(a))
        y1 = cy + int((r + 4) * math.sin(a))
        x2 = cx + int((r + r // 2) * math.cos(a))
        y2 = cy + int((r + r // 2) * math.sin(a))
        draw.line([(x1, y1), (x2, y2)], fill=fill, width=max(2, r // 10))


def _draw_cloud(draw: ImageDraw.Draw, cx: int, cy: int, w: int, h: int, fill) -> None:
    r = h // 2
    draw.ellipse([cx - w // 3 - r // 2, cy - r, cx - w // 3 + r // 2, cy + r], fill=fill)
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=fill)
    draw.ellipse([cx + w // 3 - r // 2, cy - r, cx + w // 3 + r // 2, cy + r], fill=fill)


def _draw_rain(draw: ImageDraw.Draw, x0: int, y0: int, w: int, h: int, fill) -> None:
    for i, ox in enumerate((w // 6, w // 2, 5 * w // 6)):
        x = x0 + ox
        y = y0 + (i % 2) * 4
        draw.line([(x, y), (x - 6, y + h // 2)], fill=fill, width=max(2, w // 20))


def _draw_snow_flakes(draw: ImageDraw.Draw, x0: int, y0: int, w: int, h: int, fill) -> None:
    for ox in (w // 4, w // 2, 3 * w // 4):
        cx, cy = x0 + ox, y0 + h // 2
        s = max(3, w // 16)
        draw.line([(cx - s, cy), (cx + s, cy)], fill=fill, width=2)
        draw.line([(cx, cy - s), (cx, cy + s)], fill=fill, width=2)


def _draw_bolt(draw: ImageDraw.Draw, x0: int, y0: int, w: int, h: int, fill) -> None:
    pts = [
        (x0 + w // 2, y0),
        (x0 + w // 3, y0 + h // 2),
        (x0 + w // 2, y0 + h // 2),
        (x0 + w // 3, y0 + h),
        (x0 + 2 * w // 3, y0 + h // 2),
        (x0 + w // 2, y0 + h // 2),
        (x0 + 2 * w // 3, y0),
    ]
    draw.polygon(pts, fill=fill)


def draw_weather_glyph(
    draw: ImageDraw.Draw,
    box: tuple[int, int, int, int],
    bucket: str,
    fill=(220, 225, 235),
) -> None:
    """Minimal vector-style icon inside box (x1,y1,x2,y2)."""
    x1, y1, x2, y2 = box
    w, h = x2 - x1, y2 - y1
    if w < 8 or h < 8:
        return
    cx = (x1 + x2) // 2
    cy = (y1 + y2) // 2
    r = min(w, h) // 5

    if bucket == "clear":
        _draw_sun(draw, cx, cy - h // 10, r, fill)
        return
    if bucket == "partly":
        _draw_sun(draw, cx - w // 5, cy - h // 5, max(8, r * 2 // 3), fill)
        _draw_cloud(draw, cx + w // 8, cy + h // 8, w // 2, h // 3, fill=(140, 150, 165))
        return
    if bucket == "cloudy":
        _draw_cloud(draw, cx, cy, w * 4 // 5, h * 2 // 5, fill=(150, 158, 172))
        return
    if bucket in ("drizzle", "rain"):
        _draw_cloud(draw, cx, cy - h // 10, w * 4 // 5, h // 3, fill=(150, 158, 172))
        _draw_rain(draw, x1 + w // 10, cy + h // 8, w * 4 // 5, h // 3, fill=(120, 170, 220))
        return
    if bucket == "snow":
        _draw_cloud(draw, cx, cy - h // 10, w * 4 // 5, h // 3, fill=(190, 198, 210))
        _draw_snow_flakes(draw, x1 + w // 10, cy + h // 8, w * 4 // 5, h // 3, fill=(230, 240, 255))
        return
    if bucket == "storm":
        _draw_cloud(draw, cx, cy - h // 6, w * 4 // 5, h // 3, fill=(110, 118, 132))
        _draw_bolt(draw, x1 + w // 3, cy + h // 12, w // 3, h // 2, fill=(255, 220, 80))
        _draw_rain(draw, x1 + w // 10, cy + h // 4, w * 4 // 5, h // 3, fill=(100, 140, 200))
        return
    if bucket == "fog":
        for i in range(4):
            yy = y1 + h // 5 + i * h // 6
            draw.line([(x1 + w // 8, yy), (x2 - w // 8, yy)], fill=fill, width=max(2, h // 40))
        return
    _draw_cloud(draw, cx, cy, w * 4 // 5, h * 2 // 5, fill=(150, 158, 172))


def render_weather(
    draw: ImageDraw.Draw,
    widget: dict,
    body_left: int,
    body_top: int,
    body_right: int,
    body_bottom: int,
    data_dir: str,
    full_config: dict | None,
    font_path: str | None = None,
) -> None:
    ow = get_openweather_config(full_config)
    if ow is None:
        body_font = get_font(40, font_path)
        draw.text((body_left, body_top), "Weather: enable integrations.openweather", fill=(180, 180, 180), font=body_font)
        return

    payload = fetch_onecall_payload(ow, data_dir)
    body_font = get_font(44, font_path)
    small_font = get_font(36, font_path)
    temp_font = get_font(72, font_path)

    if not payload.get("ok"):
        msg = str(payload.get("error") or "Unknown error")
        y = body_top
        for line in wrap_text(draw, msg, body_font, body_right - body_left)[:5]:
            draw.text((body_left, y), line, fill=(255, 160, 140), font=body_font)
            y += int(body_font.getbbox(line)[3] - body_font.getbbox(line)[1]) + 6
        return

    cur = payload.get("current") or {}
    day = payload.get("today") or {}
    desc = (cur.get("description") or "").title() or (cur.get("main") or "Weather")
    wid = cur.get("weather_id")
    main = cur.get("main") or ""
    bucket = _condition_bucket(wid if wid is not None else None, main)

    place = (widget.get("title") or "").strip() or str(payload.get("place") or "")

    bw = body_right - body_left
    bh = body_bottom - body_top
    icon_w = min(bw // 3, max(120, bh))
    icon_pad = 12
    glyph_box = (
        body_left,
        body_top,
        body_left + icon_w - icon_pad,
        body_bottom,
    )
    text_left = body_left + icon_w

    draw_weather_glyph(draw, glyph_box, bucket)

    y = body_top
    if place:
        draw.text((text_left, y), place, fill=(200, 205, 215), font=small_font)
        y += int(small_font.getbbox(place)[3] - small_font.getbbox(place)[1]) + 6

    t_cur = _round_temp(cur.get("temp"))
    draw.text((text_left, y), f"{t_cur}°", fill="white", font=temp_font)
    th = int(temp_font.getbbox("72")[3] - temp_font.getbbox("72")[1])
    y += th + 4

    lo = _round_temp(day.get("temp_min"))
    hi = _round_temp(day.get("temp_max"))
    hl = f"H {hi}°  L {lo}°"
    draw.text((text_left, y), hl, fill=(190, 195, 205), font=small_font)
    y += int(small_font.getbbox(hl)[3] - small_font.getbbox(hl)[1]) + 8

    for line in wrap_text(draw, desc, body_font, body_right - text_left)[:2]:
        draw.text((text_left, y), line, fill=(210, 215, 225), font=body_font)
        y += int(body_font.getbbox(line)[3] - body_font.getbbox(line)[1]) + 6
