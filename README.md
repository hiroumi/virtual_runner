# Virtual Boy Stereo Racing

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
The BGM (see "Music selection" below) is likewise original, user-supplied
audio, unrelated to any Virtual Boy/Nintendo music.

## Current status

- **Phase 1 (calibrator): done.** `config.json` holds values confirmed on
  the actual accessory (log: `docs/PHASE1_CALIBRATION_LOG.md`, Japanese).
- **Phase 2, step 1 (static stereo depth test scene): done.**
  `stereo_renderer.py` now implements the real depth→disparity math, and
  `phase2_test_scene.py` is a fixed (non-scrolling) confirmation scene
  built from original placeholder shapes, for verifying the stereo depth
  ordering looks right through the accessory before writing the actual
  driving/scrolling game. Log: `docs/PHASE2_STEREO_TEST_LOG.md`
  (Japanese).
- **Phase 2, the racing game: implemented.** `game.py` is a rear-view,
  segment-based pseudo-3D racer (scrolling curved road, accelerate/brake/
  steer, traffic cars, collision, one ~60-90s course, TIME/SCORE/SPEED
  HUD) rendered through the same `StereoRenderer`. Now also has road
  elevation -- a hill (rise/crest/fall) and a valley mid-course, with
  crest occlusion for traffic/decor behind a hill -- see "Road elevation"
  below. A "SELECT MUSIC" screen (see "Music selection" below) now runs
  before the race, letting the player pick and preview one of three BGM
  tracks, which then loops through the race itself. Log:
  `docs/PHASE2_RACE_LOG.md` (Japanese).

**Picking this back up after a break?** Start at
`docs/NEXT_STEPS.md` (Japanese) — it's a handoff summary of exactly
where things stand, current tuning values, and candidate next tasks.

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
  "fullscreen": true,
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
what was checked. `fullscreen` is set to `true`, matching how the
accessory is actually used.

## Phase 2, step 1: static stereo depth test scene

