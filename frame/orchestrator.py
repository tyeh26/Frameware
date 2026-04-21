import os
import threading
from datetime import datetime

import yaml

from frame.layout import resolve_widget_sources
from frame.renderer import create_dashboard_frame
from frame.tv import push_to_tv


class Orchestrator:
    """
    Main loop: reloads config each tick, renders the dashboard image,
    and pushes it to the Samsung Frame TV.

    base_dir  — app code root (fonts, templates, Python modules); read-only in Docker
    data_dir  — mutable data root (config, art, www, data/); bind-mounted in Docker.
                Defaults to base_dir for local dev (zero change to existing file layout).
    """

    def __init__(
        self,
        config: dict,
        base_dir: str,
        config_path: str,
        data_dir: str | None = None,
    ):
        self.config = config
        self.base_dir = base_dir
        self.data_dir = data_dir if data_dir is not None else base_dir
        self.config_path = config_path
        self._tick_event = threading.Event()

    def force_tick(self):
        """Trigger an immediate update cycle (used by SIGUSR1)."""
        print("Manual tick received; updating now.")
        self._tick_event.set()

    def run(self, stop_event: threading.Event):
        """Block until stop_event is set, updating the TV once per minute."""
        print("Starting Frame TV Dashboard... (Ctrl+C to stop)")
        self._ensure_dirs()
        self._migrate_legacy_state()

        preview_path = os.path.join(self.data_dir, "www", "frame_preview.jpg")
        history_file = os.path.join(self.data_dir, "data", "frame", "history.json")

        while not stop_event.is_set():
            config = self._reload_config()
            tv_ip = config.get("tv", {}).get("ip")
            layout = resolve_widget_sources(config.get("layout", {}))
            art_cfg = config.get("art", {})

            base_image_rel = art_cfg.get("base_image")
            if base_image_rel:
                base_art = os.path.join(self.data_dir, base_image_rel)
            else:
                base_art = None

            if base_art and os.path.exists(base_art):
                try:
                    frame_data = create_dashboard_frame(
                        base_art, layout, self.base_dir, preview_path, full_config=config
                    )
                    if stop_event.is_set():
                        break
                    if tv_ip:
                        push_to_tv(frame_data, tv_ip, history_file, art_cfg)
                    else:
                        print("No TV IP configured in config.yaml; skipping push.")
                except Exception as e:
                    print(f"Frame update error: {e}")
            else:
                print(f"Base image not found ({base_image_rel!r}); skipping frame update.")

            wait_s = max(0.1, self._seconds_until_next_minute())
            self._tick_event.wait(timeout=wait_s)
            self._tick_event.clear()

    # --- private helpers ---

    def _reload_config(self) -> dict:
        """Re-read config.yaml on every tick so changes apply without restart."""
        try:
            with open(self.config_path, "r") as f:
                return yaml.safe_load(f)
        except Exception as e:
            print(f"Config reload error: {e}; using last known config.")
            return self.config

    def _seconds_until_next_minute(self) -> float:
        now = datetime.now()
        return 60 - now.second - (now.microsecond / 1_000_000)

    def _ensure_dirs(self):
        for subdir in ("www", "art", "art/uploads", "data/frame", "data/keep", "data/calendar", "data/weather"):
            os.makedirs(os.path.join(self.data_dir, subdir), exist_ok=True)

    def _migrate_legacy_state(self):
        """One-time migration: move old state/ and lists/ files into data/."""
        migrations = {
            os.path.join(self.data_dir, "state", "frame_history.json"): os.path.join(self.data_dir, "data", "frame", "history.json"),
            os.path.join(self.data_dir, "state", "keep_state.json"):    os.path.join(self.data_dir, "data", "keep", "state.json"),
            os.path.join(self.data_dir, "lists", "shop.json"):          os.path.join(self.data_dir, "data", "keep", "shop.json"),
            os.path.join(self.data_dir, "lists", "today.json"):         os.path.join(self.data_dir, "data", "keep", "today.json"),
            os.path.join(self.data_dir, "lists", "note.json"):          os.path.join(self.data_dir, "data", "keep", "note.json"),
            os.path.join(self.data_dir, "lists", "calendar.json"):      os.path.join(self.data_dir, "data", "calendar", "events.json"),
        }
        for old_path, new_path in migrations.items():
            if os.path.exists(old_path) and not os.path.exists(new_path):
                os.makedirs(os.path.dirname(new_path), exist_ok=True)
                os.rename(old_path, new_path)
                rel_old = os.path.relpath(old_path, self.data_dir)
                rel_new = os.path.relpath(new_path, self.data_dir)
                print(f"Migrated {rel_old} → {rel_new}")
