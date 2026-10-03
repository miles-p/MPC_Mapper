"""Akai APC mini mk2 protocol + MIDI I/O.

Protocol summary (APC mini mk2 Communication Protocol v1.0):

Inputs (device -> host), MIDI channel 1:
  * 8x8 pads ............ Note 0x00-0x3F. Note 0 = bottom-left, row-major upward.
  * Track buttons ....... Note 0x64-0x6B (row under the grid, left -> right)
  * Scene buttons ....... Note 0x70-0x77 (column right of the grid, top -> bottom)
  * Shift ............... Note 0x7A
  * Faders .............. CC 0x30-0x38 (0x38 = master fader)

LED output (host -> device):
  * Pads: Note On, *velocity = colour index* (0-127 palette), *MIDI channel =
    behaviour*:
        ch 0-6   solid, brightness 10/25/50/65/75/90/100 %
        ch 7-10  pulse  1/16, 1/8, 1/4, 1/2
        ch 11-15 blink  1/24, 1/16, 1/8, 1/4, 1/2
  * Pads, true RGB: SysEx
        F0 47 7F 4F 24 <lenMSB> <lenLSB> <startPad> <endPad>
           <Rmsb> <Rlsb> <Gmsb> <Glsb> <Bmsb> <Blsb> ... F7
    each 8-bit colour component is split into msb (bit 7) and lsb (bits 0-6).
    Several (start,end,rgb) blocks may be concatenated; len = 8 * blocks.
  * Track (red) / Scene (green) single colour buttons: Note On ch 0,
    velocity 0 = off, 1 = on, 2 = blink.
"""
from __future__ import annotations

import re
import sys
import threading
from dataclasses import dataclass
from typing import Callable, Optional

try:
    import mido
except ImportError:  # pragma: no cover - allows the GUI to load without mido
    mido = None

# MIDI port backend: WinMM via ctypes on Windows (python-rtmidi has no Windows
# wheels for current Python versions), mido's rtmidi backend elsewhere.
_ports = mido
if mido is not None and sys.platform == "win32":
    try:
        from . import winmm as _ports
    except (ImportError, OSError):  # pragma: no cover
        pass

# --------------------------------------------------------------------------- #
# Control layout
# --------------------------------------------------------------------------- #
PAD_FIRST = 0x00
PAD_LAST = 0x3F
TRACK_FIRST = 0x64
SCENE_FIRST = 0x70
SHIFT_NOTE = 0x7A
FADER_CC_FIRST = 0x30
NUM_FADERS = 9

# Control ids used throughout the app
#   pad:<0-63>  track:<0-7>  scene:<0-7>  shift  fader:<0-8>


def pad_id(row: int, col: int) -> str:
    """row 0 = bottom row."""
    return f"pad:{row * 8 + col}"


def note_to_control(note: int) -> Optional[str]:
    if PAD_FIRST <= note <= PAD_LAST:
        return f"pad:{note}"
    if TRACK_FIRST <= note < TRACK_FIRST + 8:
        return f"track:{note - TRACK_FIRST}"
    if SCENE_FIRST <= note < SCENE_FIRST + 8:
        return f"scene:{note - SCENE_FIRST}"
    if note == SHIFT_NOTE:
        return "shift"
    return None


def cc_to_control(cc: int) -> Optional[str]:
    if FADER_CC_FIRST <= cc < FADER_CC_FIRST + NUM_FADERS:
        return f"fader:{cc - FADER_CC_FIRST}"
    return None


def control_to_note(control: str) -> Optional[int]:
    kind, _, idx = control.partition(":")
    if kind == "pad":
        return PAD_FIRST + int(idx)
    if kind == "track":
        return TRACK_FIRST + int(idx)
    if kind == "scene":
        return SCENE_FIRST + int(idx)
    if kind == "shift":
        return SHIFT_NOTE
    return None


def control_kind(control: str) -> str:
    return control.partition(":")[0]


def is_button(control: str) -> bool:
    return control_kind(control) in ("pad", "track", "scene", "shift")


def is_rgb(control: str) -> bool:
    return control_kind(control) == "pad"


