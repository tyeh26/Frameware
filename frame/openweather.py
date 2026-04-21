"""OpenWeatherMap Geocoding + One Call API 3.0 with JSON cache under data/weather/."""

from __future__ import annotations

import json
import os
import time
from typing import Any

import requests

GEO_ZIP_URL = "https://api.openweathermap.org/geo/1.0/zip"
ONECALL_URL = "https://api.openweathermap.org/data/3.0/onecall"


def _api_key(cfg: dict) -> str | None:
    key = (cfg.get("api_key") or "").strip()
    if key:
        return key
    return (os.environ.get("OPENWEATHERMAP_API_KEY") or "").strip() or None


def _zip_query(cfg: dict) -> str | None:
    z = (cfg.get("zip") or "").strip()
    if not z:
        return None
    country = (cfg.get("country") or "US").strip()
    return f"{z},{country}"


def _read_cache(path: str, ttl_s: int) -> dict[str, Any] | None:
    if not os.path.exists(path) or ttl_s <= 0:
        return None
    try:
        age = time.time() - os.path.getmtime(path)
        if age > ttl_s:
            return None
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and data.get("ok"):
            return data
    except Exception:
        return None
    return None


def _write_cache(path: str, payload: dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f)
    os.replace(tmp, path)


def fetch_onecall_payload(cfg: dict, data_dir: str) -> dict[str, Any]:
    """
    Return normalized weather payload for the dashboard.

    Reads/writes ``<data_dir>/data/weather/onecall_cache.json``.
    """
    cache_path = os.path.join(data_dir, "data", "weather", "onecall_cache.json")
    ttl = int(cfg.get("cache_seconds", 600))

    cached = _read_cache(cache_path, ttl)
    if cached is not None:
        return cached

    key = _api_key(cfg)
    zq = _zip_query(cfg)
    err_base: dict[str, Any] = {"ok": False, "error": "Weather unavailable", "fetched_at": time.time()}

    if not key:
        err = {**err_base, "error": "Set OPENWEATHERMAP_API_KEY or integrations.openweather.api_key"}
        _write_cache(cache_path, err)
        return err
    if not zq:
        err = {**err_base, "error": "Set integrations.openweather.zip (and optional country)"}
        _write_cache(cache_path, err)
        return err

    try:
        geo = requests.get(
            GEO_ZIP_URL,
            params={"zip": zq, "appid": key},
            timeout=15,
        )
        if geo.status_code != 200:
            err = {
                **err_base,
                "error": f"Geocoding HTTP {geo.status_code}",
                "fetched_at": time.time(),
            }
            _write_cache(cache_path, err)
            return err
        gj = geo.json()
        lat, lon = gj.get("lat"), gj.get("lon")
        if lat is None or lon is None:
            err = {**err_base, "error": "Geocoding: missing lat/lon", "fetched_at": time.time()}
            _write_cache(cache_path, err)
            return err
        place = gj.get("name") or zq

        oc = requests.get(
            ONECALL_URL,
            params={
                "lat": lat,
                "lon": lon,
                "appid": key,
                "units": "imperial",
                "exclude": "minutely,hourly",
            },
            timeout=20,
        )
        if oc.status_code != 200:
            detail = ""
            try:
                ej = oc.json()
                if isinstance(ej, dict) and ej.get("message"):
                    detail = f": {ej['message']}"
            except Exception:
                pass
            hint = ""
            if oc.status_code == 401:
                hint = " (One Call 3.0 requires an API key with access to that product; see openweathermap.org/price.)"
            err = {
                **err_base,
                "error": f"One Call HTTP {oc.status_code}{detail}{hint}",
                "fetched_at": time.time(),
            }
            _write_cache(cache_path, err)
            return err
        data = oc.json()
    except requests.RequestException as e:
        err = {**err_base, "error": str(e), "fetched_at": time.time()}
        _write_cache(cache_path, err)
        return err

    current = data.get("current") or {}
    daily = data.get("daily") or []
    today = daily[0] if daily else {}
    cur_w = (current.get("weather") or [{}])[0]

    payload: dict[str, Any] = {
        "ok": True,
        "fetched_at": time.time(),
        "place": place,
        "lat": lat,
        "lon": lon,
        "timezone": data.get("timezone"),
        "current": {
            "temp": current.get("temp"),
            "feels_like": current.get("feels_like"),
            "humidity": current.get("humidity"),
            "wind_speed": current.get("wind_speed"),
            "weather_id": cur_w.get("id"),
            "description": (cur_w.get("description") or "").strip(),
            "icon": cur_w.get("icon"),
            "main": (cur_w.get("main") or "").strip(),
        },
        "today": {
            "temp_min": (today.get("temp") or {}).get("min"),
            "temp_max": (today.get("temp") or {}).get("max"),
            "pop": today.get("pop"),
            "uvi": today.get("uvi"),
            "summary": (today.get("summary") or "").strip() if isinstance(today.get("summary"), str) else "",
        },
    }
    _write_cache(cache_path, payload)
    return payload


def get_openweather_config(full_config: dict | None) -> dict | None:
    ow = (full_config or {}).get("integrations", {}).get("openweather") or {}
    if not ow.get("enabled", False):
        return None
    return ow
