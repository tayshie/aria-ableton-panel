"""JSON-over-TCP client for the AbletonMCP Remote Script (default port 9877).

Protocol (see the Remote Script in Live's User Library/Remote Scripts/AbletonMCP):
    ->  {"type": "<command>", "params": {...}}\n
    <-  {"status": "success", "result": {...}}\n
    <-  {"status": "error", "message": "..."}\n

One request/response in flight at a time, so the socket is guarded by a lock.
"""

from __future__ import annotations

import json
import socket
import threading

# The Remote Script marshals every command onto Live's main thread with a 10 s
# budget (60 s for create_audio_clip). Stay above that or we can drop the socket
# in the same instant the script answers.
REMOTE_TIMEOUTS = {"create_audio_clip": 60.0}
DEFAULT_BUDGET = 10.0
HEADROOM = 6.0


class LiveError(Exception):
    """Raised for transport failures and for errors reported by Live itself."""


class Live:
    def __init__(self, host: str = "127.0.0.1", port: int = 9877) -> None:
        self.host = host
        self.port = port
        self._sock: socket.socket | None = None
        self._lock = threading.Lock()

    # -- transport ---------------------------------------------------------
    def _close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
        self._sock = None

    def _connect(self) -> None:
        self._sock = socket.create_connection((self.host, self.port), timeout=4.0)
        self._sock.settimeout(None)

    def probe(self) -> tuple[bool, str]:
        """Cheap liveness check: can we open the TCP port at all?"""
        try:
            s = socket.create_connection((self.host, self.port), timeout=1.5)
            s.close()
            return True, ""
        except OSError as exc:
            return False, str(exc)

    def send(self, command: str, params: dict | None = None,
             timeout: float | None = None) -> object:
        params = params or {}
        if timeout is None:
            timeout = REMOTE_TIMEOUTS.get(command, DEFAULT_BUDGET) + HEADROOM

        with self._lock:
            if self._sock is None:
                try:
                    self._connect()
                except OSError as exc:
                    raise LiveError(
                        "Ableton is not reachable on %s:%s (%s). Is Live open and is "
                        "'AbletonMCP' selected as a Control Surface in Settings > "
                        "Link, Tempo & MIDI > MIDI?" % (self.host, self.port, exc)
                    ) from exc
            assert self._sock is not None
            payload = json.dumps({"type": command, "params": params}).encode("utf-8")
            try:
                self._sock.settimeout(timeout)
                self._sock.sendall(payload)
                response = self._read_frame()
            except TimeoutError:
                self._close()
                raise LiveError(
                    "Timed out waiting for Live to answer '%s'. If every command "
                    "times out, a modal dialog is open in Live and is blocking the "
                    "Remote Script - dismiss it and retry." % command
                ) from None
            except OSError as exc:
                self._close()
                raise LiveError("Connection to Live dropped (%s)." % exc) from exc

        if response.get("status") == "error":
            raise LiveError(str(response.get("message") or "unknown Live error"))
        return response.get("result", {})

    def _read_frame(self) -> dict:
        assert self._sock is not None
        chunks: list[bytes] = []
        while True:
            chunk = self._sock.recv(8192)
            if not chunk:
                raise OSError("remote closed the connection mid-reply")
            chunks.append(chunk)
            if not chunk.rstrip().endswith(b"}"):
                continue
            try:
                return json.loads(b"".join(chunks).decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                # Multibyte character split across chunks - keep reading.
                continue
