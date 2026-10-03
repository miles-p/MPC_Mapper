"""grandMA3 link over OSC (UDP).

Outgoing (app -> MA3, to MA3's OSC "Port"):
    /<prefix>/cmd                 s  "<command line>"
    /<prefix>/Page<p>/Fader<e>    f  0..100   (executor master fader)
    /<prefix>/Page<p>/Key<e>      i  1 / 0    (executor key press / release)

Incoming feedback (MA3 -> app, our listen port). Sent by the bundled Lua
plugin ``ma3_plugin/APC_Feedback.lua`` via the SendOSC keyword:
    /apc/exec   iiifiii  page exec active(0/1) fader(0-100) r g b (-1 = no colour)
    /apc/page   i        current executor page
    /apc/hello  s        plugin version (heartbeat)
We additionally parse MA3's native OSC output ("Send" enabled on the OSC line):
    /<prefix>/Page<p>/Fader<e>  ... last numeric arg = level
    /<prefix>/Page<p>/Key<e>    ... last numeric arg = pressed
(MA3 prefixes SendOSC addresses with the OSC line prefix; any prefix is accepted.)
"""
from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional

from pythonosc.dispatcher import Dispatcher
from pythonosc.osc_server import BlockingOSCUDPServer
from pythonosc.udp_client import SimpleUDPClient


@dataclass
class ExecState:
    page: int
    exec: int
    active: bool = False
    fader: float = 0.0
    rgb: Optional[tuple[int, int, int]] = None


_NATIVE_RE = re.compile(r"/Page(\d+)/(Fader|Key|Button)(\d+)$", re.IGNORECASE)


class MA3Link:
    def __init__(self) -> None:
        self.client: Optional[SimpleUDPClient] = None
        self.server: Optional[BlockingOSCUDPServer] = None
        self._thread: Optional[threading.Thread] = None
        self.prefix = "gma3"
        self.host = ""
        self.port = 0
        self.listen_port = 0
        self.current_page = 1
        self.execs: dict[tuple[int, int], ExecState] = {}
        self.last_rx = 0.0
        self.plugin_version = ""
        # callbacks (called from the OSC server thread!)
        self.on_exec: Optional[Callable[[ExecState], None]] = None
        self.on_page: Optional[Callable[[int], None]] = None
        self.on_log: Optional[Callable[[str, str], None]] = None

    # ---------------- connection ----------------
    def start(self, host: str, port: int, listen_port: int, prefix: str) -> None:
        self.stop()
        self.prefix = prefix.strip("/")
        self.host, self.port, self.listen_port = host, port, listen_port
        disp = Dispatcher()
        # MA3 prepends the OSC line's prefix to SendOSC addresses, so the
        # plugin messages are routed by suffix in _h_default.
        disp.set_default_handler(self._h_default)
        # single-threaded server: packets are handled in arrival order.
        # Bind first so a busy port leaves the link fully stopped.
        self.server = BlockingOSCUDPServer(("0.0.0.0", listen_port), disp)
        self.client = SimpleUDPClient(host, port)
        self._thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self.server is not None:
            try:
                self.server.shutdown()
                self.server.server_close()
            except Exception:
                pass
        if self._thread is not None:
            self._thread.join(timeout=1.0)
        self._thread = None
        self.server = None
        self.client = None
        self.last_rx = 0.0
        self.plugin_version = ""
        self.execs.clear()

    @property
    def plugin_alive(self) -> bool:
        return time.time() - self.last_rx < 6.0

    # ---------------- sending ----------------
    def _addr(self, tail: str) -> str:
        return f"/{self.prefix}/{tail}" if self.prefix else f"/{tail}"

    def _send(self, addr: str, value) -> None:
        if self.on_log:
            self.on_log("out", f"{addr} {value!r}")
        if self.client is None:
            return
        try:
            self.client.send_message(addr, value)
        except Exception as e:
            if self.on_log:
                self.on_log("err", str(e))

    def command(self, cmd: str) -> None:
        cmd = cmd.strip()
        if cmd:
            self._send(self._addr("cmd"), cmd)

    def fader(self, page: int, exec_no: int, value: float) -> None:
        self._send(self._addr(f"Page{page}/Fader{exec_no}"), float(value))

    def key(self, page: int, exec_no: int, pressed: bool) -> None:
        self._send(self._addr(f"Page{page}/Key{exec_no}"), 1 if pressed else 0)

    # ---------------- receiving ----------------
    def _log_in(self, addr, args) -> None:
        self.last_rx = time.time()
        if self.on_log:
            self.on_log("in", f"{addr} {' '.join(map(str, args))}")

    def _update(self, page: int, ex: int, **kw) -> None:
        st = self.execs.get((page, ex)) or ExecState(page, ex)
        for k, v in kw.items():
            setattr(st, k, v)
        self.execs[(page, ex)] = st
        if self.on_exec:
            self.on_exec(st)

    def _h_exec(self, addr, *args) -> None:
        self._log_in(addr, args)
        try:
            page, ex, active, fader = int(args[0]), int(args[1]), int(args[2]), float(args[3])
            rgb = None
            if len(args) >= 7 and int(args[4]) >= 0:
                rgb = (int(args[4]), int(args[5]), int(args[6]))
        except (IndexError, ValueError, TypeError):
            return
        self._update(page, ex, active=bool(active), fader=fader, rgb=rgb)

    def _h_page(self, addr, *args) -> None:
        self._log_in(addr, args)
        try:
            p = int(args[0])
        except (IndexError, ValueError, TypeError):
            return
        if p != self.current_page:
            self.current_page = p
            if self.on_page:
                self.on_page(p)

    def _h_hello(self, addr, *args) -> None:
        self._log_in(addr, args)
        self.plugin_version = str(args[0]) if args else "?"

    def _h_default(self, addr, *args) -> None:
        if addr.endswith("/apc/exec"):
            return self._h_exec(addr, *args)
        if addr.endswith("/apc/page"):
            return self._h_page(addr, *args)
        if addr.endswith("/apc/hello"):
            return self._h_hello(addr, *args)
        self._log_in(addr, args)
        m = _NATIVE_RE.search(addr)
        if not m:
            return
        nums = [a for a in args if isinstance(a, (int, float))]
        if not nums:
            return
        page, what, ex = int(m.group(1)), m.group(2).lower(), int(m.group(3))
        if what == "fader":
            self._update(page, ex, fader=float(nums[-1]))
        # Key/Button messages are momentary presses, not executor state; the
        # plugin's /apc/exec is the source of truth for "active".

    # ---------------- helpers ----------------
    def state(self, page: int, ex: int) -> ExecState:
        return self.execs.get((page, ex)) or ExecState(page, ex)
