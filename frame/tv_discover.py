"""
LAN discovery for Samsung Smart TVs (Tizen) via SSDP + Samsung REST (samsungtvws).

IPv4 only: SSDP LOCATION and WebSocket tooling assume IPv4 literals; skip IPv6 hosts.

Frame-specific hints (model suffix → year) are optional metadata; any TV answering
``rest_device_info`` is a valid selection target.
"""

from __future__ import annotations

import ipaddress
import re
import select
import socket
import time
from typing import Any, Final
from urllib.parse import urlparse

from samsungtvws import exceptions as samsung_exceptions
from samsungtvws.rest import SamsungTVRest

# M-SEARCH service types. Many Samsung sets answer generic UPnP (LOCATION with IPv4) but not
# the Home Assistant–aligned RemoteControlReceiver / MainTVAgent STs; broad queries fix that.
# Candidates are still filtered to TVs answering Samsung REST via probe_samsung_tv (rest_device_info).
_SSDP_ST = (
    "ssdp:all",
    "upnp:rootdevice",
    "urn:samsung.com:device:RemoteControlReceiver:1",
    "urn:samsung.com:service:MainTVAgent2:1",
    "urn:samsung.com:device:ScreenMirroring:1",
)

_SSDP_ADDR = ("239.255.255.250", 1900)
_LOCATION_RE = re.compile(rb"LOCATION:\s*(\S+)\s*", re.IGNORECASE)

# Known "The Frame" model suffixes: order is longest-first for substring matching in modelName;
# years are UI hints only (same rows power FRAME_SUFFIX_REFERENCE).
_FRAME_SUFFIX_ROWS: Final[tuple[tuple[str, str], ...]] = (
    ("LS03D", "2024–2026"),
    ("LS03C", "2023"),
    ("LS03B", "2022"),
    ("LS03A", "2021"),
    ("LS03T", "2020"),
    ("LS03R", "2019"),
    ("LS03N", "2018"),
    ("LS003", "2017"),
)

FRAME_SUFFIX_REFERENCE: Final[list[dict[str, str]]] = [
    {"suffix": suf, "years": years} for suf, years in _FRAME_SUFFIX_ROWS
]

_FRAME_SUFFIX_YEARS: Final[dict[str, str]] = dict(_FRAME_SUFFIX_ROWS)


def _match_frame_suffix(model_name: str | None) -> str | None:
    if not model_name or not isinstance(model_name, str):
        return None
    compact = re.sub(r"\s+", "", model_name).upper()
    for suf, _ in _FRAME_SUFFIX_ROWS:
        if suf in compact:
            return suf
    return None


def enrich_device_from_rest(data: dict[str, Any]) -> dict[str, Any]:
    """
    Build display fields from Samsung ``rest_device_info()`` JSON (must include a ``device`` object).
    """
    dev = data.get("device") if isinstance(data, dict) else None
    if not isinstance(dev, dict):
        return {}
    model_full = dev.get("modelName") or dev.get("model") or dev.get("Model")
    name = dev.get("name") or dev.get("Name")
    suffix = _match_frame_suffix(model_full if isinstance(model_full, str) else None)
    frame_info: dict[str, Any] | None = None
    if suffix:
        frame_info = {
            "matched": True,
            "suffix": suffix,
            "years": _FRAME_SUFFIX_YEARS.get(suffix, ""),
        }
    out: dict[str, Any] = {
        "name": name,
        "model": model_full,
        "type": dev.get("type"),
        "model_code": suffix,
        "frame_series": frame_info,
    }
    return out


def _ssdp_header_dict(raw: bytes) -> dict[str, str]:
    """Parse SSDP NOTIFY / M-SEARCH response headers (line-oriented)."""
    text = raw.decode("utf-8", errors="replace")
    out: dict[str, str] = {}
    for line in text.split("\r\n"):
        if ":" not in line:
            continue
        k, _, rest = line.partition(":")
        key = k.strip().lower()
        if key:
            out[key] = rest.strip()
    return out


def _m_search(st: str) -> bytes:
    return (
        "M-SEARCH * HTTP/1.1\r\n"
        "HOST: 239.255.255.250:1900\r\n"
        'MAN: "ssdp:discover"\r\n'
        f"ST: {st}\r\n"
        "MX: 2\r\n"
        "\r\n"
    ).encode("ascii")


def _location_host_ipv4(location: str) -> str | None:
    try:
        parsed = urlparse(location.strip())
    except Exception:
        return None
    host = parsed.hostname
    if not host:
        return None
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return None
    if addr.version != 4:
        return None
    return str(addr)


def _collect_ssdp_candidates(deadline: float) -> set[str]:
    ips: set[str] = set()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("", 0))
        sock.setblocking(False)
        for st in _SSDP_ST:
            sock.sendto(_m_search(st), _SSDP_ADDR)

        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            r, _, _ = select.select([sock], [], [], min(remaining, 0.25))
            if not r:
                continue
            try:
                data, _addr = sock.recvfrom(8192)
            except OSError:
                continue
            for m in _LOCATION_RE.finditer(data):
                loc = m.group(1).decode("utf-8", errors="replace")
                host = _location_host_ipv4(loc)
                if host:
                    ips.add(host)
    finally:
        sock.close()
    return ips


