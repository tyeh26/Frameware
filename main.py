#!/usr/bin/env python3
"""
Frame TV Dashboard — entry point.

Usage:
  python main.py                           # normal run (web UI on by default)
  python main.py --dev                     # hot-reload on .py file changes
  python main.py --config /path/to.yaml    # explicit config location
  python main.py --data-dir /path/to/data  # mutable data directory (config, art, www, data/)
  python main.py --no-web                  # disable the web UI
  python main.py --reset-config            # re-seed config.yaml from config.example.yaml

Environment variables:
  FRAMEWARE_DATA_DIR     Override the mutable data directory (same as --data-dir)
  FRAMEWARE_RESET_CONFIG Set to "true" to force re-seed config on startup
"""

import argparse
import os
import shutil
import signal
import socket
import sys
import threading

import yaml

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _resolve_data_dir(args) -> str:
    """Resolve the mutable data directory: --data-dir > FRAMEWARE_DATA_DIR > BASE_DIR."""
    if getattr(args, "data_dir", None):
        return os.path.abspath(args.data_dir)
    env = os.environ.get("FRAMEWARE_DATA_DIR", "").strip()
    if env:
        return os.path.abspath(env)
    return BASE_DIR


def _seed_config(config_path: str, reset: bool = False) -> None:
    """
    Copy config.example.yaml → config_path if it doesn't exist yet (or reset is True).
    This is the 'seed on first run' pattern: the image always contains config.example.yaml
    as the authoritative schema template; user data lives in the volume/data_dir.
    """
    example = os.path.join(BASE_DIR, "config.example.yaml")
    if not os.path.exists(example):
        return
    if os.path.exists(config_path) and not reset:
        return
    config_dir = os.path.dirname(config_path)
    if config_dir:
        os.makedirs(config_dir, exist_ok=True)
    if reset and os.path.exists(config_path):
        print("[config] Re-seeding config.yaml from config.example.yaml (reset requested).")
    shutil.copy2(example, config_path)
    print(f"[config] Seeded {config_path} from config.example.yaml")
    print("[config] Edit this file (or use the web UI) to configure your Frame TV.")


def _find_free_port(start: int, max_tries: int = 10) -> int:
    for port in range(start, start + max_tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("0.0.0.0", port))
                return port
            except OSError:
                continue
    raise OSError(f"No free port found in range {start}–{start + max_tries - 1}")


def load_config(path: str) -> dict:
    with open(path, "r") as f:
        return yaml.safe_load(f)


def build_integrations(config: dict, data_dir: str, config_path: str) -> list:
    integrations = []
    int_cfg = config.get("integrations", {}) or {}

    keep_cfg = int_cfg.get("keep", {}) or {}
    if keep_cfg.get("enabled", False):
        from integrations.keep.fetcher import KeepFetcher
        integrations.append(KeepFetcher(keep_cfg, data_dir, config_path))

    cal_cfg = int_cfg.get("calendar", {}) or {}
    if cal_cfg.get("enabled", False):
        from integrations.calendar.fetcher import CalendarFetcher
        integrations.append(CalendarFetcher(cal_cfg, data_dir))

    return integrations


def start_dev_watcher(base_dir: str, stop_event: threading.Event):
    """
    Watch all .py files under base_dir and restart the process when any change.
    Uses os.execv so the restarted process inherits the same argv (including --dev).
    """
    try:
        from watchdog.observers import Observer
        from watchdog.events import FileSystemEventHandler
    except ImportError:
        print("[dev] watchdog not installed; hot-reload unavailable.")
        print("[dev] Install it with: pip install watchdog")
        return

    class _ReloadHandler(FileSystemEventHandler):
        def on_modified(self, event):
            if not event.is_directory and event.src_path.endswith(".py"):
                print(f"[dev] Changed: {os.path.relpath(event.src_path, base_dir)} — restarting...")
                stop_event.set()
                os.execv(sys.executable, [sys.executable] + sys.argv)

    observer = Observer()
    observer.schedule(_ReloadHandler(), base_dir, recursive=True)
    observer.daemon = True
    observer.start()
    print("[dev] Hot-reload active — watching .py files for changes.")