def control_label(control: str) -> str:
    kind, _, idx = control.partition(":")
    if kind == "pad":
        n = int(idx)
        return f"Pad R{n // 8 + 1} C{n % 8 + 1}"
    if kind == "track":
        return f"Track {int(idx) + 1}"
    if kind == "scene":
        return f"Scene {int(idx) + 1}"
    if kind == "fader":
        n = int(idx)
        return "Master Fader" if n == 8 else f"Fader {n + 1}"
    return "Shift"


ALL_CONTROLS = (
    [f"pad:{i}" for i in range(64)]
    + [f"track:{i}" for i in range(8)]
    + [f"scene:{i}" for i in range(8)]
    + ["shift"]
    + [f"fader:{i}" for i in range(NUM_FADERS)]
)

# --------------------------------------------------------------------------- #
# LED behaviours (MIDI channel for pad Note On)
# --------------------------------------------------------------------------- #
LED_MODES = [
    "Solid 10%", "Solid 25%", "Solid 50%", "Solid 65%", "Solid 75%",
    "Solid 90%", "Solid 100%",
    "Pulse 1/16", "Pulse 1/8", "Pulse 1/4", "Pulse 1/2",
    "Blink 1/24", "Blink 1/16", "Blink 1/8", "Blink 1/4", "Blink 1/2",
]
MODE_SOLID_100 = 6
MODE_BRIGHTNESS = [0.10, 0.25, 0.50, 0.65, 0.75, 0.90, 1.00]

# Single colour buttons
SINGLE_OFF, SINGLE_ON, SINGLE_BLINK = 0, 1, 2
SINGLE_STATES = ["Off", "On", "Blink"]

# --------------------------------------------------------------------------- #
# Colour palette (velocity -> RGB) from the Akai protocol document
# --------------------------------------------------------------------------- #
_PALETTE_HEX = """
000000 1E1E1E 7F7F7F FFFFFF FF4C4C FF0000 590000 190000
FFBD6C FF5400 591D00 271B00 FFFF4C FFFF00 595900 191900
88FF4C 54FF00 1D5900 142B00 4CFF4C 00FF00 005900 001900
4CFF5E 00FF19 00590D 001902 4CFF88 00FF55 00591D 001F12
4CFFB7 00FF99 005935 001912 4CC3FF 00A9FF 004152 001019
4C88FF 0055FF 001D59 000819 4C4CFF 0000FF 000059 000019
874CFF 5400FF 190064 0F0030 FF4CFF FF00FF 590059 190019
FF4C87 FF0054 59001D 220013 FF1500 993500 795100 436400
033900 005735 00547F 0000FF 00454F 2500CC 7F7F7F 202020
FF0000 BDFF2D AFED06 64FF09 108B00 00FF87 00A9FF 002AFF
3F00FF 7A00FF B21A7D 402100 FF4A00 88E106 72FF15 00FF00
3BFF26 59FF71 38FFCC 5B8AFF 3151C6 877FE9 D31DFF FF005D
FF7F00 B9B000 90FF00 835D07 392B00 144C10 0D5038 15152A
16205A 693C1C A8000A DE513D D86A1C FFE126 9EE12F 67B50F
1E1E30 DCFF6B 80FFBD 9A99FF 8E66FF 404040 757575 E0FFFF
A00000 350000 1AD000 074200 B9B000 3F3100 B35F00 4B1502
"""
PALETTE: list[tuple[int, int, int]] = [
    (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)) for h in _PALETTE_HEX.split()
]
assert len(PALETTE) == 128

# Handy named palette entries
COLOR_NAMES = {
    "Off": 0, "Dark grey": 1, "Grey": 2, "White": 3, "Red": 5, "Orange": 9,
    "Amber": 96, "Yellow": 13, "Lime": 17, "Green": 21, "Mint": 29,
    "Cyan": 33, "Sky": 37, "Blue": 45, "Purple": 49, "Magenta": 53, "Pink": 57,
}


def nearest_palette_index(rgb: tuple[int, int, int]) -> int:
    """Closest palette entry (ignoring index 0) for an arbitrary RGB colour."""
    r, g, b = rgb
    best, best_d = 3, 1 << 30
    for i, (pr, pg, pb) in enumerate(PALETTE):
        if i == 0:
            continue
        d = (2 * (pr - r) ** 2) + (4 * (pg - g) ** 2) + (3 * (pb - b) ** 2)
        if d < best_d:
            best, best_d = i, d
    return best