Before building the actual scrolling racing game, `phase2_test_scene.py`
renders a fixed scene (sky/clouds, mountains, a road with several dash
markers at different distances, a distant car, roadside trees, and the
player's own car — all original placeholder shapes, no imported art) so
the depth-based stereo effect can be checked on the real accessory in
isolation, before any gameplay logic exists.

Run it with:

```
python main.py --stereo-test
```

or directly: `python phase2_test_scene.py`. Same `--test-frames N`
headless smoke-test flag as the calibrator.

### How depth becomes disparity

`stereo_renderer.calculate_disparity(depth, parallax_scale, cfg)` is the
single function every object's stereo offset goes through — nothing
hand-picks a per-object pixel shift:

```
raw = disparity_k * (1/depth - 1/screen_depth)
disparity = clamp(raw * parallax_scale, -max_negative_disparity_px, +max_disparity_px)

left_eye_x  = projected_x + disparity / 2
right_eye_x = projected_x - disparity / 2
```

- `screen_depth` is the world distance at which disparity is exactly
  zero (the convergence plane / "screen depth"). Objects nearer than
  this automatically get positive (inward / crossed) disparity — they
  pop toward the viewer. Objects farther automatically get a small
  negative (outward) disparity — they recede behind the screen. No
  per-category special-casing is needed; it all falls out of each
  object's `depth` value alone.
- `max_disparity_px` / `max_negative_disparity_px` are hard safety
  caps in pixels, applied *after* `parallax_scale`, so turning parallax
  up can never exceed them — this is the "safe upper limit" the eye-strain
  requirement calls for. In the test scene, an object at the cap is
  flagged `(CLAMPED +/-)` in the debug overlay.
- `StereoRenderer.draw_world(depth, draw_fn)` calls `draw_fn` once per
  eye with the correct signed pixel offset already applied; `draw_flat(draw_fn)`
  is the zero-disparity equivalent for HUD/text. Game/simulation code
  calls these — it never computes eye offsets itself, and it never runs
  the simulation twice.
- Vertical disparity is never introduced by this system — only
  `x_offset` exists, matching "左右の垂直視差は原則ゼロ".

Object depths in the test scene (world units, arbitrary but internally
consistent) were chosen to reproduce every category from the spec
without special-casing, purely via the formula above:

| Object | depth | resulting disparity* |
|---|---|---|
| HUD (TIME/SCORE/SPEED) | n/a (drawn flat) | 0px always |
| Sky / clouds, mountains | 300 / 250 | -8.0px (clamped, small outward) |
| Far car | 22 | -1.1px (near zero) |
| Mid roadside trees | 11–13 | +6.7 to +10.2px |
| Road dash markers | 4–40 | +40.0px (nearest) fading to -6.2px (farthest) |
| Near roadside palms | 6 | +29.2px |
| Player's own car | 3 | +40.0px (clamped, largest) |

*at `parallax_scale=1.0`, the calibrated `config.json` defaults.

### Controls (also shown on-screen)

| Key | Action |
|---|---|
| `Up` / `Down` | Increase / decrease live `parallax_scale` (Shift = bigger step) |
| `Z` | Toggle all parallax off (every object snaps to zero disparity, for A/B comparison) |
| `I` | Debug: invert disparity sign for every object (sanity-check convergence direction) |
| `F` | Toggle fullscreen / windowed |
| `S` | Save the current live `parallax_scale` into `config.json` |
| `Esc` | Quit |

### What to check on the real accessory

1. `python main.py --stereo-test` (press `F` for fullscreen).
2. Confirm the HUD strip at the bottom looks flat / on the screen glass
   in both eyes (no doubling or drift).
3. Confirm sky and mountains read as farthest away, the player's own car
   reads as nearest (slightly popping toward you), and the ordering in
   between (far car → mid trees → near palms) feels like a smooth
   progression rather than distinct "layers."
4. Use `Up`/`Down` to find a `parallax_scale` that feels comfortable —
   err low. Press `S` to save it back into `config.json`.
5. Use `Z` to confirm the zero-parallax state genuinely looks flat (a good
   sanity check that disparity is actually being applied, not just
   placebo). Use `I` only as a debug aid if the depth ordering feels
   backwards — it should not be needed once the scene reads correctly.

Only after this reads correctly on the real accessory should the actual
scrolling/driving game logic be built on top of `StereoRenderer`.

## The racing game

```
python main.py --race
```

or directly: `python game.py`. Same `--test-frames N` headless flag.

Rear-view, segment-based scrolling road (the classic "OutRun-style"
technique: a long line of fixed-length segments, each carrying a curve
value; integrating curve twice gives a smoothly bending road with no real
3D geometry), 3 lanes with dashed American-style lane dividers. One
player car, a handful of slow-moving traffic cars to avoid, one course
that takes roughly 60-90s to finish at a believable cruising speed,
TIME/SCORE/SPEED HUD.

Cornering is tuned to be forgiving: every curve on the course can be
taken flat-out with no steering at all without running off the road (see
docs/PHASE2_RACE_LOG.md for the tuning). Steering still matters for lane
position and dodging traffic, just not as a brake substitute.

Top speed is 90 world-units/sec, but the speedometer doesn't show that
number directly: `HUD_MAX_DISPLAY_SPEED` (320) is a separate constant,
and the display is `speed / MAX_SPEED * HUD_MAX_DISPLAY_SPEED`. That
decoupling exists on request -- "keep the dial reading 320, but make the
actual game a bit faster than that (like a real 360)" -- and it means
`MAX_SPEED` can keep climbing later without the speedometer's top number
ever having to change.

Getting to this point took three rounds of the same scaling exercise
(45 -> 60 -> 80 -> 90 world-units/sec), each time scaling accel/brake/
friction and traffic speed by the same ratio to keep the pedal feel
consistent, and scaling every *bend's length* by that ratio too (peak
curve values untouched by this part). That's not arbitrary: how far you
drift through a curve with no steering is proportional to how long you
spend in it (`length / speed`), so scaling a bend's length by the same
factor as top speed keeps that time -- and therefore the safety margin
and the felt duration of the curve -- exactly constant as top speed
climbs.

On top of that, the big sweeping bends (not the one intentionally sharp
chicane) later had their length roughly doubled again and their peak
curve roughly halved -- `peak * length` held constant, so the safety
math doesn't move -- to read as wide, lazy highway curves you hold
flat-out through rather than bends that are merely survivable at speed.
Verified by simulation throughout every round: max unsteered drift
through the whole course has stayed in the 0.28-0.30 range regardless of
how much top speed or curve length changed, and the flat-out clear time
has stayed inside the 60-90s target (currently ~74s with a realistic
accel ramp, vs. a 70s flat-out floor).

### Music selection

