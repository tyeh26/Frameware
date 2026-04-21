import json
import os
import re

try:
    import keyring
    _keyring_available = True
except ImportError:
    _keyring_available = False

from integrations.base import IntegrationBase

KEYRING_SERVICE = "gkeep-token"


class KeepFetcher(IntegrationBase):
    """Syncs Google Keep lists and notes to local JSON files."""

    def __init__(self, config: dict, base_dir: str, config_path: str | None = None):
        super().__init__(config, base_dir)
        self.config_path = config_path

    @property
    def sync_interval(self) -> int:
        return int(self.config.get("sync_interval_seconds", 300))

    def fetch_once(self):
        try:
            import gkeepapi
        except ImportError as e:
            print(f"[KeepFetcher] gkeepapi not available: {e}")
            return

        email = self.config.get("email")
        master_token = self._get_master_token(email, self.config.get("master_token"))
        password = self.config.get("password")
        state_path = os.path.join(self.base_dir, self.config.get("state_file", "data/keep/state.json"))

        if not email or (not master_token and not password):
            print("[KeepFetcher] Missing email or credentials. Set via keyring or config.")
            return

        keep = gkeepapi.Keep()
        state = self._load_state(state_path)

        if master_token:
            keep.authenticate(email, master_token, state=state)
        else:
            keep.login(email, password, state=state)

        keep.sync()

        targets = self._derive_targets()
        deleted_targets = []
        for target in targets:
            output = target.get("output")
            if not output:
                continue
            out_path = os.path.join(self.base_dir, output)
            os.makedirs(os.path.dirname(out_path), exist_ok=True)

            node = self._resolve_node(keep, target)
            if node is None:
                deleted_targets.append(target)
                continue

            items = self._node_to_items(node, include_checked=bool(target.get("include_checked")))

            with open(out_path, "w") as f:
                json.dump({"items": items}, f)

        self._save_state(state_path, keep.dump())
        if deleted_targets:
            self._remove_widgets_from_config(deleted_targets)
        self._auto_discover(keep)
        self._cleanup_stale_json(self._derive_targets())
        print(f"[KeepFetcher] Synced {len(targets)} target(s).")

    # --- auto-discovery ---

    def _auto_discover(self, keep):
        """Find Keep notes/lists whose title starts with the configured prefix and
        add any new ones as widgets in layout > widgets + write their JSON data."""
        discover_cfg = self.config.get("auto_discover", {}) or {}
        if not discover_cfg.get("enabled", False):
            return

        prefix = discover_cfg.get("prefix", "Frameware")
        prefix_lower = prefix.lower()

        existing_keep_titles = {
            (w.get("keep_title") or "").lower()
            for w in self._load_widgets()
            if w.get("keep_title")
        }

        all_nodes = [n for n in keep.all() if n.__class__.__name__.lower() in ("list", "note")]

        newly_added = 0
        for node in all_nodes:
            full_title = getattr(node, "title", "") or ""
            if not full_title.lower().startswith(prefix_lower):
                continue

            display_title = self._strip_prefix(full_title, prefix)
            if display_title.lower() in existing_keep_titles:
                continue

            slug = self._title_to_slug(display_title)
            output = f"data/keep/{slug}.json"

            out_path = os.path.join(self.base_dir, output)
            os.makedirs(os.path.dirname(out_path), exist_ok=True)
            items = self._node_to_items(node, include_checked=False)
            with open(out_path, "w") as f:
                json.dump({"items": items}, f)

            node.title = display_title
            node_type = node.__class__.__name__.lower()
            self._add_widget_to_config(display_title, node_type)
            existing_keep_titles.add(display_title.lower())
            newly_added += 1
            print(f"[KeepFetcher] Auto-discovered: '{full_title}' → '{display_title}' (renamed in Keep)")

        if newly_added:
            keep.sync()

    def _add_widget_to_config(self, display_title: str, node_type: str = "list"):
        """Append a new Keep widget to layout > widgets in config.yaml."""
        if not self.config_path:
            return

        new_widget = {
            "type": node_type,
            "title": display_title,
            "keep_title": display_title,
        }

        try:
            from ruamel.yaml import YAML
            ryaml = YAML()
            ryaml.preserve_quotes = True
            with open(self.config_path, "r") as f:
                cfg = ryaml.load(f)
            cfg["layout"]["widgets"].append(new_widget)
            with open(self.config_path, "w") as f:
                ryaml.dump(cfg, f)
        except ImportError:
            import yaml as _yaml
            with open(self.config_path, "r") as f:
                cfg = _yaml.safe_load(f)
            cfg["layout"]["widgets"].append(new_widget)
            with open(self.config_path, "w") as f:
                _yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
        except Exception as e:
            print(f"[KeepFetcher] Could not update config.yaml: {e}")

    def _remove_widgets_from_config(self, deleted_targets: list):
        """Remove widgets from config.yaml whose Keep note/list has been deleted."""
        if not self.config_path or not deleted_targets:
            return
        titles_to_remove = {
            t["title"].lower() for t in deleted_targets if t.get("title")
        }
        try:
            from ruamel.yaml import YAML
            ryaml = YAML()
            ryaml.preserve_quotes = True
            with open(self.config_path, "r") as f:
                cfg = ryaml.load(f)
            cfg["layout"]["widgets"] = [
                w for w in cfg["layout"]["widgets"]
                if (w.get("keep_title") or "").lower() not in titles_to_remove
            ]
            with open(self.config_path, "w") as f:
                ryaml.dump(cfg, f)
        except ImportError:
            import yaml as _yaml
            with open(self.config_path, "r") as f:
                cfg = _yaml.safe_load(f)
            cfg["layout"]["widgets"] = [
                w for w in cfg["layout"]["widgets"]
                if (w.get("keep_title") or "").lower() not in titles_to_remove
            ]
            with open(self.config_path, "w") as f:
                _yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
        except Exception as e:
            print(f"[KeepFetcher] Could not update config.yaml: {e}")
            return
        for t in deleted_targets:
            print(f"[KeepFetcher] Removed deleted list/note from config: '{t.get('title')}'")

    # --- target derivation ---

    def _derive_targets(self) -> list:
        """Build fetch targets from layout > widgets in the current config."""
        widgets = self._load_widgets()
        targets = []
        seen_outputs = set()
        for w in widgets:
            keep_title = w.get("keep_title")
            keep_label = w.get("keep_label")
            if not keep_title and not keep_label:
                continue
            slug_key = keep_title or keep_label
            output = w.get("source") or f"data/keep/{self._title_to_slug(slug_key)}.json"
            if output in seen_outputs:
                continue
            seen_outputs.add(output)
            targets.append({
                "type": w.get("type", "list"),
                "title": keep_title,
                "label": keep_label,
                "output": output,
                "include_checked": bool(w.get("include_checked", False)),
            })
        return targets

    def _load_widgets(self) -> list:
        """Re-read config.yaml and return layout > widgets for freshness."""
        if not self.config_path:
            return []
        try:
            import yaml
            with open(self.config_path, "r") as f:
                full_cfg = yaml.safe_load(f)
            return (full_cfg.get("layout", {}) or {}).get("widgets", []) or []
        except Exception:
            return []

    def _cleanup_stale_json(self, targets: list):
        """Delete data/keep/*.json files not referenced by any active target."""
        keep_dir = os.path.join(self.base_dir, "data", "keep")
        if not os.path.isdir(keep_dir):
            return

        protected = set()
        state_file = self.config.get("state_file", "data/keep/state.json")
        protected.add(os.path.normpath(os.path.join(self.base_dir, state_file)))
        for target in targets:
            output = target.get("output")
            if output:
                protected.add(os.path.normpath(os.path.join(self.base_dir, output)))

        for fname in os.listdir(keep_dir):
            if not fname.endswith(".json"):
                continue
            fpath = os.path.normpath(os.path.join(keep_dir, fname))
            if fpath not in protected:
                try:
                    os.remove(fpath)
                    print(f"[KeepFetcher] Removed stale file: data/keep/{fname}")
                except OSError as e:
                    print(f"[KeepFetcher] Could not remove data/keep/{fname}: {e}")

    # --- helpers ---

    def _get_master_token(self, email: str, config_token: str = None) -> str | None:
        if config_token:
            return config_token
        if not _keyring_available or not email:
            return None
        try:
            token = keyring.get_password(KEYRING_SERVICE, email)
            if token:
                return token
        except Exception:
            pass
        return None

    def _load_state(self, state_path: str) -> dict | None:
        if not state_path or not os.path.exists(state_path):
            return None
        try:
            with open(state_path, "r") as f:
                return json.load(f)
        except Exception:
            return None

    def _save_state(self, state_path: str, state: dict):
        if not state_path:
            return
        os.makedirs(os.path.dirname(os.path.abspath(state_path)), exist_ok=True)
        try:
            with open(state_path, "w") as f:
                json.dump(state, f)
        except Exception as e:
            print(f"[KeepFetcher] Could not save state: {e}")

    def _strip_prefix(self, title: str, prefix: str) -> str:
        """Remove prefix (case-insensitive) and any following separator from title."""
        stripped = title[len(prefix):]
        return stripped.lstrip(". /").strip() or title

    def _title_to_slug(self, title: str) -> str:
        slug = title.lower().strip()
        slug = re.sub(r"[^a-z0-9]+", "_", slug)
        return slug.strip("_") or "unnamed"

    def _resolve_node(self, keep, target: dict):
        if target.get("id"):
            node = keep.get(target["id"])
            return node if node and not getattr(node, "trashed", False) else None

        notes = None
        if target.get("label"):
            label = keep.findLabel(target["label"])
            if label:
                notes = [n for n in keep.find(labels=[label]) if not getattr(n, "trashed", False)]

        if notes is None and target.get("title"):
            title = target["title"]
            notes = [
                n for n in keep.all()
                if not getattr(n, "trashed", False) and getattr(n, "title", "") == title
            ]

        if notes is None:
            notes = [n for n in keep.all() if not getattr(n, "trashed", False)]

        notes = self._filter_type(notes, target.get("type"))

        if target.get("title"):
            return self._select_by_title(notes, target["title"])
        return notes[0] if notes else None

    def _filter_type(self, notes: list, want_type: str | None) -> list:
        if not want_type:
            return notes
        want_type = want_type.lower()
        if want_type == "list":
            return [n for n in notes if n.__class__.__name__.lower() == "list"]
        if want_type == "note":
            return [n for n in notes if n.__class__.__name__.lower() == "note"]
        return notes

    def _select_by_title(self, notes: list, title: str):
        exact = [n for n in notes if getattr(n, "title", "") == title]
        return exact[0] if exact else None

    def _node_to_items(self, node, include_checked: bool = False) -> list[str]:
        if node is None:
            return []
        node_type = node.__class__.__name__.lower()
        if node_type == "list":
            items = [item.text for item in node.unchecked]
            if include_checked:
                items += [item.text for item in node.checked]
            return [i for i in items if i]
        text = getattr(node, "text", "") or ""
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if lines:
            return lines
        if getattr(node, "title", ""):
            return [node.title]
        return []
