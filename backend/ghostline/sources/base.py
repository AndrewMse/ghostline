from __future__ import annotations

import socket
from abc import ABC, abstractmethod
from typing import AsyncIterator

from ..models import Event


class Source(ABC):
    """A sim adapter: turns a sim's telemetry feed into `models` events."""

    sim: str = "unknown"

    def __init__(self) -> None:
        self.connected = False
        self.detail = ""

    @abstractmethod
    def events(self) -> AsyncIterator[Event]:
        """Yield events forever, reconnecting as needed."""

    def status(self) -> dict:
        return {"sim": self.sim, "connected": self.connected, "detail": self.detail}


def lan_ip() -> str:
    """This machine's primary LAN address (no packet is sent)."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect(("8.8.8.8", 65530))
            return s.getsockname()[0]
        except OSError:
            return "127.0.0.1"
