# Virtual Boy Stereo Racing (Phase 1: Calibrator)

Windows 11 desktop prototype for a stereoscopic pseudo-3D racing game,
displayed through Nintendo's **Virtual Boy for Nintendo Switch** accessory
with a 7", 1024×600 HDMI panel wired to a PC instead of a Switch.

**This is not a reproduction of the original Virtual Boy hardware.** There
is no red LED array and no vibrating mirror here. This project draws
ordinary left-eye/right-eye images on a normal HDMI LCD; the accessory's
lenses and red filter are what the player looks through.

No original Nintendo/Virtual Boy names, logos, characters, vehicles,
artwork, or music are used or planned. All visuals are original geometric
placeholders (rectangles, lines, circles) until real original art exists.

## Current status: Phase 1 only

Only the **display calibrator** is implemented. The racing game itself
(Phase 2) is intentionally **not started** — `stereo_renderer.py` is a
placeholder describing the planned shared rendering layer, and `main.py`
currently just launches the calibrator.

**Update (2026-09-02): real-hardware calibration complete.** `config.json`
now holds values confirmed on the actual accessory (see
`docs/PHASE1_CALIBRATION_LOG.md` for the log, in Japanese). Phase 2 can
begin from here.

## Why a calibrator comes first

On the real hardware, the 1024×600 panel is **not** simply split into two
512×600 halves. Looking through the accessory, you only see two small
areas of the screen near its center — their exact position, size, and
spacing depend on the physical lens/panel alignment and must be measured
on the real unit. The values shipped in this repo are a **placeholder
guess** (two 280×200 boxes, left-of-center and right-of-center) — not a
measurement — and must be replaced by real values found by running the
calibrator while looking through the accessory.

## Setup (Windows 11)