# --------------------------------------------------------------------------- #
# LED state (what a control currently shows) - also drives the GUI preview
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class LedState:
    color: int = 0                 # palette index (pads) / 0-2 single state (buttons)
    mode: int = MODE_SOLID_100     # behaviour channel (pads only)
    rgb: Optional[tuple[int, int, int]] = None  # true colour via SysEx (pads only)

    def display_rgb(self) -> tuple[int, int, int]:
        if self.rgb is not None:
            base = self.rgb
        else:
            base = PALETTE[self.color & 0x7F]
        if self.mode < len(MODE_BRIGHTNESS) and self.rgb is None:
            k = MODE_BRIGHTNESS[self.mode]
            return tuple(int(c * (0.25 + 0.75 * k)) for c in base)  # type: ignore
        return base

    @property
    def animated(self) -> bool:
        return self.mode >= 7


def rgb_sysex_data(start_pad: int, end_pad: int, rgb: tuple[int, int, int]) -> list[int]:
    """SysEx *data* bytes (without F0/F7, as mido wants) for one RGB range."""
    block = [start_pad & 0x3F, end_pad & 0x3F]
    for c in rgb:
        c = max(0, min(255, int(c)))
        block += [(c >> 7) & 0x01, c & 0x7F]
    length = len(block)
    return [0x47, 0x7F, 0x4F, 0x24, (length >> 7) & 0x7F, length & 0x7F] + block


# --------------------------------------------------------------------------- #
# MIDI device
# --------------------------------------------------------------------------- #
ButtonCallback = Callable[[str, bool], None]
FaderCallback = Callable[[str, int], None]


def list_ports() -> tuple[list[str], list[str]]:
    if _ports is None:
        return [], []
    try:
        return _ports.get_input_names(), _ports.get_output_names()
    except Exception:
        return [], []


def _is_secondary_port(name: str) -> bool:
    """Windows (WinMM) names a USB device's 2nd port "MIDIIN2 (APC mini mk2)" /
    "MIDIOUT2 (...)"; for the APC that is the Notes port."""
    return re.match(r"midi(in|out)\d+\s*\(", name.strip().lower()) is not None


def port_base_name(name: str) -> str:
    """Port name without the volatile client/port numbers ("... Contr 24:0" on
    Linux, "APC mini mk2 1" from rtmidi on Windows), which can change between
    sessions."""
    return re.sub(r"\s+\d+(:\d+)?$", "", name.strip())


def match_port(saved: str, names: list[str]) -> Optional[str]:
    """Find a previously saved port again, even if its index has changed."""
    if not saved:
        return None
    if saved in names:
        return saved
    base = port_base_name(saved)
    for n in names:
        if port_base_name(n) == base:
            return n
    return None


def guess_port(names: list[str]) -> Optional[str]:
    """Pick the APC mini mk2 *Control* port (the Notes port is for note mode)."""
    apc = [n for n in names if "apc" in n.lower() and "mini" in n.lower()]
    if not apc:
        return None
    # On Linux ALSA the ports are e.g. "APC mini mk2:APC mini mk2 APC mini mk2 Contr 24:0"
    # and "... APC mini mk2 Notes 24:1". On Windows (WinMM) they are "APC mini mk2"
    # and "MIDIIN2 (APC mini mk2)"; Windows MIDI Services names them
    # "APC mini mk2 Control" / "APC mini mk2 Notes".
    for n in apc:
        if "contr" in n.lower():
            return n
    for n in apc:
        if "note" not in n.lower() and not _is_secondary_port(n):
            return n
    return apc[0]


