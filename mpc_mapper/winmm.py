"""Windows MIDI I/O through WinMM (ctypes), used instead of python-rtmidi.

python-rtmidi has no Windows wheels for current Python versions, so pip would
need a C++ compiler to install it. WinMM ships with every Windows version and
is what rtmidi uses underneath anyway. Messages are mido.Message objects, so
the rest of the app doesn't care which backend is active.

The WinMM callback must not call multimedia functions (that can deadlock), so
it only queues the raw data; a worker thread parses it, calls the user
callback and hands SysEx buffers back to the driver.
"""
from __future__ import annotations

import ctypes
import queue
import sys
import threading
import time
from ctypes import wintypes
from typing import Callable, Optional

import mido

if sys.platform != "win32":  # pragma: no cover
    raise ImportError("winmm backend is Windows only")

_winmm = ctypes.WinDLL("winmm")

MAXPNAMELEN = 32
CALLBACK_NULL = 0x00000000
CALLBACK_FUNCTION = 0x00030000
MIM_DATA = 0x3C3
MIM_LONGDATA = 0x3C4
MHDR_DONE = 0x00000001

SYSEX_BUFFERS = 4
SYSEX_BUFFER_SIZE = 1024


class MIDIINCAPSW(ctypes.Structure):
    _fields_ = [("wMid", wintypes.WORD), ("wPid", wintypes.WORD),
                ("vDriverVersion", wintypes.UINT),
                ("szPname", wintypes.WCHAR * MAXPNAMELEN),
                ("dwSupport", wintypes.DWORD)]


class MIDIOUTCAPSW(ctypes.Structure):
    _fields_ = [("wMid", wintypes.WORD), ("wPid", wintypes.WORD),
                ("vDriverVersion", wintypes.UINT),
                ("szPname", wintypes.WCHAR * MAXPNAMELEN),
                ("wTechnology", wintypes.WORD), ("wVoices", wintypes.WORD),
                ("wNotes", wintypes.WORD), ("wChannelMask", wintypes.WORD),
                ("dwSupport", wintypes.DWORD)]


class MIDIHDR(ctypes.Structure):
    pass


MIDIHDR._fields_ = [("lpData", ctypes.c_void_p), ("dwBufferLength", wintypes.DWORD),
                    ("dwBytesRecorded", wintypes.DWORD), ("dwUser", ctypes.c_size_t),
                    ("dwFlags", wintypes.DWORD), ("lpNext", ctypes.POINTER(MIDIHDR)),
                    ("reserved", ctypes.c_size_t), ("dwOffset", wintypes.DWORD),
                    ("dwReserved", ctypes.c_size_t * 8)]

MIDIINPROC = ctypes.WINFUNCTYPE(None, wintypes.HANDLE, wintypes.UINT, ctypes.c_size_t,
                                ctypes.c_size_t, ctypes.c_size_t)

_H = wintypes.HANDLE
_P = ctypes.POINTER
for _name, _args in {
    "midiInGetNumDevs": [], "midiOutGetNumDevs": [],
    "midiInGetDevCapsW": [ctypes.c_size_t, _P(MIDIINCAPSW), wintypes.UINT],
    "midiOutGetDevCapsW": [ctypes.c_size_t, _P(MIDIOUTCAPSW), wintypes.UINT],
    "midiInOpen": [_P(_H), wintypes.UINT, ctypes.c_size_t, ctypes.c_size_t, wintypes.DWORD],
    "midiOutOpen": [_P(_H), wintypes.UINT, ctypes.c_size_t, ctypes.c_size_t, wintypes.DWORD],
    "midiInStart": [_H], "midiInStop": [_H], "midiInReset": [_H], "midiInClose": [_H],
    "midiOutReset": [_H], "midiOutClose": [_H],
    "midiInPrepareHeader": [_H, _P(MIDIHDR), wintypes.UINT],
    "midiInUnprepareHeader": [_H, _P(MIDIHDR), wintypes.UINT],
    "midiInAddBuffer": [_H, _P(MIDIHDR), wintypes.UINT],
    "midiOutPrepareHeader": [_H, _P(MIDIHDR), wintypes.UINT],
    "midiOutUnprepareHeader": [_H, _P(MIDIHDR), wintypes.UINT],
    "midiOutLongMsg": [_H, _P(MIDIHDR), wintypes.UINT],
    "midiOutShortMsg": [_H, wintypes.DWORD],
    "midiInGetErrorTextW": [wintypes.UINT, wintypes.LPWSTR, wintypes.UINT],
    "midiOutGetErrorTextW": [wintypes.UINT, wintypes.LPWSTR, wintypes.UINT],
}.items():
    _fn = getattr(_winmm, _name)
    _fn.argtypes = _args
    _fn.restype = wintypes.UINT


