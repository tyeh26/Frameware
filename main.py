#!/usr/bin/env python3
"""
Frame TV Dashboard — entry point.

Usage:
  python main.py                        # normal run
  python main.py --dev                  # hot-reload on .py file changes
  python main.py --config /path/to.yaml # custom config location
"""

import argparse
import os
import signal
import sys
import threading

import yaml

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CONFIG = os.path.join(BASE_DIR, "config.yaml")


def load_config(path: str) -> dict:
    with open(path, "r") as f:
        return yaml.safe_load(f)


def build_integrations(config: dict, base_dir: str) -> list:
    integrations = []
    int_cfg = config.get("integrations", {}) or {}

    keep_cfg = int_cfg.get("keep", {}) or {}
    if keep_cfg.get("enabled", False):
        from integrations.keep.fetcher import KeepFetcher
        integrations.append(KeepFetcher(keep_cfg, base_dir))

    cal_cfg = int_cfg.get("calendar", {}) or {}
    if cal_cfg.get("enabled", False):
        from integrations.calendar.fetcher import CalendarFetcher
        integrations.append(CalendarFetcher(cal_cfg, base_dir))

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


def main():
    parser = argparse.ArgumentParser(
        description="Frame TV Dashboard",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Signals:\n  SIGINT  (Ctrl+C) — graceful shutdown\n  SIGUSR1           — force an immediate frame update",
    )
    parser.add_argument(
        "--config",
        default=DEFAULT_CONFIG,
        metavar="PATH",
        help="Path to config.yaml (default: ./config.yaml)",
    )
    parser.add_argument(
        "--dev",
        action="store_true",
        help="Enable hot-reload: restart automatically when any .py file changes",
    )
    args = parser.parse_args()

    if not os.path.exists(args.config):
        print(f"Error: config file not found at '{args.config}'")
        print("Copy config.example.yaml to config.yaml and fill in your settings.")
        sys.exit(1)

    config = load_config(args.config)
    stop_event = threading.Event()

    from frame.orchestrator import Orchestrator
    orchestrator = Orchestrator(config, BASE_DIR, args.config)

    def _handle_exit(signum, frame):
        print("\nGracefully shutting down...")
        stop_event.set()
        orchestrator.force_tick()  # unblock the wait so the loop exits promptly

    signal.signal(signal.SIGINT, _handle_exit)
    signal.signal(signal.SIGTERM, _handle_exit)
    if hasattr(signal, "SIGUSR1"):
        signal.signal(signal.SIGUSR1, lambda s, f: orchestrator.force_tick())

    integrations = build_integrations(config, BASE_DIR)
    for integration in integrations:
        integration.start(stop_event)

    if args.dev:
        start_dev_watcher(BASE_DIR, stop_event)

    orchestrator.run(stop_event)


if __name__ == "__main__":
    main()