def _start_web(
    config: dict,
    config_path: str,
    data_dir: str,
    orchestrator,
    stop_event: threading.Event,
):
    """Start the Flask web UI and mDNS registration in daemon threads."""
    web_cfg = config.get("web", {}) or {}
    requested = int(web_cfg.get("port", 5000))
    port = _find_free_port(requested)
    if port != requested:
        print(f"[web] Port {requested} in use — using port {port} instead")

    from web.app import create_app
    app = create_app(
        config_path=config_path,
        base_dir=BASE_DIR,
        data_dir=data_dir,
        orchestrator=orchestrator,
    )

    flask_thread = threading.Thread(
        target=lambda: app.run(host="0.0.0.0", port=port, use_reloader=False, threaded=True),
        daemon=True,
        name="flask",
    )
    flask_thread.start()
    print(f"[web] UI available at http://localhost:{port}")

    from web.mdns import start_mdns
    mdns_thread = threading.Thread(
        target=start_mdns,
        args=(port, stop_event),
        daemon=True,
        name="mdns",
    )
    mdns_thread.start()


def main():
    parser = argparse.ArgumentParser(
        description="Frame TV Dashboard",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Signals:\n"
            "  SIGINT  (Ctrl+C) — graceful shutdown\n"
            "  SIGUSR1           — force an immediate frame update\n\n"
            "Environment variables:\n"
            "  FRAMEWARE_DATA_DIR     Mutable data directory (config, art, www, data/)\n"
            "  FRAMEWARE_RESET_CONFIG Set to 'true' to re-seed config.yaml from example"
        ),
    )
    parser.add_argument(
        "--config",
        default=None,
        metavar="PATH",
        help=(
            "Explicit path to config.yaml. "
            "If omitted, defaults to <data-dir>/config.yaml."
        ),
    )
    parser.add_argument(
        "--data-dir",
        default=None,
        metavar="PATH",
        dest="data_dir",
        help=(
            "Root directory for mutable data (config, art uploads, www, data/). "
            "Overrides FRAMEWARE_DATA_DIR. Defaults to the project directory."
        ),
    )
    parser.add_argument(
        "--reset-config",
        action="store_true",
        dest="reset_config",
        help="Re-seed config.yaml from config.example.yaml even if one already exists.",
    )
    parser.add_argument(
        "--dev",
        action="store_true",
        help="Enable hot-reload: restart automatically when any .py file changes",
    )
    parser.add_argument(
        "--no-web",
        action="store_true",
        dest="no_web",
        help="Disable the web UI and mDNS registration",
    )
    args = parser.parse_args()

    data_dir = _resolve_data_dir(args)
    reset = args.reset_config or os.environ.get("FRAMEWARE_RESET_CONFIG", "").lower() == "true"

    config_path = args.config if args.config else os.path.join(data_dir, "config.yaml")
    _seed_config(config_path, reset=reset)

    if not os.path.exists(config_path):
        print(f"Error: config file not found at '{config_path}'")
        print("Copy config.example.yaml to config.yaml and fill in your settings.")
        sys.exit(1)

    config = load_config(config_path)
    stop_event = threading.Event()

    from frame.orchestrator import Orchestrator
    orchestrator = Orchestrator(config, BASE_DIR, config_path, data_dir=data_dir)

    # After sleep/wake, TV WebSocket calls can block a long time; the SIGINT handler
    # only runs when the main thread gets control back. A second Ctrl+C exits immediately.
    _sigint_once = False

    def _handle_exit(signum, frame):
        nonlocal _sigint_once
        if _sigint_once:
            print("\nExiting immediately (second interrupt).")
            os._exit(128 + signum)
        _sigint_once = True
        print("\nGracefully shutting down... (Ctrl+C again to force quit)")
        stop_event.set()
        orchestrator.force_tick()  # unblock the wait so the loop exits promptly

    signal.signal(signal.SIGINT, _handle_exit)
    signal.signal(signal.SIGTERM, _handle_exit)
    if hasattr(signal, "SIGUSR1"):
        signal.signal(signal.SIGUSR1, lambda s, f: orchestrator.force_tick())

    integrations = build_integrations(config, data_dir, config_path)
    for integration in integrations:
        integration.start(stop_event)

    if not args.no_web:
        _start_web(config, config_path, data_dir, orchestrator, stop_event)

    if args.dev:
        start_dev_watcher(BASE_DIR, stop_event)

    orchestrator.run(stop_event)


if __name__ == "__main__":
    main()
