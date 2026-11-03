from __future__ import annotations

from PySide6.QtCore import QObject, Signal, QThread

from app.core.evolink import EvolinkClient, EvolinkConfig


class EvolinkConnectivityWorker(QThread):
    finished = Signal(str)
    failed = Signal(str)

    def __init__(self, api_key: str, base_url: str, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.api_key = api_key
        self.base_url = base_url

    def run(self) -> None:  # pragma: no cover
        try:
            config = EvolinkConfig.from_values(self.api_key, self.base_url)
            client = EvolinkClient(config, timeout=20)
            client.test_connection()
            self.finished.emit(config.base_url)
        except Exception as exc:
            self.failed.emit(str(exc))
