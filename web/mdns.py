"""
Registers 'frameware.local' via mDNS (Bonjour/Zeroconf) so that any device
on the LAN can reach the web UI at http://frameware.local:<port>.
"""

import socket
import threading


def _get_local_ip() -> str:
    """Return the machine's primary LAN IP (not loopback)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def start_mdns(port: int, stop_event: threading.Event) -> None:
    """
    Register an mDNS HTTP service named 'frameware' on 'frameware.local'.
    Blocks until stop_event is set, then unregisters cleanly.
    Call from a daemon thread.
    """
    try:
        from zeroconf import ServiceInfo, Zeroconf
    except ImportError:
        print("[mdns] zeroconf not installed; frameware.local will not be resolvable.")
        print("[mdns] Install it with: pip install zeroconf")
        return

    local_ip = _get_local_ip()

    info = ServiceInfo(
        "_http._tcp.local.",
        "frameware._http._tcp.local.",
        addresses=[socket.inet_aton(local_ip)],
        port=port,
        properties={"path": "/"},
        server="frameware.local.",
    )

    zc = Zeroconf()
    try:
        zc.register_service(info)
        print(f"[mdns] Registered frameware.local → {local_ip}:{port}")
        stop_event.wait()
    finally:
        zc.unregister_service(info)
        zc.close()
        print("[mdns] mDNS service unregistered.")