def _check(res: int, what: str, out: bool = False) -> None:
    if res == 0:
        return
    buf = ctypes.create_unicode_buffer(256)
    getter = _winmm.midiOutGetErrorTextW if out else _winmm.midiInGetErrorTextW
    getter(res, buf, len(buf))
    raise OSError(f"{what} failed: {buf.value or 'error'} (MMSYSERR {res})")


# --------------------------------------------------------------------------- #
# Port names
# --------------------------------------------------------------------------- #
def _unique(names: list[str]) -> list[str]:
    """Two identical devices get "Name", "Name #2", ... so each is selectable."""
    seen: dict[str, int] = {}
    out = []
    for n in names:
        seen[n] = seen.get(n, 0) + 1
        out.append(n if seen[n] == 1 else f"{n} #{seen[n]}")
    return out


def get_input_names() -> list[str]:
    names = []
    for i in range(_winmm.midiInGetNumDevs()):
        caps = MIDIINCAPSW()
        if _winmm.midiInGetDevCapsW(i, ctypes.byref(caps), ctypes.sizeof(caps)) == 0:
            names.append(caps.szPname)
        else:
            names.append(f"MIDI In {i}")
    return _unique(names)


def get_output_names() -> list[str]:
    names = []
    for i in range(_winmm.midiOutGetNumDevs()):
        caps = MIDIOUTCAPSW()
        if _winmm.midiOutGetDevCapsW(i, ctypes.byref(caps), ctypes.sizeof(caps)) == 0:
            names.append(caps.szPname)
        else:
            names.append(f"MIDI Out {i}")
    return _unique(names)


def _index(name: str, names: list[str], kind: str) -> int:
    try:
        return names.index(name)
    except ValueError:
        raise OSError(f"MIDI {kind} port not found: {name!r}") from None


# --------------------------------------------------------------------------- #
# Input
# --------------------------------------------------------------------------- #
def _short_len(status: int) -> int:
    hi = status & 0xF0
    if hi in (0xC0, 0xD0) or status in (0xF1, 0xF3):
        return 2
    if status == 0xF6 or status >= 0xF8:
        return 1
    return 3


