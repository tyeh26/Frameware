import json
import os

try:
    import keyring
    _keyring_available = True
except ImportError:
    _keyring_available = False

from integrations.base import IntegrationBase

KEYRING_SERVICE = "gkeep-token"


class KeepFetcher(IntegrationBase):
    """Syncs Google Keep lists and notes to local JSON files."""

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
        targets = self.config.get("targets", [])

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

        for target in targets:
            output = target.get("output")
            if not output:
                continue
            out_path = os.path.join(self.base_dir, output)
            os.makedirs(os.path.dirname(out_path), exist_ok=True)

            node = self._resolve_node(keep, target)
            items = self._node_to_items(node, include_checked=bool(target.get("include_checked")))

            with open(out_path, "w") as f:
                json.dump({"items": items}, f)

        self._save_state(state_path, keep.dump())
        print(f"[KeepFetcher] Synced {len(targets)} target(s).")

    # --- helpers ---

    def _get_master_token(self, email: str, config_token: str = None) -> str | None:
        if _keyring_available and email:
            token = keyring.get_password(KEYRING_SERVICE, email)
            if token:
                return token
        return config_token

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

    def _resolve_node(self, keep, target: dict):
        if target.get("id"):
            return keep.get(target["id"])

        notes = None
        if target.get("label"):
            label = keep.findLabel(target["label"])
            if label:
                notes = list(keep.find(labels=[label]))

        if notes is None and target.get("title"):
            notes = list(keep.find(query=target["title"]))

        if notes is None:
            notes = list(keep.all())

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
        if exact:
            return exact[0]
        return notes[0] if notes else None

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
