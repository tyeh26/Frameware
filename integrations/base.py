import threading
from abc import ABC, abstractmethod


class IntegrationBase(ABC):
    """Base class for all integrations that run as background sync threads."""

    def __init__(self, config: dict, base_dir: str):
        self.config = config
        self.base_dir = base_dir
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    @abstractmethod
    def fetch_once(self):
        """Perform a single fetch/sync cycle."""

    @property
    def sync_interval(self) -> int:
        """Seconds to wait between fetch cycles. Override to customize."""
        return 300

    def start(self, stop_event: threading.Event):
        """Start the background sync thread."""
        self._stop_event = stop_event
        self._thread = threading.Thread(target=self._loop, daemon=True, name=self.__class__.__name__)
        self._thread.start()

    def _loop(self):
        while not self._stop_event.is_set():
            try:
                self.fetch_once()
            except Exception as e:
                print(f"[{self.__class__.__name__}] Error: {e}")
            self._stop_event.wait(timeout=self.sync_interval)