class APCMini:
    """Thread-safe-ish wrapper around the APC mini mk2 MIDI ports.

    Caches the LED state of every control so only changes are transmitted and
    the GUI can mirror the hardware.
    """

    def __init__(self) -> None:
        self.inport = None
        self.outport = None
        self.in_name: Optional[str] = None
        self.out_name: Optional[str] = None
        self._lock = threading.Lock()
        self.led: dict[str, LedState] = {}
        self.on_button: Optional[ButtonCallback] = None
        self.on_fader: Optional[FaderCallback] = None
        self.on_led: Optional[Callable[[str, LedState], None]] = None
        self.on_raw: Optional[Callable[[str, str], None]] = None  # (direction, text)
        self.on_fader_sync: Optional[Callable[[list[int]], None]] = None

    # ---------------- connection ----------------
    @property
    def connected(self) -> bool:
        return self.outport is not None or self.inport is not None

    def open(self, in_name: Optional[str], out_name: Optional[str]) -> None:
        self.close()
        if _ports is None:
            raise RuntimeError("mido / python-rtmidi not installed")
        try:
            if in_name:
                self.inport = _ports.open_input(in_name, callback=self._on_midi)
                self.in_name = in_name
            if out_name:
                self.outport = _ports.open_output(out_name)
                self.out_name = out_name
        except Exception:
            self.close()
            raise
        self.send_intro()

    def send_intro(self) -> None:
        """Introduction message; the device answers with all fader positions."""
        if mido is not None and self.outport is not None:
            self._send(mido.Message("sysex", data=[0x47, 0x7F, 0x4F, 0x60, 0x00, 0x04,
                                                   0x00, 0x01, 0x00, 0x00]))

    def close(self) -> None:
        for p in (self.inport, self.outport):
            try:
                if p is not None:
                    p.close()
            except Exception:
                pass
        self.inport = self.outport = None
        self.in_name = self.out_name = None

    # ---------------- input ----------------
    def _on_midi(self, msg) -> None:
        if self.on_raw:
            self.on_raw("in", str(msg))
        if msg.type == "sysex":
            d = list(msg.data)
            # Introduction reply: 47 7F 4F 61 <len> <len> f0..f8 (fader positions)
            if d[:4] == [0x47, 0x7F, 0x4F, 0x61] and len(d) >= 6 + NUM_FADERS:
                vals = d[6:6 + NUM_FADERS]
                if self.on_fader_sync:
                    self.on_fader_sync(vals)
            return
        if msg.type in ("note_on", "note_off"):
            ctrl = note_to_control(msg.note)
            if ctrl and self.on_button:
                pressed = msg.type == "note_on" and msg.velocity > 0
                self.on_button(ctrl, pressed)
        elif msg.type == "control_change":
            ctrl = cc_to_control(msg.control)
            if ctrl and self.on_fader:
                self.on_fader(ctrl, msg.value)

    # ---------------- output ----------------
    def _send(self, msg) -> None:
        if self.on_raw:
            self.on_raw("out", str(msg))
        if self.outport is None:
            return
        with self._lock:
            try:
                self.outport.send(msg)
            except Exception:
                pass

    def set_led(self, control: str, state: LedState, force: bool = False) -> None:
        """Set a button LED. Pads honour colour/mode/rgb, others colour = 0/1/2."""
        if not is_button(control):
            return
        if not force and self.led.get(control) == state:
            return
        self.led[control] = state
        if self.on_led:
            self.on_led(control, state)
        note = control_to_note(control)
        if note is None or mido is None:
            return
        if is_rgb(control):
            if state.rgb is not None:
                # SysEx is static RGB only; clear any blink/pulse first
                # with Note On velocity 0, then send the colour.
                self._send(mido.Message("note_on", channel=0, note=note, velocity=0))
                self._send(mido.Message("sysex", data=rgb_sysex_data(note, note, state.rgb)))
            else:
                self._send(mido.Message("note_on", channel=state.mode & 0x0F,
                                        note=note, velocity=state.color & 0x7F))
        else:
            self._send(mido.Message("note_on", channel=0, note=note,
                                    velocity=max(0, min(2, state.color))))

    def send_raw(self, data: list[int]) -> None:
        """Send raw bytes (LED lab)."""
        if mido is None:
            return
        try:
            msg = mido.Message.from_bytes(data)
        except Exception as e:
            if self.on_raw:
                self.on_raw("err", f"bad message: {e}")
            return
        self._send(msg)

    def resend_all(self) -> None:
        for ctrl, st in list(self.led.items()):
            self.set_led(ctrl, st, force=True)

    def clear_all(self) -> None:
        for ctrl in ALL_CONTROLS:
            if is_button(ctrl):
                self.set_led(ctrl, LedState(0, 0 if not is_rgb(ctrl) else MODE_SOLID_100))