class Input:
    def __init__(self, name: str, callback: Callable[[mido.Message], None]) -> None:
        self.name = name
        self.callback = callback
        self.closed = False
        self._q: queue.Queue = queue.Queue()
        self._sysex = bytearray()
        self._lock = threading.Lock()
        self._handle = _H()
        self._proc = MIDIINPROC(self._on_winmm)   # keep a reference: WinMM calls it
        idx = _index(name, get_input_names(), "input")
        _check(_winmm.midiInOpen(ctypes.byref(self._handle), idx,
                                 ctypes.cast(self._proc, ctypes.c_void_p).value, 0,
                                 CALLBACK_FUNCTION), f"Opening {name!r}")
        self._bufs = []
        self._hdrs = []
        try:
            for _ in range(SYSEX_BUFFERS):
                buf = ctypes.create_string_buffer(SYSEX_BUFFER_SIZE)
                hdr = MIDIHDR()
                hdr.lpData = ctypes.cast(buf, ctypes.c_void_p)
                hdr.dwBufferLength = SYSEX_BUFFER_SIZE
                _check(_winmm.midiInPrepareHeader(self._handle, ctypes.byref(hdr),
                                                  ctypes.sizeof(hdr)), "midiInPrepareHeader")
                _check(_winmm.midiInAddBuffer(self._handle, ctypes.byref(hdr),
                                              ctypes.sizeof(hdr)), "midiInAddBuffer")
                self._bufs.append(buf)
                self._hdrs.append(hdr)
            self._thread = threading.Thread(target=self._worker, name="winmm-in", daemon=True)
            self._thread.start()
            _check(_winmm.midiInStart(self._handle), "midiInStart")
        except Exception:
            self.close()
            raise

    # Runs on a WinMM thread: only queue, never call multimedia functions here.
    def _on_winmm(self, _h, msg, _inst, p1, _p2) -> None:
        if msg == MIM_DATA:
            self._q.put((MIM_DATA, p1))
        elif msg == MIM_LONGDATA:
            self._q.put((MIM_LONGDATA, p1))

    def _worker(self) -> None:
        while True:
            item = self._q.get()
            if item is None:
                return
            kind, p1 = item
            try:
                if kind == MIM_DATA:
                    status = p1 & 0xFF
                    data = [status, (p1 >> 8) & 0xFF, (p1 >> 16) & 0xFF][:_short_len(status)]
                    self._emit(data)
                else:
                    self._long_data(p1)
            except Exception:
                pass

    def _long_data(self, p_hdr: int) -> None:
        hdr = MIDIHDR.from_address(p_hdr)
        n = hdr.dwBytesRecorded
        if self.closed:
            return
        if n:
            self._sysex += ctypes.string_at(hdr.lpData, n)
            if self._sysex[:1] != b"\xF0":
                self._sysex.clear()
            elif self._sysex[-1:] == b"\xF7":
                data = list(self._sysex)
                self._sysex.clear()
                self._emit(data)
        with self._lock:
            if not self.closed:
                hdr.dwBytesRecorded = 0
                _winmm.midiInAddBuffer(self._handle, ctypes.byref(hdr), ctypes.sizeof(hdr))

    def _emit(self, data: list[int]) -> None:
        try:
            msg = mido.Message.from_bytes(data)
        except (ValueError, TypeError):
            return
        if self.callback:
            self.callback(msg)

    def close(self) -> None:
        with self._lock:
            if self.closed:
                return
            self.closed = True
            if self._handle:
                _winmm.midiInStop(self._handle)
                _winmm.midiInReset(self._handle)   # returns all SysEx buffers
                for hdr in self._hdrs:
                    _winmm.midiInUnprepareHeader(self._handle, ctypes.byref(hdr),
                                                 ctypes.sizeof(hdr))
                _winmm.midiInClose(self._handle)
                self._handle = _H()
        self._q.put(None)


# --------------------------------------------------------------------------- #
# Output
# --------------------------------------------------------------------------- #
class Output:
    def __init__(self, name: str) -> None:
        self.name = name
        self.closed = False
        self._handle = _H()
        self._lock = threading.Lock()
        idx = _index(name, get_output_names(), "output")
        _check(_winmm.midiOutOpen(ctypes.byref(self._handle), idx, 0, 0, CALLBACK_NULL),
               f"Opening {name!r}", out=True)

    def send(self, msg: mido.Message) -> None:
        data = msg.bytes()
        with self._lock:
            if self.closed:
                raise OSError("MIDI output is closed")
            if data[0] == 0xF0:
                self._send_long(bytes(data))
            else:
                packed = 0
                for i, b in enumerate(data[:3]):
                    packed |= (b & 0xFF) << (8 * i)
                _check(_winmm.midiOutShortMsg(self._handle, packed), "midiOutShortMsg",
                       out=True)

    def _send_long(self, data: bytes) -> None:
        buf = ctypes.create_string_buffer(data, len(data))
        hdr = MIDIHDR()
        hdr.lpData = ctypes.cast(buf, ctypes.c_void_p)
        hdr.dwBufferLength = hdr.dwBytesRecorded = len(data)
        size = ctypes.sizeof(hdr)
        _check(_winmm.midiOutPrepareHeader(self._handle, ctypes.byref(hdr), size),
               "midiOutPrepareHeader", out=True)
        try:
            _check(_winmm.midiOutLongMsg(self._handle, ctypes.byref(hdr), size),
                   "midiOutLongMsg", out=True)
            deadline = time.monotonic() + 1.0
            while not (hdr.dwFlags & MHDR_DONE) and time.monotonic() < deadline:
                time.sleep(0.0005)
        finally:
            _winmm.midiOutUnprepareHeader(self._handle, ctypes.byref(hdr), size)

    def close(self) -> None:
        with self._lock:
            if self.closed:
                return
            self.closed = True
            if self._handle:
                _winmm.midiOutReset(self._handle)
                _winmm.midiOutClose(self._handle)
                self._handle = _H()


def open_input(name: str, callback: Optional[Callable[[mido.Message], None]] = None) -> Input:
    return Input(name, callback)


def open_output(name: str) -> Output:
    return Output(name)