def probe_samsung_tv(ip: str, timeout: float = 1.5) -> dict[str, Any] | None:
    """
    Samsung ``rest_device_info()`` (HTTP GET :8001/api/v2/); returns display fields or None.
    Any TV that returns parseable device info is selectable; Frame hints are additive.
    """
    try:
        rest = SamsungTVRest(ip, port=8001, timeout=timeout)
        data = rest.rest_device_info()
    except (
        samsung_exceptions.HttpApiError,
        samsung_exceptions.ResponseError,
        OSError,
    ):
        return None
    if not isinstance(data, dict):
        return None
    fields = enrich_device_from_rest(data)
    if not fields:
        return None
    return {"ip": ip, **fields}


def discover_samsung_tvs(total_seconds: float = 5.0) -> dict[str, Any]:
    """
    SSDP discovery then REST probe for each candidate IP.

    Returns a dict with:
    - ``candidates``: each SSDP IPv4 that was probed within the time budget, sorted;
      ``responded`` plus device fields when REST device info succeeded. IPs seen on SSDP
      but not probed in time are omitted.
    - ``tvs``: subset that responded, sorted by ``model`` then IP (any Samsung TV, not Frame-only).
    - ``frame_suffix_reference``: static suffix → years/notes for UI (does not gate selection).
    """
    start = time.monotonic()
    deadline = start + total_seconds
    # Leave at least ~0.75s after SSDP for HTTP probes; cap SSDP listen at 4s.
    ssdp_deadline = min(start + 4.0, deadline - 0.75)
    if ssdp_deadline < start + 0.35:
        ssdp_deadline = start + 0.35
    ssdp_ips = _collect_ssdp_candidates(ssdp_deadline)
    # Allow a little more time for probes if total_seconds is generous
    probe_deadline = deadline
    candidate_rows: list[dict[str, Any]] = []
    tvs: list[dict[str, Any]] = []
    seen: set[str] = set()
    ordered = sorted(ssdp_ips, key=lambda s: ipaddress.ip_address(s))
    for ip in ordered:
        if time.monotonic() > probe_deadline:
            break
        remain = max(0.1, probe_deadline - time.monotonic())
        info = probe_samsung_tv(ip, timeout=min(1.5, remain))
        row: dict[str, Any] = {"ip": ip, "responded": info is not None}
        if info:
            row["name"] = info.get("name")
            row["model"] = info.get("model")
            row["type"] = info.get("type")
            row["model_code"] = info.get("model_code")
            row["frame_series"] = info.get("frame_series")
            if info["ip"] not in seen:
                seen.add(info["ip"])
                tvs.append(dict(row))
        candidate_rows.append(row)

    def _candidate_sort_key(row: dict[str, Any]) -> tuple:
        ip_s = row.get("ip") or "0.0.0.0"
        try:
            ip_ord = ipaddress.ip_address(ip_s)
        except ValueError:
            ip_ord = ipaddress.ip_address("0.0.0.0")
        if not row.get("responded"):
            return (1, ip_ord)
        return (0, (row.get("model") or "").upper(), ip_ord)

    candidate_rows.sort(key=_candidate_sort_key)
    tvs.sort(
        key=lambda r: (
            (r.get("model") or "").upper(),
            ipaddress.ip_address(r["ip"]),
        )
    )
    return {
        "candidates": candidate_rows,
        "tvs": tvs,
        "frame_suffix_reference": list(FRAME_SUFFIX_REFERENCE),
    }


def tv_reachable(ip: str, timeout: float = 1.0) -> bool:
    """True if the TV answers the standard device REST endpoint."""
    if not ip:
        return False
    try:
        ipaddress.ip_address(ip)
    except ValueError:
        return False
    return probe_samsung_tv(ip, timeout=timeout) is not None


def dump_ssdp_for_ip(target_ip: str, listen_seconds: float = 5.0) -> list[dict[str, str]]:
    """
    Send M-SEARCH (see _SSDP_ST) and collect SSDP headers from
    replies tied to target_ip (UDP source address or LOCATION host).

    Use this to see which ST:/USN: your TV actually advertises — the REST API on :8001
    does not expose URNs. Router apps (e.g. eero) show IP/MAC, not SSDP service types.
    """
    try:
        want = ipaddress.ip_address(target_ip.strip())
    except ValueError as e:
        raise ValueError(f"Not a valid IPv4/IPv6 address: {target_ip!r}") from e
    if want.version != 4:
        raise ValueError("dump_ssdp_for_ip expects an IPv4 address.")

    want_s = str(want)
    st_queries = _SSDP_ST
    deadline = time.monotonic() + listen_seconds
    rows: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("", 0))
        sock.setblocking(False)
        for st in st_queries:
            sock.sendto(_m_search(st), _SSDP_ADDR)

        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            r, _, _ = select.select([sock], [], [], min(remaining, 0.25))
            if not r:
                continue
            try:
                data, addr = sock.recvfrom(16384)
            except OSError:
                continue
            src_ip = addr[0] if addr else ""
            hdrs = _ssdp_header_dict(data)
            loc = hdrs.get("location", "")
            loc_host = _location_host_ipv4(loc) if loc else None
            if src_ip != want_s and loc_host != want_s:
                continue
            st = hdrs.get("st", "")
            usn = hdrs.get("usn", "")
            key = (st, usn, loc)
            if key in seen:
                continue
            seen.add(key)
            rows.append(
                {
                    "from": src_ip,
                    "st": st,
                    "usn": usn,
                    "location": loc,
                    "server": hdrs.get("server", ""),
                }
            )
    finally:
        sock.close()
    return rows