```
py -3 -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

## Running the calibrator

```
python main.py
```

or directly:

```
python calibration.py
```

Launches in windowed mode at 1024×600 by default (press `F` for
fullscreen — fullscreen is what you want when actually looking through
the accessory). Settings load from `config.json` if present, otherwise
safe placeholder defaults are used.

Automated / no-input smoke test (renders N frames and exits, used for
CI / headless verification, no window interaction required):

```
python calibration.py --test-frames 60
```

## Controls

All of these are also listed on-screen while the calibrator is running.

| Key | Action |
|---|---|
| `1` / `2` / `3` | Select LEFT / RIGHT / BOTH (global move) viewport |
| `4` | Select EYE GAP (arrow keys move left/right apart or together, symmetrically) |
| `5` | Select PARALLAX TEST DEPTH (left/right arrows push the Parallax-mode test shape back/forward) |
| Arrow keys | Move (or resize, see `Tab`) the current selection |
| Shift + arrows | Same, in steps of 10px instead of 1px |
| `Tab` | Switch the arrow keys between MOVE and SIZE (width/height) |
| `+` / `-` | Adjust content scale (display magnification of the test pattern) |
| `[` / `]` | Cycle test pattern: Grid → Alignment → Depth → Parallax → Crop → Color |
| `P` | Toggle parallax test on/off (off = both eyes identical, for direct comparison) |
| `X` | Swap left/right images |
| `H` / `V` | Flip the selected viewport(s) horizontally / vertically |
| `F` | Toggle fullscreen / windowed |
| `S` | Save current values to `config.json` |
| `R`, `R` (twice within 3s) | Reset in-memory values to defaults (not saved until you press `S`) |
| `Esc` | Quit (remember to press `S` first if you want to keep changes) |

### Test patterns

- **Grid** — identical grid + circle in both eyes; use to check aspect
  ratio and lens distortion (the circle should look round).
- **Alignment** — just a center cross and corner brackets, minimal
  clutter, for judging left/right fusion.
- **Depth** — three squares (far/mid/near) each with a different amount
  of parallax, previewing the near-to-far depth range the future game
  will use.
- **Parallax** — one shape whose depth you control directly with target
  `5` + left/right arrows, to find a comfortable parallax range.
- **Crop** — edge ruler ticks and corner markers, to check whether the
  lens vignettes/crops the edges of the viewport.
- **Color** — black, 4 steps of red, 3 steps of gray, and white side by
  side, to judge visibility through the accessory's red filter.

In Depth and Parallax modes, the on-screen HUD and all text labels are
always drawn at zero parallax (identical position in both eyes) — only
the test shapes themselves are shifted, per spec.

## `config.json`

Written by pressing `S` in the calibrator; read on startup. If the file
is missing, unreadable, or contains invalid values, the calibrator falls
back to safe built-in defaults automatically (it will not crash on a bad
file).

`config.json` is normally machine/hardware-specific. For this project it
is committed anyway, because it now holds the values verified on the
actual target accessory (see `docs/PHASE1_CALIBRATION_LOG.md`) and is
meant to be the working baseline for Phase 2 — not a per-developer local
file. If you calibrate a different physical unit, expect to get different
numbers and commit over these once re-verified.
`config.example.json` (committed) documents the original placeholder
defaults the calibrator falls back to when no `config.json` exists.

Current committed values (real-hardware-verified, 2026-09-02):

```json
{
  "output_width": 1024,
  "output_height": 600,
  "fullscreen": false,
  "left_viewport": { "x": 152, "y": 175, "width": 280, "height": 282 },
  "right_viewport": { "x": 532, "y": 171, "width": 280, "height": 282 },
  "swap_eyes": false,
  "flip_left_h": false,
  "flip_left_v": false,
  "flip_right_h": false,
  "flip_right_v": false,
  "parallax_scale": 1.0,
  "content_scale": 1.0
}
```

`left_viewport` / `right_viewport` are the only numbers Phase 2 will
actually need to consume — everything else in the calibrator UI (eye
gap, global move, per-eye offset) is just a convenient way to *edit*
these two rectangles, not a separately persisted value.

A viewport can never be dragged fully off-screen: `Rect.clamp()` always
keeps at least 20px of it on-screen and enforces a 20px minimum size, so
a runaway adjustment is always recoverable without hand-editing the JSON.

## Assumptions made (please verify on real hardware)

Recorded here per the project instructions, since these were not
measurable without the physical accessory:

- Default viewport size (280×200) and position (centered left-of-center
  / right-of-center) are a rough placeholder guess, not a measurement of
  the real accessory's optical window.
- Both eyes default to the same viewport size; the code supports
  different left/right sizes (nothing enforces symmetry), but the
  calibrator's `BOTH` selection assumes you generally want to move/resize
  them together.
- Max test-pattern parallax was capped at 40px as a sensible-looking
  default for a 1024-wide screen; this is unrelated to
  `parallax_scale`, which the future game will use for the *actual*
  gameplay parallax range, and its own safe limits should be re-checked
  during Phase 2.
- Font rendering uses whatever monospace font pygame's `SysFont` finds
  on the system (`consolas`/`courier new` preferred). Not bundling a
  font file, since the calibrator's text is a dev/debug aid, not
  in-game UI.

## What to verify on the real accessory before Phase 2

1. Put the panel in the accessory, run `python main.py`, press `F` for
   fullscreen.
2. Use `1`/`2`/`3` + arrows to get both eye viewports roughly centered in
   what you see through each lens.
3. Switch to **Crop** mode (`]`) and nudge size/position until the ruler
   ticks near each edge are all visible (no edge clipped by the lens).
4. Switch to **Grid** mode and confirm the circle looks round in both
   eyes (fix width/height independently if it's egg-shaped — that's lens
   or aspect distortion, not a bug in the calibrator).
5. Switch to **Alignment** mode and confirm the two crosses fuse into one
   without excessive eye strain; use `H`/`V` flips and `X` swap if the
   image appears mirrored or swapped.
6. Switch to **Color** mode and note which reds/grays actually read as
   distinct colors through the filter — this should inform the game's
   final color palette in Phase 2.
7. Switch to **Depth**/**Parallax** modes and find a `parallax_scale`
   that feels comfortable (start low; the spec calls for conservative
   defaults and no aggressive negative/pop-out parallax).
8. Press `S` to save. Confirm by quitting (`Esc`) and relaunching that
   the same layout comes back automatically.

Only after this is done and `config.json` reflects real, verified
numbers should Phase 2 (the actual racing game) begin.

**Status: done.** See `docs/PHASE1_CALIBRATION_LOG.md` for the record of
what was checked. One thing worth a second look before Phase 2: the
saved `fullscreen` value is currently `false` (windowed) — confirm
whether that's intentional for actual play through the accessory, or
whether it should be `true`.

## Project layout

```
main.py              entry point (currently just launches the calibrator)
calibration.py        Phase 1: the calibrator itself
config.py             Config/Rect dataclasses, JSON load/save, clamping
stereo_renderer.py     Phase 2 placeholder (not implemented; documents the
                       planned shared stereo-rendering API)
config.json            real-hardware-verified calibration (committed)
config.example.json     original placeholder defaults (committed)
requirements.txt        runtime dependency (pygame)
requirements-dev.txt     + pytest, for running tests/
tests/                  automated tests (headless, SDL dummy driver)
assets/                 placeholder for future art (empty for now)
docs/                   working log (Japanese)
```

## Tests

```
pip install -r requirements-dev.txt
pytest
```

Tests run headlessly (`SDL_VIDEODRIVER=dummy`) and cover: config
load/save/round-trip, fallback-to-defaults on missing/corrupt/invalid
`config.json`, viewport clamping/recovery, and a full pass over every key
binding to confirm none of them raises.
