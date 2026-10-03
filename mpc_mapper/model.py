"""Mapping data model + the catalogue of draggable grandMA3 controls.

Every assignment is ultimately a set of *command templates* that are sent to
grandMA3 as command lines (via OSC "/<prefix>/cmd"), or an OSC executor
fader/key address. Templates may contain the placeholders

    {page}   executor page   ("" + current page when page == 0)
    {exec}   executor number
    {target} "Executor {page}.{exec}" / "Executor {exec}" helper
    {value}  fader value 0-100 (faders only)

so anything the catalogue does not cover can be done with a custom command.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Optional

from . import apc

# --------------------------------------------------------------------------- #
# LED feedback configuration
# --------------------------------------------------------------------------- #
FEEDBACK_SOURCES = {
    "static": "Static (always 'off' look)",
    "press": "Lit while pressed",
    "latch": "Local toggle (latched)",
    "exec_active": "MA3: executor running",
    "exec_fader": "MA3: executor fader > 0",
    "page": "MA3: current page == page",
}


@dataclass
class LedConfig:
    source: str = "exec_active"
    off_color: int = 1            # palette idx (pads) / 0-2 (track/scene)
    off_mode: int = apc.MODE_SOLID_100
    on_color: int = 21            # green
    on_mode: int = apc.MODE_SOLID_100
    use_ma3_color: bool = False   # pads: use MA3 appearance colour (true RGB)
    ma3_dim: float = 0.15         # brightness of MA3 colour when "off"

    @staticmethod
    def default_for(control: str) -> "LedConfig":
        if apc.is_rgb(control):
            return LedConfig()
        return LedConfig(off_color=apc.SINGLE_OFF, on_color=apc.SINGLE_ON)


# --------------------------------------------------------------------------- #
# Assignment
# --------------------------------------------------------------------------- #
@dataclass
class Assignment:
    name: str = ""
    catalog_id: str = "custom"
    page: int = 0                 # 0 = follow current MA3 page
    exec: int = 201
    press_cmd: str = ""
    release_cmd: str = ""
    value_cmd: str = ""           # faders: command template (uses {value})
    osc_fader: bool = False       # faders: use /<prefix>/Page{p}/Fader{e} instead
    osc_key: bool = False         # buttons: use /<prefix>/Page{p}/Key{e} 1/0
    led: LedConfig = field(default_factory=LedConfig)

    def target(self, current_page: int) -> str:
        if self.page > 0:
            return f"Executor {self.page}.{self.exec}"
        return f"Executor {self.exec}"

    def eff_page(self, current_page: int) -> int:
        return self.page if self.page > 0 else current_page

    def render(self, template: str, current_page: int, value: Optional[float] = None) -> str:
        if not template:
            return ""
        # plain replacement (not str.format) so stray braces in a command
        # line, e.g. Lua "...{...}", never raise
        out = template
        for key, val in (("{target}", self.target(current_page)),
                         ("{page}", str(self.eff_page(current_page))),
                         ("{exec}", str(self.exec)),
                         ("{value}", "" if value is None else f"{value:g}")):
            out = out.replace(key, val)
        return out

    def uses_exec(self) -> bool:
        blob = self.press_cmd + self.release_cmd + self.value_cmd
        return ("{target}" in blob or "{exec}" in blob or self.osc_fader or self.osc_key
                or self.led.source in ("exec_active", "exec_fader"))

    def to_json(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_json(d: dict) -> "Assignment":
        d = dict(d)
        led_d = d.pop("led", None) or {}
        led = LedConfig(**{k: v for k, v in led_d.items() if k in LedConfig.__dataclass_fields__})
        known = {f for f in Assignment.__dataclass_fields__}
        a = Assignment(led=led, **{k: v for k, v in d.items() if k in known})
        a.sanitize()
        return a

    def sanitize(self, control: str = "") -> None:
        """Coerce/clamp values loaded from a (possibly hand-edited) file."""
        def _int(v, lo, hi, default):
            try:
                return max(lo, min(hi, int(v)))
            except (TypeError, ValueError):
                return default
        self.name = str(self.name)
        self.catalog_id = str(self.catalog_id)
        self.page = _int(self.page, 0, 9999, 0)
        self.exec = _int(self.exec, 1, 9999, 201)
        for f in ("press_cmd", "release_cmd", "value_cmd"):
            setattr(self, f, str(getattr(self, f) or ""))
        self.osc_fader = bool(self.osc_fader)
        self.osc_key = bool(self.osc_key)
        led = self.led
        if led.source not in FEEDBACK_SOURCES:
            led.source = "static"
        cmax = 127 if (not control or apc.is_rgb(control)) else 2
        led.off_color = _int(led.off_color, 0, cmax, 0)
        led.on_color = _int(led.on_color, 0, cmax, 0)
        led.off_mode = _int(led.off_mode, 0, 15, apc.MODE_SOLID_100)
        led.on_mode = _int(led.on_mode, 0, 15, apc.MODE_SOLID_100)
        led.use_ma3_color = bool(led.use_ma3_color)
        try:
            led.ma3_dim = max(0.0, min(1.0, float(led.ma3_dim)))
        except (TypeError, ValueError):
            led.ma3_dim = 0.15


# --------------------------------------------------------------------------- #
# Catalogue of MA3 controls (left-hand list in the GUI)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class CatalogItem:
    id: str
    group: str
    name: str
    kind: str                # "button" | "fader" | "any"
    press: str = ""
    release: str = ""
    value: str = ""
    osc_fader: bool = False
    osc_key: bool = False
    feedback: str = "exec_active"
    needs_exec: bool = True
    help: str = ""


CATALOG: list[CatalogItem] = [
    # ---- executor buttons
    CatalogItem("exec.go", "Executor buttons", "Go+", "button", press="Go+ {target}",
                help="Fire next cue of the executor's sequence."),
    CatalogItem("exec.goback", "Executor buttons", "Go-", "button", press="Go- {target}"),
    CatalogItem("exec.toggle", "Executor buttons", "Toggle", "button", press="Toggle {target}"),
    CatalogItem("exec.flash", "Executor buttons", "Flash", "button",
                press="Flash On {target}", release="Flash Off {target}"),
    CatalogItem("exec.temp", "Executor buttons", "Temp", "button",
                press="Temp On {target}", release="Temp Off {target}"),
    CatalogItem("exec.swop", "Executor buttons", "Swap", "button",
                press="Swap On {target}", release="Swap Off {target}"),
    CatalogItem("exec.on", "Executor buttons", "On", "button", press="On {target}"),
    CatalogItem("exec.off", "Executor buttons", "Off", "button", press="Off {target}"),
    CatalogItem("exec.pause", "Executor buttons", "Pause", "button", press="Pause {target}"),
    CatalogItem("exec.top", "Executor buttons", "Top", "button", press="Top {target}"),
    CatalogItem("exec.select", "Executor buttons", "Select", "button",
                press="Select {target}", feedback="press"),
    CatalogItem("exec.key", "Executor buttons", "Physical key (as assigned in MA3)", "button",
                osc_key=True,
                help="Presses the executor key exactly like the console button, "
                     "using whatever function the key has in MA3."),
    # ---- executor faders
    CatalogItem("fader.master", "Executor faders", "Fader Master", "fader",
                value="FaderMaster {target} At {value}", osc_fader=True,
                feedback="exec_fader"),
    CatalogItem("fader.x", "Executor faders", "Fader X-Fade", "fader",
                value="FaderCrossFade {target} At {value}", feedback="exec_fader"),
    CatalogItem("fader.temp", "Executor faders", "Fader Temp", "fader",
                value="FaderTemp {target} At {value}", feedback="exec_fader"),
    CatalogItem("fader.rate", "Executor faders", "Fader Rate", "fader",
                value="FaderRate {target} At {value}", feedback="exec_fader"),
    CatalogItem("fader.speed", "Executor faders", "Fader Speed", "fader",
                value="FaderSpeed {target} At {value}", feedback="exec_fader"),
    CatalogItem("fader.time", "Executor faders", "Fader Time", "fader",
                value="FaderTime {target} At {value}", feedback="exec_fader"),
    # ---- masters
    CatalogItem("master.grand", "Masters", "Grand Master", "fader",
                value='Master 2.1 At {value}', needs_exec=False,
                feedback="static"),
    CatalogItem("master.highlight", "Masters", "Highlight toggle", "button",
                press="Highlight", needs_exec=False, feedback="latch"),
    CatalogItem("master.blind", "Masters", "Blind toggle", "button",
                press="Blind", needs_exec=False, feedback="latch"),
    CatalogItem("master.blackout", "Masters", "Blackout (flash)", "button",
                press='Master 2.1 At 0', release='Master 2.1 At 100',
                needs_exec=False, feedback="press"),
    # ---- pages
    CatalogItem("page.next", "Pages", "Page +", "button", press="Next Page",
                needs_exec=False, feedback="press"),
    CatalogItem("page.prev", "Pages", "Page -", "button", press="Previous Page",
                needs_exec=False, feedback="press"),
    CatalogItem("page.goto", "Pages", "Go to page {page}", "button",
                press="Page {page}", needs_exec=False, feedback="page",
                help="Set the page number in the inspector."),
    # ---- programmer
    CatalogItem("prog.clear", "Programmer", "Clear", "button", press="Clear",
                needs_exec=False, feedback="press"),
    CatalogItem("prog.clearall", "Programmer", "Clear All", "button", press="ClearAll",
                needs_exec=False, feedback="press"),
    CatalogItem("prog.next", "Programmer", "Next", "button", press="Next",
                needs_exec=False, feedback="press"),
    CatalogItem("prog.prev", "Programmer", "Previous", "button", press="Previous",
                needs_exec=False, feedback="press"),
    CatalogItem("prog.all", "Programmer", "All", "button", press="All",
                needs_exec=False, feedback="press"),
    CatalogItem("prog.oops", "Programmer", "Oops", "button", press="Oops",
                needs_exec=False, feedback="press"),
    CatalogItem("prog.dim", "Programmer", "Dimmer (selection)", "fader",
                value="At {value}", needs_exec=False, feedback="static"),
    # ---- global playback
    CatalogItem("glob.goall", "Global", "Go+ (selected exec)", "button", press="Go+",
                needs_exec=False, feedback="press"),
    CatalogItem("glob.offall", "Global", "Off all executors", "button",
                press="Off Page Thru.Thru", needs_exec=False, feedback="press"),
    # ---- custom
    CatalogItem("custom.button", "Custom", "Custom command button", "button",
                press="", needs_exec=False, feedback="press",
                help="Type any MA3 command line for press/release."),
    CatalogItem("custom.fader", "Custom", "Custom fader command", "fader",
                value="", needs_exec=False, feedback="static",
                help="Template with {value} (0-100)."),
]
CATALOG_BY_ID = {c.id: c for c in CATALOG}


def assignment_from_catalog(item: CatalogItem, control: str, page: int = 0,
                            exec_no: int = 201) -> Assignment:
    led = LedConfig.default_for(control)
    led.source = item.feedback
    if item.feedback == "press" and apc.is_rgb(control):
        led.on_color, led.off_color = 3, 1
    name = item.name.replace("{page}", str(page or 1))
    if item.needs_exec:
        name = f"{item.name} {exec_no}" if page == 0 else f"{item.name} {page}.{exec_no}"
    return Assignment(
        name=name, catalog_id=item.id, page=page if item.id != "page.goto" else (page or 1),
        exec=exec_no, press_cmd=item.press, release_cmd=item.release, value_cmd=item.value,
        osc_fader=item.osc_fader, osc_key=item.osc_key, led=led,
    )


# --------------------------------------------------------------------------- #
# Whole mapping
# --------------------------------------------------------------------------- #
@dataclass
class Settings:
    ma3_host: str = "127.0.0.1"
    ma3_port: int = 8000          # MA3 OSC "Port" (MA3 receives here)
    listen_port: int = 8001       # we receive feedback here
    osc_prefix: str = "gma3"
    midi_in: str = ""
    midi_out: str = ""
    fader_deadband: int = 0       # ignore tiny CC jitter
    fader_rate_hz: float = 40.0


@dataclass
class Mapping:
    assignments: dict[str, Assignment] = field(default_factory=dict)
    settings: Settings = field(default_factory=Settings)

    def to_json(self) -> dict:
        return {
            "version": 1,
            "settings": asdict(self.settings),
            "assignments": {k: v.to_json() for k, v in self.assignments.items()},
        }

    @staticmethod
    def from_json(d: dict) -> "Mapping":
        s = Settings(**{k: v for k, v in d.get("settings", {}).items()
                        if k in Settings.__dataclass_fields__})
        a = {}
        for k, v in (d.get("assignments") or {}).items():
            if k in apc.ALL_CONTROLS and isinstance(v, dict):
                a[k] = Assignment.from_json(v)
                a[k].sanitize(k)
        return Mapping(assignments=a, settings=s)

    def save(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_json(), f, indent=2)

    @staticmethod
    def load(path: str) -> "Mapping":
        with open(path, encoding="utf-8") as f:
            return Mapping.from_json(json.load(f))

    def watched_executors(self, current_page: int) -> set[tuple[int, int]]:
        out = set()
        for a in self.assignments.values():
            if a.uses_exec():
                out.add((a.eff_page(current_page), a.exec))
        return out


def demo_mapping() -> Mapping:
    """Sensible starting layout: grid columns = executors 201-208 on page 1."""
    m = Mapping()
    cat = CATALOG_BY_ID
    for col in range(8):
        ex = 201 + col
        # top row: Go+, then toggle, flash; bottom rows free
        m.assignments[apc.pad_id(7, col)] = assignment_from_catalog(cat["exec.go"], apc.pad_id(7, col), 0, ex)
        m.assignments[apc.pad_id(6, col)] = assignment_from_catalog(cat["exec.goback"], apc.pad_id(6, col), 0, ex)
        m.assignments[apc.pad_id(5, col)] = assignment_from_catalog(cat["exec.toggle"], apc.pad_id(5, col), 0, ex)
        m.assignments[apc.pad_id(4, col)] = assignment_from_catalog(cat["exec.flash"], apc.pad_id(4, col), 0, ex)
        m.assignments[f"fader:{col}"] = assignment_from_catalog(cat["fader.master"], f"fader:{col}", 0, ex)
        m.assignments[f"track:{col}"] = assignment_from_catalog(cat["exec.off"], f"track:{col}", 0, ex)
    for i in range(4):
        a = assignment_from_catalog(cat["page.goto"], f"scene:{i}", i + 1)
        a.name = f"Page {i + 1}"
        m.assignments[f"scene:{i}"] = a
    m.assignments["scene:6"] = assignment_from_catalog(cat["page.prev"], "scene:6")
    m.assignments["scene:7"] = assignment_from_catalog(cat["page.next"], "scene:7")
    m.assignments["fader:8"] = assignment_from_catalog(cat["master.grand"], "fader:8")
    # colour the rows differently so the grid reads nicely
    for col in range(8):
        m.assignments[apc.pad_id(7, col)].led.on_color = 21
        m.assignments[apc.pad_id(7, col)].led.off_color = 23
        m.assignments[apc.pad_id(6, col)].led.on_color = 9
        m.assignments[apc.pad_id(6, col)].led.off_color = 11
        m.assignments[apc.pad_id(5, col)].led.on_color = 45
        m.assignments[apc.pad_id(5, col)].led.off_color = 47
        m.assignments[apc.pad_id(5, col)].led.on_mode = 9   # pulse 1/4 while running
        m.assignments[apc.pad_id(4, col)].led.on_color = 3
        m.assignments[apc.pad_id(4, col)].led.off_color = 1
    return m
