# MPC Mapper — Akai APC mini mk2 → grandMA3

Desktop app (Python / PySide6) that maps the controls on an **Akai APC mini mk2**
to **grandMA3**, with live **LED feedback** from the console.

* Drag grandMA3 controls (Go+, Flash, Toggle, Fader Master, Page, Clear, custom
  command lines, …) from a list onto a drawing of the APC.
* Every pad, track button, scene button, Shift and all 9 faders can be mapped.
* Each button gets an **LED rule**: what makes it lit (executor running, fader up,
  current page, pressed, latched) and an *off look* and *on look*, using the
  APC palette (128 colours) with any of the 16 behaviours (solid 10–100 %,
  pulse, blink). Pads can also show the **executor's MA3 appearance colour**
  in true RGB.
* **LED Lab** tab for trying out the LED codes on the hardware: palette,
  behaviours, RGB SysEx, raw hex MIDI.
* Works without the hardware: Shift+click the drawing to simulate presses and
  Shift+drag faders.

## Install & run

```bash
cd MPC_Mapper
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m mpc_mapper        # or ./run.sh
```

Settings (last file, chosen ports) are stored with `QSettings`: the registry
on Windows, `~/.config/MPCMapper` on Linux.

### Windows

Install Python 3.9 or newer from [python.org](https://www.python.org/downloads/)
(tick *Add python.exe to PATH*), then double-click **`run.bat`**, or from a
command prompt:

```bat
cd MPC_Mapper
py -3 -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python -m mpc_mapper
```

* The APC mini mk2 is class compliant; no Akai driver is needed.
* Windows lets only **one program at a time** open a MIDI port. Close other
  software that uses the APC (DAW, MIDI monitor, grandMA3 onPC MIDI input)
  before connecting.
* The first time you click *Connect MA3*, Windows Firewall asks whether Python
  may receive network traffic. Allow it on the network the console is on,
  or the app receives no feedback on the listen port (8001).

### MIDI ports

On Linux the APC shows up as `APC mini mk2 … Contr…` and on Windows as
`APC mini mk2 0` (the second port, `MIDIIN2 (APC mini mk2)`, is the Notes
port). The app picks the *Control* port, which carries pads, buttons, faders
and LEDs, automatically.

## How it talks to grandMA3

**OSC over UDP.** It's the officially supported remote protocol, it has low
latency and it needs no extra hardware.

| Direction | What | How |
|---|---|---|
| App → MA3 | Button actions | `/<prefix>/cmd "Go+ Executor 1.201"` (any command line) |
| App → MA3 | Executor fader master | `/<prefix>/Page1/Fader201 <0-100>` |
| App → MA3 | "Physical key" mode | `/<prefix>/Page1/Key201 1/0` |
| MA3 → App | Executor state, page, colour | Lua plugin `APC_Feedback`, sent with `SendOSC` |

MA3's own OSC output can't be used for feedback. It only fires when something
happens, it gives no state on connect and no colours, and its addresses change
between versions. So a small Lua plugin polls the executors you mapped and
pushes their state:

```
/apc/exec  page exec active fader r g b
/apc/page  page
/apc/hello version          (heartbeat → status bar "MA3 feedback")
```

The app tells the plugin which executors to watch by setting the user variable
`APC_WATCH` (it does this on connect and whenever the mapping changes).

### grandMA3 setup

1. **Menu → In & Out → OSC**: turn on *Enable Input* and *Enable Output*.
2. **Line 1** (commands in): Destination IP = the PC running the app, Port = `8000`,
   Prefix = `gma3`, **Receive = Yes**, **Receive Command = Yes**.
3. **Line 2** (feedback out): Destination IP = the PC running the app, Port = `8001`,
   **Send = Yes** and **Send Command = Yes**, Receive off.
   MA3 uses one port per line for both directions, so you need two lines.
4. Import the plugin: copy `ma3_plugin/APC_Feedback.xml` and `APC_Feedback.lua`
   to the plugin library folder on a USB stick or in the onPC data folder
   (`gma3_library/datapools/plugins`), then import it into the Plugins pool.
   Run it once to start it and again to stop it, or use *MA3 → Start feedback
   plugin* in the app. If your feedback line isn't line 2, edit `OSC_LINE`
   at the top of the Lua file.
5. In the app's toolbar, enter the MA3 IP, port 8000, listen port 8001 and
   prefix `gma3`, then click **Connect MA3**.

## Using the mapper

* **Executor for dropped controls** (bottom left) decides which executor a
  dropped control targets:
  * *By column*: pad column 1 → base, column 2 → base + 1, and so on (faders too).
  * *Fixed number*.
  * *Auto-increment*.

  Page *Current* follows whatever page MA3 is on.
* Click a control to edit it in the inspector. The action is a set of command
  templates with `{target}`, `{page}`, `{exec}` and `{value}`, so you can edit
  any of them into whatever command line you want.
* Drag one control onto another to move it. Ctrl+drag copies it.
  Right-click a control for Simulate and Clear.
* Mappings are saved as JSON (*File → Save*). The last one opens automatically.
  *File → Load demo layout* gives you executors 201–208 laid out as columns
  (Go+, Go−, Toggle, Flash, Off), faders as masters and scene buttons as pages.

## APC mini mk2 LED reference

| Control | Message | Meaning |
|---|---|---|
| Pad 0–63 (0 = bottom-left) | `9n pad colour` | n (channel) = behaviour, velocity = palette colour |
| | ch 0–6 | solid 10, 25, 50, 65, 75, 90, 100 % |
| | ch 7–10 | pulse 1/16, 1/8, 1/4, 1/2 |
| | ch 11–15 | blink 1/24, 1/16, 1/8, 1/4, 1/2 |
| Pad true RGB | `F0 47 7F 4F 24 00 08 start end Rh Rl Gh Gl Bh Bl F7` | static colour only, 8-bit per channel split into msb/lsb |
| Track 1–8 (0x64–0x6B, red) | `90 note v` | v = 0 off, 1 on, 2 blink |
| Scene 1–8 (0x70–0x77, green) | `90 note v` | same |
| Faders | CC 0x30–0x38 | 0x38 = master |
| Intro | `F0 47 7F 4F 60 00 04 00 01 00 00 F7` | the device replies with all fader positions (*Device → Sync fader positions*) |

Note: Shift + Scene 6/7 on the hardware switches the APC to Drum/Note mode, and
then the pads stop working with this app. Shift + Scene 5 goes back to Session mode.

## Files

```
mpc_mapper/apc.py          APC mini mk2 protocol, palette, MIDI I/O
mpc_mapper/ma3.py          OSC client/server for grandMA3
mpc_mapper/model.py        mapping model + catalogue of MA3 controls
mpc_mapper/engine.py       runtime: buttons/faders → MA3, feedback → LEDs
mpc_mapper/gui/            PySide6 GUI (APC drawing, catalogue, inspector, LED lab)
ma3_plugin/                grandMA3 Lua feedback plugin
```