Before the race starts, a "SELECT MUSIC" screen (`music.py`) lets the
player choose one of three BGM tracks: `PIXEL BREEZE`, `CRIMSON HIGHWAY`,
`BEYOND THE RED HORIZON` (audio files committed under `bgm/` -- see
"Project layout" below). It shows the title and a left-triangle /
track-name / right-triangle row, drawn as
vector polygons (not a font glyph, to stay consistent with this project's
"everything is a drawn shape, no external art/fonts required for
gameplay" approach) through `StereoRenderer.draw_flat`, so it's
zero-parallax and reuses the exact same calibrated viewports as the race
HUD -- this screen never touches `config.json`.

| Key | Action |
|---|---|
| `Left`/`Right` or `A`/`D` | Change track (wraps at both ends) -- stops the current preview and plays the newly selected track from the beginning, looped, with a short fade-in |
| `Enter` / `Space` | Confirm selection and start the race |
| `Esc` | Quit (no race starts) |

`PIXEL BREEZE` previews automatically the moment the screen appears.
Confirming carries the selected track into the race, where it restarts
from the beginning and loops (`pygame.mixer.music.play(loops=-1)`) for
the whole race -- SDL_mixer's music channel handles the looping natively,
no per-frame Python bookkeeping needed. `music.MusicPlayer` wraps every
`pygame.mixer.music` call in a broad try/except: a missing or unreadable
BGM file never crashes the game, only shows a short error line (a
`_fit_text` helper keeps it from overflowing the narrow viewport even for
an unusually long filename) and leaves the game running with no BGM.

BGM plays at a fixed `BGM_VOLUME = 0.65` (65%, set via
`pygame.mixer.music.set_volume()` right before `play()` so a fade-in
ramps up to that level instead of jumping to it) -- this was missing
until 2026-09-04, so both the preview and the in-race loop had been
playing at full (100%) volume.

### Controls

| Key | Action |
|---|---|
| `Up` / `W` | Accelerate |
| `Down` / `S` | Brake |
| `Left`/`Right` or `A`/`D` | Steer |
| `[` / `]` | Decrease / increase live `parallax_scale` |
| `Z` | Toggle all parallax off (debug A/B) |
| `I` | Debug: invert disparity sign |
| `D` | Toggle FPS / frame-time / depth debug overlay |
| `F` | Toggle fullscreen / windowed |
| `S` | Save current `parallax_scale` to `config.json` |
| `R` | Restart the race (same BGM/settings, current race from the top) |
| `Backspace`, or a gamepad's Select/Back button held ~1s | Reset (see below) |
| `Esc` | Quit |

Driving off the road (`abs(player.x) > 1.0`) caps your top speed and adds
extra friction. Touching a traffic car cuts your speed and starts a
1-second collision cooldown so a single graze can't repeatedly stack
penalties every frame.

### Reset, for switching players at a booth (2026-09-04)

`Restart` (`R`) redoes the current race with the same BGM and settings.
`Reset` is a different, larger operation added for running this as a
Maker Faire exhibit: it tears the whole session down back to the
SELECT MUSIC screen -- track selection back to `PIXEL BREEZE`, race
state/enemies/SFX/BGM all cleared -- so the next visitor can pick a
track and play without anyone needing to quit and relaunch the app.
Available from every screen: SELECT MUSIC, mid-race, after a finish,
after time-up.

`Backspace` resets immediately. A gamepad's Select/Back button must be
held for about a second first (`input_reset.GamepadResetHold`,
`RESET_HOLD_MS`), so a brief accidental press at a booth doesn't wipe
someone's race. Gamepad support is new (there was none before): it uses
pygame's SDL_GameController-backed events
(`CONTROLLER_BUTTON_BACK`/`CONTROLLERBUTTONDOWN`/`UP`), so "Select/Back"
means the same physical button across different Xbox/PS-style pads
instead of a hardware-specific button index -- untested on the actual
exhibit controller yet (see "What to check on the real accessory"
below).

Reset never touches `config.json` or the calibrated viewports, and never
calls `pygame.quit()` / recreates the window -- `game.run()`'s top-level
loop just re-enters the SELECT MUSIC screen with the same window,
renderer, and `MusicPlayer` it already had.

### Sound effects: synthesized engine drone + tire screech

Unlike the BGM (user-supplied original tracks), the engine and tire-
screech sound effects are generated entirely in code (`sfx.py`, using
numpy + `pygame.sndarray`) -- no audio files, consistent with this
project's "everything is generated, no external art/assets required"
approach for its visuals. Asked which approach to use, since these SFX
need continuous pitch/intensity changes tied to gameplay (not a fixed
recording), the answer was code synthesis over file-based SFX.

- **Engine**: an additively-synthesized drone (5 harmonics) pre-rendered
  into `ENGINE_BUCKET_COUNT` (16) discrete pitch buckets from
  `ENGINE_MIN_FREQ` (idle) to `ENGINE_MAX_FREQ` (redline) -- pygame can't
  retune a looping `Sound` in real time, so `EngineSound` picks the
  nearest bucket for the current `speed_frac` each frame and, when the
  bucket changes, crossfades between two alternating mixer channels
  (`ENGINE_CROSSFADE_MS`) rather than hard-cutting. Each bucket's loop
  buffer is snapped to hold an exact whole number of wave cycles so it
  loops with no seam/click. Recomputed right after collision handling in
  `Game.update()`, so a hit's speed drop is audible the same frame, not
  one frame late.
- **Tire screech**: reuses `abs(current_curve) * speed_frac` -- the same
  centrifugal-drift proxy `Game.update()` already computes every frame --
  as a stand-in for lateral tire force (there's no real slip/grip model).
  Above `TIRE_SCREECH_THRESHOLD`, a short noise-based screech clip (high-
  passed noise mixed with a couple of vibrato'd resonant tones) plays on
  its own channel, retriggering back-to-back for as long as the threshold
  holds -- so a multi-second bend gets continuous screech, not one clip
  cut short -- and fades out (`TIRE_SCREECH_FADE_MS`) once cornering
  force drops back down. Gentle bends stay under threshold on purpose;
  only the sharper ones (medium sweeps and up) trigger it.

Both `EngineSound` and `TireScreech` degrade to complete, silent no-ops
if numpy or `pygame.mixer` aren't usable (matching `MusicPlayer`'s
tolerance for a missing BGM file) -- sound effects are polish, never a
crash risk. Both fade out automatically once the race ends (finish or
time-up) and resume on `R` (restart).

**2026-09-04 feedback: "barely audible."** Measured why -- a handful of
summed sine harmonics has RMS well below a single sine's, let alone a
mastered BGM track, so the source waveforms themselves were quiet before
volume even entered into it. Fixed with both a volume increase
(`ENGINE_VOLUME`/`TIRE_SCREECH_VOLUME`: 0.32/0.45 -> 0.8/0.8) and
`_soft_clip`, a tanh-based saturation stage (`ENGINE_SATURATION_DRIVE`/
`TIRE_SCREECH_SATURATION_DRIVE`) that raises RMS by pushing mid-amplitude
samples up toward the peak ceiling without hard-clipping -- verified by
simulation to raise effective loudness roughly 2.7-4.4x while keeping
peaks under 1.0. The debug overlay (`D`) now also shows the engine's
current pitch bucket and whether tire screech is playing, so a future
hardware check can tell "still too quiet" apart from "not triggering at
all."

**2026-09-04, second pass: real-hardware feedback (after Reset checked out
fine) was that the SFX were still barely noticeable.** Both volumes are
now at `1.0` -- the max `pygame.mixer.Sound.set_volume` accepts, no more
headroom on that knob -- and the saturation drives pushed further
(`ENGINE_SATURATION_DRIVE`: 2.5 -> 5.0, `TIRE_SCREECH_SATURATION_DRIVE`:
1.6 -> 2.4, tire kept gentler since noise-based content collapses into
flat static at a much lower drive than a tonal engine drone does).
Simulated effective RMS: engine 0.525 -> 0.808, tire 0.319 -> 0.483
(peaks still safely under 1.0). Expect a noticeably grittier engine tone
now, not just a louder version of the old one -- if that reads as
distortion rather than punch, `ENGINE_SATURATION_DRIVE` is the knob to
back off. If it's *still* too quiet after this, there's no more volume
headroom left to raise -- the next lever would be the waveform itself
(harmonic mix, frequency range) rather than gain. See
docs/PHASE2_RACE_LOG.md for the full numbers.

### How the road gets its stereo effect

Every sprite (trees, traffic cars, the player's own car, HUD) goes
through `StereoRenderer.draw_world` / `draw_flat` exactly like the
Phase 2 test scene — see that section above for the depth->disparity
formula, which is unchanged.

The road itself is different: a single quad's near edge and far edge are
at two different distances from the camera, so they need two different
disparities, not one. Each corner is projected individually through the
new `StereoRenderer.project_x(local_x, depth)` (returns `(left_x,
right_x)` for that one point), so the nearest visible segment gets a
strong inward shift and the segment right at the horizon gets almost
none — a real per-segment gradient, not the whole road shifted as one
flat plane. `road.py` documents the segment/curve model in more detail.

### Selling the turn: background pan + car lean

The segment-projection technique above never rotates the camera -- a
curve only ever shifts the road's `world_x` relative to a screen-locked
vanishing point. Left alone, that reads as "the road appeared crooked"
rather than "we're turning": the background and the player's own car
stay perfectly still on screen while only the road bends.

Two small, purely cosmetic, zero-parallax additions in `game.py` fix
that (the classic fix for this exact problem in segment-based pseudo-3D
racers):

- **Background pan.** Each frame, the sky/mountains layer eases toward a
  target horizontal offset of `-current_segment.curve * speed_fraction *
  BG_SHIFT_SCALE` (both eyes shifted equally -- this is a camera-yaw cue,
  not a depth cue, so it rides on top of the small existing stereo
  disparity rather than replacing it). A right curve pans the background
  left, as if the camera itself were swinging right into the turn; the
  pan eases back to centered the moment the curve straightens out again.
- **Car lean.** The player's car sprite nudges a few pixels *toward* the
  curve direction (`current_segment.curve * speed_fraction *
  CAR_LEAN_SCALE`), so it visually leans into the bend instead of sitting
  dead-center while the world moves around it.

Together they turn "the road is diagonal, the car isn't" into "we're
banking into the curve" -- see `docs/PHASE2_RACE_LOG.md` for the request
that prompted this and how it was verified.

### Road elevation: hills, a crest, and a valley

Added on top of the existing left/right curve system, not a replacement
for it. Each `road.py` `Segment` now also carries an `elevation`
(`world_y`, road-surface height); a short list of `(segment_index,
elevation)` checkpoints in `road.py` is smoothstep-interpolated (via
`apply_elevation()`) into every segment's height, so a hill's rise, crest,
and fall -- or a valley's dip and recovery -- always ease in/out and can
never kink. `MAX_GRADE` is a safety ceiling checked by
`tests/test_road.py` against every authored hill.

`game.py`'s `project()` grew a `world_y`/`cam_y` pair: the screen-Y formula
became `height/2 + scale*(CAMERA_HEIGHT + (cam_y - world_y) *
ELEVATION_Y_SCALE)*height/2`, which reduces to exactly the pre-hill
formula when elevation is 0 everywhere. Road, traffic cars, and roadside
decor all project through this same function with `elevation_at()`
(interpolated the same way as `world_x_at`/`curve_at`), so a car or tree
always sits exactly on the surface of whatever segment it currently
occupies rather than floating or sinking. Left/right eyes always share the
same `sy` -- only the horizontal `project_x` differs per eye, so hills
never introduce vertical parallax.

**Hiding what's over the hill.** `_draw_road()` used to paint far-to-near
(simple painter's algorithm, fine when nothing overlaps on screen). Hills
break that assumption, so it now draws near-to-far and tracks a "crest
watermark" -- the classic technique from Jake Gordon's pseudo-3D racer
tutorials: a segment is skipped once its far edge fails to clear either
its own near edge or the watermark left by a nearer, already-drawn crest.
On flat/curved ground this condition never fires (screen-Y is strictly
monotonic there), so existing rendering is unaffected; it only starts
hiding segments once a real crest exists. Traffic cars and decor reuse the
same watermark array (`Game._sprite_visible`) so an enemy car beyond a
hill crest stays hidden and reappears once the camera crests the hill,
exactly like the road itself.

**Camera and player car.** `Game.cam_elevation` (the camera's road-height
reference) and `Game.player_bob` (a small, separately-damped vertical
nudge for just the player-car sprite) both ease toward their targets
exponentially rather than snapping -- no jump/suspension physics, just
smoothing -- so cresting a hill or bottoming out in a valley never makes
the view or the car visibly jump. The player car's base position stays
pinned near the bottom of the screen; `player_bob` is a small offset on
top of that, sized by local road grade and hard-capped by
`PLAYER_BOB_MAX_PX`.

**Tuning knobs**, all separate from `config.json`'s calibration values
(viewport/eye_gap/swap/flip are never touched by this feature):
`ELEVATION_Y_SCALE` (px per world_y unit on screen), `road.HILL_HEIGHT` /
`VALLEY_DEPTH` (grade strength), `road.HILL_RISE_SEGMENTS` /
`HILL_CREST_SEGMENTS` / `HILL_FALL_SEGMENTS` / `VALLEY_DOWN_SEGMENTS` /
`VALLEY_HOLD_SEGMENTS` / `VALLEY_UP_SEGMENTS` (segments spent transitioning),
`CAMERA_ELEVATION_SMOOTHING` (camera follow speed), and
`PLAYER_BOB_LOOKAHEAD` / `PLAYER_BOB_STRENGTH` / `PLAYER_BOB_MAX_PX` /
`PLAYER_BOB_SMOOTHING` (player-car nudge).

Placed mid-course on purpose, not a full track redesign: the hill's
descent deliberately overlaps the start of a medium curve (both gentle,
never combined with the sharp end-of-course chicane), and the valley sits
in a straight with a clear buffer before that chicane. See
`docs/PHASE2_RACE_LOG.md` for the exact placement, tuning numbers, and
verification (51/51 tests pass, headless full-course run confirmed no
crashes; real-hardware confirmation of 60fps and the crest-occlusion feel
through the accessory's lenses is still outstanding).

**2026-09-03 follow-up feedback** (before real-hardware confirmation had
even happened): "make the hill more pronounced and have it show up
sooner." `HILL_START` moved from 1095 to 350 (much earlier in the
course), `HILL_HEIGHT`/`VALLEY_DEPTH` grew (14→20 / 8→11), and
`ELEVATION_Y_SCALE` grew (2.4→3.6, a pure rendering-scale knob that
doesn't touch world-unit geometry). `MAX_GRADE`'s own comment was wrong
about which value it was checking -- `apply_elevation`'s smoothstep peaks
at 1.5x its transition's *average* grade, not the average itself -- so it
grew from 0.09 to 0.12 alongside a corrected comment, not as a safety
loosening. Verified with the same drift simulation as the curve rework
below: course length/pace unaffected, 51/51 tests still pass.

### Winding curves instead of long lazy sweeps (2026-09-03 feedback)

Also from that same round of feedback: the big sweeping bends (peak
0.09-0.14, 190-290 segments each) were mathematically already one full
self-cancelling sine cycle (see `_add_bend`'s docstring) -- a right-then-
left "S" in principle -- but so gradual over that much distance that
driving through one read as a long diagonal straight rather than a real
curve. Every one of them except the chicane (already short and snappy,
not the complaint) got replaced in `TRACK_EVENTS` with a chain of 3-4
shorter `_add_bend` calls alternating sign, e.g. `0.09/210` became
`[0.09/70, -0.09/70, 0.09/70]` -- same total segment count, so every
later straight/bend (and the hill/valley placement above, which is
relative to those same segment indices) starts at exactly the index it
always did. Each lobe keeps the original peak, just over a shorter span,
so its own length*peak product -- and therefore its own contribution to
unsteered drift -- is *smaller* than the single long bend it replaces:
if anything more conservative on the flat-out safety margin, not less.
Verified directly: a flat-out, zero-steering simulation through the new
curves still finishes in ~74s (unchanged) with max lateral drift 0.299
(essentially identical to the pre-rework figure of 0.28-0.30). See
`docs/PHASE2_RACE_LOG.md` for the full before/after and verification.

### Smooth cornering: interpolating between segments

Segments are 3 world units long, and during a curve consecutive
segments' `world_x` can differ by a large fraction of the road's width.
Early on, the camera's lateral reference (`_road_center_x`) and the
"current curve" used for centrifugal force / background pan / car lean
all sampled that value at the coarse per-segment resolution -- fine on a
straight (where it never changes between segments), but on a curve it
meant the whole view stayed still for a few frames and then hopped by a
large step the instant the camera crossed into the next segment,
reported as choppy/janky cornering.

`road.py` now exposes `world_x_at()` / `curve_at()`, which linearly
interpolate between the two nearest segments instead of snapping to one.
Every per-frame lookup of a moving thing's lateral position (the camera,
traffic cars) goes through these; static roadside decor doesn't need to,
since its world_z never changes frame to frame. `tests/test_road.py`
has a regression test asserting the interpolated value can't jump more
than a small bound over a small step, specifically in one of the sharper
curve regions.

### What to check on the real accessory

Same idea as the Phase 2 test scene checklist above, but now while
actually driving: confirm the road still reads as continuously receding
into the distance while turning, the player's car stays comfortably "in
front of the glass," and traffic cars pop toward you convincingly as
they get closer. Use `[`/`]` to retune `parallax_scale` for comfort
during actual play (it may want to differ from the static test scene's
value) and `S` to save it.

Also confirm Reset with the actual exhibit hardware: whether the
gamepad's Select/Back button is recognized at all (an unrecognized pad
just means gamepad Reset silently doesn't fire -- `Backspace` still
works as a fallback either way), whether holding it for ~1s feels right
for the booth, and whether the brief "RESET" flash reads clearly through
both lenses.

## Project layout

```
main.py                 entry point: calibrator by default, or
                        --stereo-test for the Phase 2 depth test scene
calibration.py           Phase 1: the calibrator itself
stereo_renderer.py        shared stereo drawing layer: depth -> disparity
                        math (calculate_disparity) and the StereoRenderer
                        class that composites both eyes into the
                        calibrated viewports. Racing-game logic will
                        render through this; it has no game code itself.
phase2_test_scene.py      Phase 2 step 1: static depth/disparity
                        confirmation scene (no scrolling/game logic)
road.py                  segment-based road/track model (curve, world_x,
                        world_z) shared by game.py; no drawing in here
game.py                  Phase 2 step 2: the actual racing game (input,
                        physics, traffic/collision, HUD, road rendering)
music.py                 pre-race "SELECT MUSIC" screen + MusicPlayer
                        (pygame.mixer.music wrapper: track selection,
                        preview/loop playback, safe load-error handling)
bgm/                     the three BGM tracks music.py loads (mp3,
                        committed -- original, user-supplied audio)
sfx.py                   synthesized engine drone + tire screech sound
                        effects (numpy + pygame.sndarray; no audio files)
input_reset.py            shared Reset input plumbing (Select/Back
                        gamepad hold-to-reset tracking, safe gamepad
                        open) used by both music.py and game.py
config.py                Config/Rect dataclasses, JSON load/save, clamping
config.json               real-hardware-verified calibration + disparity
                        safety settings (committed)
config.example.json       original placeholder defaults (committed)
requirements.txt          runtime dependencies (pygame, numpy)
requirements-dev.txt       + pytest, for running tests/
tests/                    automated tests (headless, SDL dummy driver)
assets/                   placeholder for future art (empty for now)
docs/                     working log + NEXT_STEPS.md handoff (Japanese)
```

## Tests

```
pip install -r requirements-dev.txt
pytest
```

Tests run headlessly (`SDL_VIDEODRIVER=dummy`) and cover: config
load/save/round-trip, fallback-to-defaults on missing/corrupt/invalid
`config.json`, viewport clamping/recovery, every calibrator key binding,
the depth→disparity formula (zero at `screen_depth`, monotonic, safety
caps never exceeded even at extreme inputs), every Phase 2 test-scene key
binding, the track/curve model (reasonable length and lateral range, no
runaway curve), the elevation model (smooth/eased transitions, grade never
exceeds `MAX_GRADE`, hill/valley reach their authored extremes), the
racing game's rules (accelerate/coast/off-road speed caps, collision
penalty + cooldown, finish/time-up transitions, restart, every key
binding), hill-specific behavior (camera elevation eases rather than
snaps, player-car bob stays within its cap, an object behind a hill crest
is hidden until the camera crests it), the music-select screen (track
order, next/prev wraparound in both directions -- via MusicPlayer directly
and via the real scripted-keypress event loop -- confirm/quit, a missing
BGM file not raising and producing a short, viewport-width-safe error
message, and, when the `bgm/` assets are present, that all three real
tracks actually load and play), and the synthesized sound effects
(engine loop buffers hold an exact whole number of cycles so they loop
click-free, engine pitch bucket climbs monotonically with speed and
crossfades between alternating channels, tire screech triggers above its
threshold and not below, doesn't retrigger while already playing, and
fades out on both a threshold drop and an explicit stop, both SFX degrade
to silent no-ops if numpy or the mixer are unavailable, and both actually
stop on race-finish and resume on restart in a full Game integration).
