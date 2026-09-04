"""Phase 2: the actual pseudo-3D racing game.

Rear-view, segment-based scrolling road (see road.py), one player car,
a handful of slow-moving traffic cars to avoid, one ~60-90s course,
and a TIME/SCORE/SPEED HUD. Everything red/black, original placeholder
shapes only -- no imported art.

Simulation runs exactly once per frame (see Game.update). Only drawing
branches per eye, through StereoRenderer -- see stereo_renderer.py and
docs/PHASE2_STEREO_TEST_LOG.md for the depth->disparity design this
reuses unchanged. Each road segment's near and far edge are at different
distances from the camera, so (unlike the single-depth sprites) its four
corners are projected individually through StereoRenderer.project_x --
that's the "per road segment" disparity the project spec calls for,
not one shift for the whole road.
"""
from __future__ import annotations

import argparse
import math
import random
from pathlib import Path

import pygame

from config import load_config, save_config
from gamepad import (
    GamepadResetHold,
    get_primary_controller,
    open_connected_controllers,
    open_controller_from_event,
    read_accel,
    read_brake,
    read_steer,
)
from road import (
    DRAW_DISTANCE,
    ROAD_WIDTH,
    SEGMENT_LENGTH,
    build_track,
    curve_at,
    elevation_at,
    track_length,
    world_x_at,
)
from music import MusicPlayer, MusicSelectScreen
from sfx import (
    ENGINE_BUCKET_COUNT,
    ENGINE_PRESET_ORDER,
    TIRE_SCREECH_PRESET_ORDER,
    EngineSound,
    TireScreech,
)
from stereo_renderer import StereoRenderer

BLACK = (0, 0, 0)
MOUNTAIN_COLOR = (100, 15, 15)
CLOUD_COLOR = (55, 0, 0)
GRASS_DARK = (18, 4, 4)
GRASS_LIGHT = (26, 6, 6)
RUMBLE_DARK = (120, 15, 15)
RUMBLE_LIGHT = (190, 30, 30)
ROAD_DARK = (40, 9, 9)
ROAD_LIGHT = (52, 12, 12)
LANE_LINE_COLOR = (225, 165, 165)
TREE_COLOR = (150, 20, 20)
TRAFFIC_COLOR = (170, 25, 25)
PLAYER_COLOR = (255, 45, 45)
HUD_BORDER = (200, 40, 40)
HUD_TEXT = (255, 90, 90)
DEBUG_TEXT = (190, 190, 190)
MESSAGE_COLOR = (255, 210, 110)

CAMERA_HEIGHT = 6.0
FOV_DEG = 110.0
CAMERA_DEPTH = 1.0 / math.tan(math.radians(FOV_DEG / 2))

RACE_TIME = 90.0
PLAYER_CAR_DEPTH = 3.0  # matches the Phase 2 test scene's tuned value

# Maker Faire "next visitor" reset: Backspace (keyboard) or an ~1s held
# Select/Back (gamepad, see gamepad.GamepadResetHold) tears the
# current session down and returns to SELECT MUSIC without quitting
# pygame or touching config.json -- see Game._trigger_reset / run()'s
# docstring below for the full flow.
RESET_FLASH_MS = 150  # how long the "RESET" flat-text flash is held on screen

PRESET_FLASH_MS = 1200  # how long an engine/tire-screech preset name flash stays on screen

# The speedometer always reads HUD_MAX_DISPLAY_SPEED at MAX_SPEED,
# regardless of what MAX_SPEED actually is -- this lets the underlying
# sim's pace be tuned (i.e. actually made faster) independently of what
# number the dial shows at the top end. Requested as: keep the display
# pinned at "320" while making the game itself feel like a genuine ~360.
HUD_MAX_DISPLAY_SPEED = 320.0
MAX_SPEED = 90.0
OFFROAD_MAX_SPEED = 40.0
ACCEL = 49.5
BRAKE = 139.5
FRICTION = 23.6
OFFROAD_FRICTION = 90.0
STEER_RATE = 2.0
# Kept low enough that even the sharpest bend on the course can be taken
# flat out with no steering input at all without running off the road --
# an arcade racer should let you blast through curves, not force braking
# for every turn (see docs/PHASE2_RACE_LOG.md for the tuning math).
CENTRIFUGAL = 0.8
PLAYER_X_LIMIT = 2.2

# Background parallax + car lean: without these, a curve only bends the
# road while the horizon/background and the player's own car stay put on
# screen, which reads as "the road appeared crooked" rather than "we are
# turning." Panning the background opposite the curve (as if the camera
# itself were yawing into the turn) and nudging the car sprite toward the
# curve direction gives that sense of drifting into the bend instead.
BG_SHIFT_SCALE = 110.0    # px of background pan at full curve + full speed
BG_SHIFT_SMOOTHING = 6.0  # higher = pan reacts to curve changes faster
CAR_LEAN_SCALE = 11.0     # px the player car sprite nudges toward the turn

# -- Player car sprites (2026-09-05) -----------------------------------------
# 5-pose placeholder pixel art (see assets/cars/player/) replacing the flat
# rectangle draw_car() drew for the player specifically -- traffic cars are
# explicitly out of scope for this pass and still use draw_car(). Canvas
# size and anchor point are shared by all 5 PNGs (see
# generate_placeholder_sprites.py's CANVAS_SIZE/ANCHOR, mirrored here rather
# than imported since that script is a one-off asset-authoring tool, not a
# runtime dependency) -- ANCHOR is where each sprite's "ground contact,
# horizontal center" point sits within its own canvas, so blitting every
# sprite with that same offset from (cx, cy) is what keeps the tire contact
# point and body centerline from jumping when the sprite changes.
#
# 2026-09-05: switched from the 64x48 placeholder art to production art
# extracted from a user-supplied sprite sheet (see
# assets/cars/player/build_from_spritesheet.py), which needed a wider
# 88x48 canvas -- update this pair together with that script's
# FINAL_CANVAS_SIZE if the sheet is ever rebuilt at a different size.
PLAYER_ASSETS_DIR = Path(__file__).resolve().parent / "assets" / "cars" / "player"
PLAYER_SPRITE_KEYS = ("hard_left", "left", "straight", "right", "hard_right")
PLAYER_SPRITE_CANVAS_SIZE = (88, 48)
PLAYER_SPRITE_ANCHOR = (44, 48)  # bottom-center

# The single, unified -1..1 "how hard is the player steering right now"
# value (keyboard + gamepad combined -- see update()) that picks a sprite.
# Boundaries requested as: -1..-0.55 hard_left, -0.55..-0.15 left,
# -0.15..+0.15 straight, +0.15..+0.55 right, +0.55..+1 hard_right.
PLAYER_SPRITE_THRESHOLDS = (-0.55, -0.15, 0.15, 0.55)
# Extra margin required to cross back over a boundary once already on its
# far side, so a value sitting right at a boundary can't flicker the
# sprite every frame -- combined with PLAYER_VISUAL_STEER_SMOOTHING below
# (which itself already keeps the value from jumping instantly), this is
# the "hysteresis" the spec asks for in addition to the smoothing.
PLAYER_SPRITE_HYSTERESIS = 0.05
# How fast the *visual* steering value chases the actual (instantaneous)
# combined input -- deliberately separate from STEER_RATE/the physics
# steer value: this only ever affects which of the 5 sprites is drawn,
# never player.x or collision, so sprite switching can never itself change
# where the car actually is. Keyboard/D-pad's digital +-1 "snap" is what
# this smooths into a gradual sprite progression, per the spec ("押した
# 瞬間に最大角度へ切り替えず、短時間で段階的に変化させる").
PLAYER_VISUAL_STEER_SMOOTHING = 6.0  # 1/s


_player_sprites_cache: dict = {"loaded": False, "sprites": {}}


def _load_player_sprites() -> dict[str, pygame.Surface]:
    """Loads+caches the 5 PNGs once per process (not once per Game --
    Game gets re-constructed on every Restart-via-Reset, and re-decoding
    5 PNGs from disk each time would be wasteful). Returns {} (not a
    partial dict) if any file is missing/unreadable, so a broken asset
    can't leave some poses using placeholder art and others not --
    _draw_player_car falls back to the original draw_car() rectangle
    for *all* poses in that case, matching this project's established
    "missing asset degrades gracefully, never crashes" philosophy (see
    music.py/sfx.py)."""
    if _player_sprites_cache["loaded"]:
        return _player_sprites_cache["sprites"]
    sprites: dict[str, pygame.Surface] = {}
    try:
        for key in PLAYER_SPRITE_KEYS:
            path = PLAYER_ASSETS_DIR / f"player_{key}.png"
            surf = pygame.image.load(str(path)).convert_alpha()
            if surf.get_size() != PLAYER_SPRITE_CANVAS_SIZE:
                # A mismatched canvas would break the shared-anchor
                # guarantee every other sprite relies on -- refuse the
                # whole set rather than risk the car jumping on switch.
                sprites = {}
                break
            sprites[key] = surf
    except (pygame.error, FileNotFoundError, OSError):
        sprites = {}
    _player_sprites_cache["sprites"] = sprites
    _player_sprites_cache["loaded"] = True
    return sprites


# -- Road elevation (hills) -------------------------------------------------
# Vertical companion to CAMERA_HEIGHT/project() below: each segment now
# additionally carries an elevation (world_y, see road.py), and every
# drawn thing (road, traffic, decor, camera) is projected through the same
# formula, so a hill is real geometry, not a screen-space pan. All of these
# are separate from config.json's calibration values on purpose -- they're
# gameplay/visual tuning, not display calibration -- see project().
ELEVATION_Y_SCALE = 3.6        # px-on-screen per world_y unit of camera/road
                                # height difference -- "起伏による画面Y方向の倍率"
                                # (raised from 2.4 on 2026-09-03 feedback:
                                # "make the hill's ups/downs more
                                # pronounced" -- a pure rendering-scale
                                # knob, doesn't touch world-unit geometry
                                # or MAX_GRADE safety margins at all)
CAMERA_ELEVATION_SMOOTHING = 6.0  # how fast cam_elevation chases the
                                   # player's actual road elevation (1/s)
PLAYER_BOB_LOOKAHEAD = 6.0      # world units ahead sampled to sense local
                                 # grade for the player-car nudge
PLAYER_BOB_STRENGTH = 90.0      # px of player-car vertical nudge per unit
                                 # of local grade (dy/dz) -- bob "strength"
PLAYER_BOB_MAX_PX = 10.0        # hard cap so cresting/valleys never make
                                 # the player car visibly jump
PLAYER_BOB_SMOOTHING = 5.0      # how fast the player-car nudge chases its
                                 # target grade (1/s)

LANE_COUNT = 3  # American-style multi-lane road
# Fractional offsets (of ROAD_WIDTH) of the dashed lines between lanes,
# e.g. [-1/3, 1/3] for 3 lanes. Traffic lane centers use the same spacing
# (see _build_traffic) so cars visually sit in the middle of a lane.
LANE_DIVIDER_FRACS = [(2 * i - LANE_COUNT) / LANE_COUNT for i in range(1, LANE_COUNT)]
LANE_LINE_HALF_WIDTH = 0.35  # world units

TRAFFIC_SPEED = 28.0
COLLISION_Z_RANGE = SEGMENT_LENGTH * 2.5
COLLISION_X_RANGE = 0.7
COLLISION_PENALTY = 0.5
COLLISION_COOLDOWN = 1.0

SCORE_PER_SECOND_PER_SPEED = 2.0


def _font(size: int) -> pygame.font.Font:
    return pygame.font.SysFont("consolas,couriernew,monospace", size)


def project(
    world_x: float,
    world_y: float,
    world_z: float,
    cam_x: float,
    cam_y: float,
    cam_z: float,
    width: float,
    height: float,
):
    """world_y/cam_y are elevation (road.py's Segment.elevation / the
    camera's smoothed road-height reference, Game.cam_elevation) -- both
    default to 0 on flat ground, which reduces the sy formula below to
    exactly what it was before hills existed. Only sy depends on them;
    left/right eyes always share this same sy (see stereo_renderer.py --
    vertical parallax is never a thing), only the horizontal x differs per
    eye via StereoRenderer.project_x downstream."""
    # Floor of one segment length, not near-zero: right at the camera the
    # scale would otherwise blow up to an extreme value, which is
    # invisible for the wide grass/road quads (they just fill the bottom
    # of the frame either way) but produced a distracting stray sliver
    # for the thin lane-divider lines.
    trans_z = max(world_z - cam_z, SEGMENT_LENGTH)
    scale = CAMERA_DEPTH / trans_z
    sx = width / 2 + scale * (world_x - cam_x) * width / 2
    sy = height / 2 + scale * (CAMERA_HEIGHT + (cam_y - world_y) * ELEVATION_Y_SCALE) * height / 2
    sw = scale * ROAD_WIDTH * width / 2
    return sx, sy, sw, trans_z


def draw_tree(surf: pygame.Surface, cx: float, base_y: float, scale: float, color) -> None:
    trunk_h = 22 * scale
    top = (cx, base_y - trunk_h)
    pygame.draw.line(surf, color, (cx, base_y), top, max(1, int(2 * scale)))
    for angle_deg in (-135, -105, -75, -45):
        rad = math.radians(angle_deg)
        length = 16 * scale
        end = (top[0] + length * math.cos(rad), top[1] + length * math.sin(rad))
        pygame.draw.line(surf, color, top, end, max(1, int(2 * scale)))


def draw_car(surf: pygame.Surface, cx: float, base_y: float, scale: float, color) -> None:
    body_w, body_h = 44 * scale, 16 * scale
    cab_w, cab_h = 28 * scale, 11 * scale
    pygame.draw.rect(surf, color, (cx - body_w / 2, base_y - body_h, body_w, body_h))
    pygame.draw.rect(surf, color, (cx - cab_w / 2, base_y - body_h - cab_h + 2, cab_w, cab_h))


class TrafficCar:
    def __init__(self, z: float, x: float, speed: float):
        self.z = z
        self.x = x
        self.speed = speed


class Player:
    def __init__(self):
        self.x = 0.0
        self.z = 0.0
        self.speed = 0.0


def _make_display(cfg) -> pygame.Surface:
    flags = pygame.FULLSCREEN if cfg.fullscreen else 0
    return pygame.display.set_mode((cfg.output_width, cfg.output_height), flags)


class Game:
    def __init__(self, cfg, screen=None, renderer=None, music: MusicPlayer | None = None):
        # screen/renderer/music are optional so game.run() can reuse the
        # ones the music-select screen already set up (same window, same
        # StereoRenderer/parallax state, same MusicPlayer -- no flicker or
        # re-init) -- existing direct callers (tests included) that just
        # do Game(cfg) still get a freshly created display/renderer and no
        # BGM, exactly as before this feature existed.
        self.cfg = cfg
        self.segments = build_track()
        self.track_length = track_length(self.segments)
        self.screen = screen if screen is not None else _make_display(cfg)
        self.renderer = renderer if renderer is not None else StereoRenderer(self.screen, cfg)
        self.music = music
        if self.music is not None:
            # Confirmed selection -> stop the (looped) preview and restart
            # the same track from the beginning, looping, for the race.
            self.music.start_looping()
        self.font_hud = _font(13)
        self.font_debug = _font(12)
        self.font_message = _font(18)
        self.clock = pygame.time.Clock()

        self.player = Player()
        self.traffic = self._build_traffic()
        self.decor = self._build_decor()

        self.time_left = RACE_TIME
        self.score = 0.0
        self.finished = False
        self.time_up = False
        self.collision_cooldown = 0.0
        self.show_debug = False
        self.last_frame_ms = 0.0
        self.bg_offset = 0.0  # smoothed background-parallax pan, see update()
        self.current_curve = 0.0
        self.cam_elevation = 0.0  # smoothed camera road-height reference
        self.player_bob = 0.0     # smoothed player-car vertical nudge (px)
        self.player_visual_steer = 0.0  # smoothed sprite-selection input, see update()
        self._player_sprite_index = PLAYER_SPRITE_KEYS.index("straight")
        self._player_sprites = _load_player_sprites()
        self._road_base_idx = 0
        self._road_clip_before_n: list[float] = []  # crest occlusion, see _draw_road

        # Synthesized, not file-based -- see sfx.py. Always created (no
        # music-select-style "choice" for SFX); both degrade to silent
        # no-ops on their own if numpy/pygame.mixer aren't usable.
        self.engine_sound = EngineSound()
        self.tire_screech = TireScreech()
        # Brief on-screen name flash when `E`/`T` cycles the engine/tire
        # screech preset (see _cycle_preset) -- not gated behind
        # self.show_debug, since auditioning presets is meant to be usable
        # even without the full debug overlay on.
        self._preset_flash_name: str | None = None
        self._preset_flash_until_ms = 0

        # run()'s exit reason ("quit" or "reset") -- see _trigger_reset
        # and run()'s docstring.
        self._outcome = "quit"
        self.gamepad_reset_hold = GamepadResetHold()

    def _make_display(self) -> pygame.Surface:
        return _make_display(self.cfg)

    def _build_traffic(self) -> list[TrafficCar]:
        rng = random.Random(42)
        cars = []
        start = 120
        end = len(self.segments) - 60
        step = 90
        lane_centers = [(2 * i - (LANE_COUNT - 1)) / LANE_COUNT for i in range(LANE_COUNT)]
        for base in range(start, max(start + 1, end), step):
            lane = rng.choice(lane_centers)
            cars.append(TrafficCar(z=base * SEGMENT_LENGTH, x=lane, speed=TRAFFIC_SPEED))
        return cars

    def _build_decor(self) -> list[tuple[float, float, float]]:
        """(world_z, side, scale) for roadside trees, evenly spaced."""
        decor = []
        for i in range(10, len(self.segments) - 5, 14):
            side = 1.0 if (i // 14) % 2 == 0 else -1.0
            decor.append((i * SEGMENT_LENGTH, side, 1.0 + (i % 5) * 0.08))
        return decor

    # -- main loop ------------------------------------------------------
    def run(self, test_frames: int | None = None) -> str:
        """Runs the race until the player quits (Esc / window close) or
        triggers a Reset (Backspace, or an ~1s held gamepad Select/Back --
        see _trigger_reset). Returns "quit" or "reset" so the module-level
        run() below knows whether to tear the whole session down or loop
        back to SELECT MUSIC -- this method itself never calls
        pygame.quit(), so the window/display/renderer/MusicPlayer this
        Game was constructed with stay alive either way."""
        running = True
        frame = 0
        while running:
            dt = self.clock.tick(60) / 1000.0
            dt = min(dt, 0.05)
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self._outcome = "quit"
                    running = False
                elif event.type == pygame.KEYDOWN:
                    if not self._handle_keydown(event):
                        running = False
                elif event.type == pygame.CONTROLLERBUTTONDOWN:
                    self._handle_controller_button_down(event)
                elif event.type == pygame.CONTROLLERBUTTONUP:
                    self.gamepad_reset_hold.handle_event(event)
                elif event.type == pygame.CONTROLLERDEVICEADDED:
                    open_controller_from_event(event)
            if running and self.gamepad_reset_hold.triggered():
                self._trigger_reset()
                running = False
            keys = pygame.key.get_pressed()
            gamepad = get_primary_controller()
            self.update(dt, keys, gamepad)
            self._draw()
            pygame.display.flip()
            frame += 1
            if test_frames is not None and frame >= test_frames:
                running = False
        if self._outcome == "reset":
            self._draw_reset_flash()
        return self._outcome

    def _handle_controller_button_down(self, event: pygame.event.Event) -> None:
        """START maps to Restart -- "既存のポーズ/スタート操作": there's no
        pause feature in this game, so the closest existing "start
        (again)" action is Restart, same as the `R` key. Select/Back's
        hold-to-reset is handled by gamepad_reset_hold regardless of
        which button this event is for (it ignores anything else)."""
        self.gamepad_reset_hold.handle_event(event)
        if event.button == pygame.CONTROLLER_BUTTON_START:
            self._restart()

    def _handle_keydown(self, event: pygame.event.Event) -> bool:
        renderer, cfg = self.renderer, self.cfg
        key = event.key
        if key == pygame.K_ESCAPE:
            self._outcome = "quit"
            return False
        elif key == pygame.K_BACKSPACE:
            self._trigger_reset()
            return False
        elif key == pygame.K_r:
            self._restart()
        elif key == pygame.K_LEFTBRACKET:
            renderer.parallax_scale = max(0.0, renderer.parallax_scale - 0.05)
        elif key == pygame.K_RIGHTBRACKET:
            renderer.parallax_scale = min(2.0, renderer.parallax_scale + 0.05)
        elif key == pygame.K_z:
            renderer.zero_parallax = not renderer.zero_parallax
        elif key == pygame.K_i:
            renderer.flip_debug = not renderer.flip_debug
        elif key == pygame.K_d:
            self.show_debug = not self.show_debug
        elif key == pygame.K_f:
            cfg.fullscreen = not cfg.fullscreen
            self.screen = self._make_display()
            renderer.screen = self.screen
        elif key == pygame.K_s:
            cfg.parallax_scale = renderer.parallax_scale
            save_config(cfg)
        elif key == pygame.K_e:
            self._cycle_engine_preset()
        elif key == pygame.K_t:
            self._cycle_tire_preset()
        return True

    def _cycle_preset(self, order: list[str], current: str, set_preset, label: str) -> None:
        """Shared by _cycle_engine_preset/_cycle_tire_preset: advances to
        the next name in `order`, applies it via `set_preset`, and flashes
        "<label>: <name>" on screen -- see _draw_preset_flash."""
        next_name = order[(order.index(current) + 1) % len(order)] if current in order else order[0]
        set_preset(next_name)
        self._preset_flash_name = f"{label}: {next_name}"
        self._preset_flash_until_ms = pygame.time.get_ticks() + PRESET_FLASH_MS

    def _cycle_engine_preset(self) -> None:
        """`E`: audition the engine's three synthesis presets (see
        sfx.ENGINE_PRESETS) live during the race, since their tonal
        character is a real-hardware listening call this session can't
        make on its own -- see also sfx_test.py for an offline comparison
        tool. Purely a debug/tuning aid; has no effect on config.json or
        anything else the race depends on."""
        self._cycle_preset(
            ENGINE_PRESET_ORDER, self.engine_sound.preset_name, self.engine_sound.set_preset, "ENGINE"
        )

    def _cycle_tire_preset(self) -> None:
        """`T`: same idea as `E`, for the tire screech's three synthesis
        presets (see sfx.TIRE_SCREECH_PRESETS)."""
        self._cycle_preset(
            TIRE_SCREECH_PRESET_ORDER, self.tire_screech.preset_name, self.tire_screech.set_preset, "TIRE"
        )

    def _update_player_sprite_index(self, value: float) -> None:
        """Picks which of PLAYER_SPRITE_KEYS to draw from the (already
        time-smoothed, see update()) visual steering value, with
        hysteresis: once at index `i`, `value` must clear the boundary
        toward a neighboring index by PLAYER_SPRITE_HYSTERESIS (not just
        touch it) before that neighbor is selected -- stops the sprite
        flickering back and forth for a value sitting right at a
        boundary. In normal play `value` only ever changes gradually
        (it's already smoothed, so consecutive frames rarely cross more
        than one boundary), but this still walks multiple steps in one
        call if it ever needs to, so an unusually large single-frame
        jump can't strand the sprite in the wrong category."""
        idx = self._player_sprite_index
        max_idx = len(PLAYER_SPRITE_KEYS) - 1
        while True:
            lower = PLAYER_SPRITE_THRESHOLDS[idx - 1] - PLAYER_SPRITE_HYSTERESIS if idx > 0 else -2.0
            upper = PLAYER_SPRITE_THRESHOLDS[idx] + PLAYER_SPRITE_HYSTERESIS if idx < max_idx else 2.0
            if value < lower and idx > 0:
                idx -= 1
            elif value > upper and idx < max_idx:
                idx += 1
            else:
                break
        self._player_sprite_index = idx

    def _restart(self) -> None:
        self.player = Player()
        self.time_left = RACE_TIME
        self.score = 0.0
        self.finished = False
        self.time_up = False
        self.collision_cooldown = 0.0
        self.traffic = self._build_traffic()
        self.cam_elevation = 0.0
        self.player_bob = 0.0
        self.player_visual_steer = 0.0
        self._player_sprite_index = PLAYER_SPRITE_KEYS.index("straight")

    def _trigger_reset(self) -> None:
        """The Maker Faire "next visitor" Reset, as opposed to _restart()
        (same BGM/settings, same race from the top): this clears the race
        exactly like _restart() but additionally stops the BGM and SFX and
        marks run()'s outcome as "reset" so the caller ends the race loop
        and shows SELECT MUSIC again (which resets the track selection to
        PIXEL BREEZE and previews it, on its own -- see
        MusicSelectScreen.run()). Never touches self.cfg / config.json."""
        self.engine_sound.stop()
        self.tire_screech.stop()
        if self.music is not None:
            self.music.stop()
        self._restart()
        self._outcome = "reset"

    def _draw_reset_flash(self) -> None:
        """A brief "RESET" flash before control returns to SELECT MUSIC --
        drawn zero-parallax like the select screen itself (not the
        screen-center overlay _draw_message uses), so it's actually
        readable through both lenses. Kept short on purpose: this runs at
        a live exhibit, not a menu a visitor is expected to read."""
        def draw(surf: pygame.Surface, ox: float) -> None:
            w, h = surf.get_size()
            text = self.font_message.render("RESET", True, MESSAGE_COLOR)
            surf.blit(text, text.get_rect(center=(w / 2 + ox, h / 2)))

        self.renderer.begin_frame(BLACK)
        self.renderer.draw_flat(draw)
        self.renderer.present()
        pygame.display.flip()
        pygame.time.delay(RESET_FLASH_MS)

    # -- simulation (runs once, regardless of how many eyes we draw) ----
    def update(self, dt: float, keys, gamepad=None) -> None:
        """`gamepad` is the pygame._sdl2.controller.Controller to read
        analog steering/accelerate/brake from this frame, or None (no
        controller connected/recognized) -- keyboard keeps working
        exactly as before either way; see gamepad.py's read_steer/
        read_accel/read_brake, which all degrade to "no input" on None."""
        start = pygame.time.get_ticks()
        self.collision_cooldown = max(0.0, self.collision_cooldown - dt)

        racing = not self.finished and not self.time_up
        if racing:
            offroad = abs(self.player.x) > 1.0
            max_speed = OFFROAD_MAX_SPEED if offroad else MAX_SPEED
            friction = OFFROAD_FRICTION if offroad else FRICTION

            if keys[pygame.K_UP] or keys[pygame.K_w] or read_accel(gamepad):
                self.player.speed += ACCEL * dt
            elif keys[pygame.K_DOWN] or keys[pygame.K_s] or read_brake(gamepad):
                self.player.speed -= BRAKE * dt
            else:
                self.player.speed -= friction * dt
            self.player.speed = max(0.0, min(max_speed, self.player.speed))

            speed_frac = self.player.speed / MAX_SPEED
            steer = 0.0
            if keys[pygame.K_LEFT] or keys[pygame.K_a]:
                steer -= 1.0
            if keys[pygame.K_RIGHT] or keys[pygame.K_d]:
                steer += 1.0
            steer = max(-1.0, min(1.0, steer + read_steer(gamepad)))
            self.player.x += steer * STEER_RATE * speed_frac * dt

            # Sprite selection only -- deliberately never touches
            # player.x/collision (see PLAYER_VISUAL_STEER_SMOOTHING's
            # comment): smooths the same combined keyboard+gamepad
            # `steer` used for physics above into a separate value that
            # drifts toward it over time instead of snapping, so a
            # keyboard/D-pad digital +-1 press ramps through the sprite
            # progression rather than jumping straight to hard_left/
            # hard_right.
            self.player_visual_steer += (
                (steer - self.player_visual_steer) * min(1.0, PLAYER_VISUAL_STEER_SMOOTHING * dt)
            )
            self._update_player_sprite_index(self.player_visual_steer)

            # Interpolated, not the coarse per-segment value: during a
            # curve, consecutive segments' curve/world_x can differ by a
            # large fraction of the road width, so sampling them as a
            # step function made the whole view visibly hop once per
            # segment (~every 60-70ms at speed) instead of panning
            # smoothly through the turn.
            self.current_curve = curve_at(self.segments, self.player.z)
            self.player.x -= self.current_curve * CENTRIFUGAL * speed_frac * dt
            self.player.x = max(-PLAYER_X_LIMIT, min(PLAYER_X_LIMIT, self.player.x))

            # Background pans opposite the curve (as if the camera itself
            # were yawing into the turn) and eases back once the curve
            # straightens out again -- see the BG_SHIFT_* comment above.
            target_bg_shift = -self.current_curve * speed_frac * BG_SHIFT_SCALE
            self.bg_offset += (target_bg_shift - self.bg_offset) * min(1.0, BG_SHIFT_SMOOTHING * dt)

            # Camera's road-height reference eases toward the player's
            # actual segment elevation rather than snapping to it -- see
            # PLAYER_BOB_* below for the (separate, more heavily damped)
            # player-car sprite nudge that rides on top of this.
            target_cam_elevation = elevation_at(self.segments, self.player.z)
            self.cam_elevation += (
                (target_cam_elevation - self.cam_elevation) * min(1.0, CAMERA_ELEVATION_SMOOTHING * dt)
            )
            grade = (
                elevation_at(self.segments, self.player.z + PLAYER_BOB_LOOKAHEAD)
                - elevation_at(self.segments, self.player.z)
            ) / PLAYER_BOB_LOOKAHEAD
            target_bob = max(-PLAYER_BOB_MAX_PX, min(PLAYER_BOB_MAX_PX, -grade * PLAYER_BOB_STRENGTH))
            self.player_bob += (target_bob - self.player_bob) * min(1.0, PLAYER_BOB_SMOOTHING * dt)

            self.player.z += self.player.speed * dt
            self.score += self.player.speed * dt * SCORE_PER_SECOND_PER_SPEED

            for car in self.traffic:
                car.z = min(car.z + car.speed * dt, self.track_length)
                if (
                    self.collision_cooldown <= 0.0
                    and abs(self.player.z - car.z) < COLLISION_Z_RANGE
                    and abs(self.player.x - car.x) < COLLISION_X_RANGE
                ):
                    self.player.speed *= COLLISION_PENALTY
                    self.collision_cooldown = COLLISION_COOLDOWN

            # Recomputed from this frame's final speed (post-collision, if
            # any) so a hit's speed drop is audible immediately rather than
            # one frame late. Tire screech reuses the centrifugal-drift
            # proxy already computed above -- see sfx.py's own comment for
            # why that stands in for lateral tire force here.
            self.engine_sound.update(self.player.speed / MAX_SPEED, active=True, dt=dt)
            self.tire_screech.update(abs(self.current_curve) * speed_frac, active=True)

            self.time_left -= dt
            if self.player.z >= self.track_length:
                self.player.z = self.track_length
                self.finished = True
            elif self.time_left <= 0.0:
                self.time_left = 0.0
                self.time_up = True
        else:
            self.engine_sound.update(0.0, active=False, dt=dt)
            self.tire_screech.update(0.0, active=False)

        self.last_frame_ms = pygame.time.get_ticks() - start

    def _segment_at(self, world_z: float):
        idx = int(world_z / SEGMENT_LENGTH)
        idx = max(0, min(len(self.segments) - 1, idx))
        return self.segments[idx]

    # -- drawing ----------------------------------------------------------
    def _draw(self) -> None:
        renderer = self.renderer
        renderer.begin_frame(BLACK)
        self._draw_background()
        self._draw_road()
        for wz, side, scale in self.decor:
            self._draw_decor_object(wz, side, scale)
        for car in self.traffic:
            self._draw_traffic_car(car)
        renderer.draw_world(PLAYER_CAR_DEPTH, self._draw_player_car)
        renderer.draw_flat(self._draw_hud)
        if self._preset_flash_name is not None and pygame.time.get_ticks() < self._preset_flash_until_ms:
            renderer.draw_flat(self._draw_preset_flash)
        renderer.present()
        if self.finished or self.time_up:
            self._draw_message()
        if self.show_debug:
            self._draw_debug_overlay()

    def _draw_background(self) -> None:
        def draw(surf: pygame.Surface, ox: float) -> None:
            # bg_offset pans both eyes equally (it's a camera-yaw cue, not
            # a depth cue) on top of the normal small stereo disparity.
            ox = ox + self.bg_offset
            w, h = surf.get_size()
            horizon = int(h * 0.5)
            for cx_frac, cy, r in ((0.28, horizon * 0.28, 10), (0.6, horizon * 0.42, 13), (0.82, horizon * 0.2, 8)):
                rect = pygame.Rect(0, 0, int(r * 2.2), int(r))
                rect.center = (int(w * cx_frac + ox), int(cy))
                pygame.draw.ellipse(surf, CLOUD_COLOR, rect)
            pts = [
                (0, horizon), (w * 0.18, horizon - 18), (w * 0.35, horizon - 4),
                (w * 0.55, horizon - 22), (w * 0.75, horizon - 8), (w * 0.9, horizon - 16), (w, horizon),
            ]
            pygame.draw.polygon(surf, MOUNTAIN_COLOR, [(x + ox, y) for x, y in pts])

        self.renderer.draw_world(250.0, draw)

    def _road_center_x(self) -> float:
        # Interpolated (see world_x_at's docstring) -- this is the
        # camera's lateral reference point, sampled every frame, so any
        # coarseness here shows up directly as a jerky/stepped view.
        return world_x_at(self.segments, self.player.z) + self.player.x * ROAD_WIDTH

    def _draw_road(self) -> None:
        renderer = self.renderer
        left, right = renderer.left_surface, renderer.right_surface
        width, height = left.get_size()
        cam_x = self._road_center_x()
        cam_y = self.cam_elevation
        cam_z = self.player.z

        base_idx = int(self.player.z / SEGMENT_LENGTH)
        self._road_base_idx = base_idx
        max_idx = len(self.segments) - 1

        # world_z always advances with n, even past the last real segment
        # (near the finish line) -- otherwise every point beyond the track
        # end would collapse onto the same segment at distance ~0 and the
        # road would degenerate into one overlapping blob instead of
        # continuing to recede into the distance.
        #
        # Points are built NEAREST-first (n=0..DRAW_DISTANCE) so the
        # render loop below can walk near-to-far and apply the classic
        # "crest watermark" hill-occlusion trick: on flat/curved ground
        # (elevation 0) sy is strictly decreasing as n increases, so the
        # watermark check below never fires and this is equivalent to the
        # old far-to-near painter's-algorithm order; it only starts hiding
        # segments once a hill crest makes a farther segment's projected y
        # fail to clear the nearer crest's, which is exactly the "hidden
        # behind the hill" case. See docs/PHASE2_RACE_LOG.md.
        points = []
        for n in range(0, DRAW_DISTANCE + 1):
            idx = base_idx + n
            look_idx = min(idx, max_idx)
            seg = self.segments[look_idx]
            world_z = idx * SEGMENT_LENGTH
            sx, sy, sw, tz = project(seg.world_x, seg.elevation, world_z, cam_x, cam_y, cam_z, width, height)
            points.append((look_idx, sx, sy, sw, tz))

        crest_y = float(height)
        clip_before_n = [crest_y] * DRAW_DISTANCE
        for i in range(len(points) - 1):
            idx_near, sx_near, sy_near, sw_near, tz_near = points[i]
            idx_far, sx_far, sy_far, sw_far, tz_far = points[i + 1]
            clip_before_n[i] = crest_y

            if sy_far >= sy_near or sy_far >= crest_y:
                # Far edge doesn't rise above the near edge (perspective
                # has inverted on the far side of a crest), or doesn't
                # clear the watermark a nearer crest already established
                # -- either way this segment is hidden behind a hill.
                continue

            dark = self.segments[idx_near].looks_dark
            grass = GRASS_DARK if dark else GRASS_LIGHT
            rumble = RUMBLE_DARK if dark else RUMBLE_LIGHT
            road = ROAD_DARK if dark else ROAD_LIGHT

            for color, mult in ((grass, 3.0), (rumble, 1.15), (road, 1.0)):
                l_near, r_near = renderer.project_x(sx_near, tz_near)
                l_far, r_far = renderer.project_x(sx_far, tz_far)
                w_near, w_far = sw_near * mult, sw_far * mult
                pygame.draw.polygon(
                    left, color,
                    [(l_near - w_near, sy_near), (l_near + w_near, sy_near),
                     (l_far + w_far, sy_far), (l_far - w_far, sy_far)],
                )
                pygame.draw.polygon(
                    right, color,
                    [(r_near - w_near, sy_near), (r_near + w_near, sy_near),
                     (r_far + w_far, sy_far), (r_far - w_far, sy_far)],
                )

            if dark:
                # American-style dashed lane dividers: only drawn on the
                # "dark" rumble bands, which gives them a dashed look for
                # free using the same alternation as the rumble strips.
                line_hw_frac = LANE_LINE_HALF_WIDTH / ROAD_WIDTH
                for frac in LANE_DIVIDER_FRACS:
                    off_near, off_far = sw_near * frac, sw_far * frac
                    hw_near, hw_far = sw_near * line_hw_frac, sw_far * line_hw_frac
                    l_near, r_near = renderer.project_x(sx_near + off_near, tz_near)
                    l_far, r_far = renderer.project_x(sx_far + off_far, tz_far)
                    pygame.draw.polygon(
                        left, LANE_LINE_COLOR,
                        [(l_near - hw_near, sy_near), (l_near + hw_near, sy_near),
                         (l_far + hw_far, sy_far), (l_far - hw_far, sy_far)],
                    )
                    pygame.draw.polygon(
                        right, LANE_LINE_COLOR,
                        [(r_near - hw_near, sy_near), (r_near + hw_near, sy_near),
                         (r_far + hw_far, sy_far), (r_far - hw_far, sy_far)],
                    )

            crest_y = sy_near

        self._road_clip_before_n = clip_before_n

    def _sprite_visible(self, world_z: float, sy: float) -> bool:
        """A sprite (traffic car / roadside decor) is hidden once a nearer
        hill crest's road-edge watermark has been reached -- reuses the
        same clip values _draw_road built for the road polygons
        themselves, so a car/tree behind a hill stays hidden until the
        camera crests it instead of being drawn independent of the
        terrain that's currently blocking it."""
        n = int(world_z / SEGMENT_LENGTH) - self._road_base_idx
        if 0 <= n < len(self._road_clip_before_n):
            return sy < self._road_clip_before_n[n]
        return True

    def _draw_decor_object(self, world_z: float, side: float, scale: float) -> None:
        seg = self._segment_at(world_z)
        cam_x = self._road_center_x()
        cam_y = self.cam_elevation
        cam_z = self.player.z
        width, height = self.renderer.left_surface.get_size()
        world_x = seg.world_x + side * ROAD_WIDTH * 1.4
        world_y = elevation_at(self.segments, world_z)
        sx, sy, sw, tz = project(world_x, world_y, world_z, cam_x, cam_y, cam_z, width, height)
        if tz > SEGMENT_LENGTH * (DRAW_DISTANCE + 1) or world_z < cam_z:
            return
        if not self._sprite_visible(world_z, sy):
            return

        def draw(surf: pygame.Surface, ox: float) -> None:
            draw_tree(surf, sx + ox, sy, max(0.3, scale * (sw / (ROAD_WIDTH * 6))), TREE_COLOR)

        self.renderer.draw_world(tz, draw)

    def _draw_traffic_car(self, car: TrafficCar) -> None:
        # Interpolated like the camera reference (world_x_at) since a
        # traffic car's z keeps advancing frame to frame, unlike static
        # roadside decor -- otherwise it would visibly hop sideways once
        # per segment while cornering, same as the camera did. Elevation
        # is sampled the same way (elevation_at), so a car sits exactly on
        # the road surface of whatever segment it currently occupies
        # instead of floating/sinking as the road climbs or falls under it.
        cam_x = self._road_center_x()
        cam_y = self.cam_elevation
        cam_z = self.player.z
        width, height = self.renderer.left_surface.get_size()
        world_x = world_x_at(self.segments, car.z) + car.x * ROAD_WIDTH
        world_y = elevation_at(self.segments, car.z)
        sx, sy, sw, tz = project(world_x, world_y, car.z, cam_x, cam_y, cam_z, width, height)
        if tz > SEGMENT_LENGTH * (DRAW_DISTANCE + 1) or car.z < cam_z:
            return
        if not self._sprite_visible(car.z, sy):
            return

        def draw(surf: pygame.Surface, ox: float) -> None:
            draw_car(surf, sx + ox, sy, max(0.35, sw / (ROAD_WIDTH * 3.5)), TRAFFIC_COLOR)

        self.renderer.draw_world(tz, draw)

    def _draw_player_car(self, surf: pygame.Surface, ox: float) -> None:
        w, h = surf.get_size()
        speed_frac = self.player.speed / MAX_SPEED
        # Nudge the car sprite toward the curve direction, in step with
        # the background panning the opposite way (see _draw_background)
        # -- together they read as "drifting into the turn" instead of
        # "still going straight while the road bends."
        lean = self.current_curve * speed_frac * CAR_LEAN_SCALE
        cx = w / 2 + self.player.x * 10 + lean + ox
        # player_bob is a small, smoothed, clamped nudge from the local
        # road grade (see update()) -- the car's base position stays
        # pinned near the bottom of the screen, it doesn't move by the
        # same amount as the road itself.
        cy = h - 34 + self.player_bob
        sprite_key = PLAYER_SPRITE_KEYS[self._player_sprite_index]
        sprite = self._player_sprites.get(sprite_key)
        if sprite is not None:
            anchor_x, anchor_y = PLAYER_SPRITE_ANCHOR
            surf.blit(sprite, (cx - anchor_x, cy - anchor_y))
        else:
            # Missing/broken sprite files -- fall back to the original
            # placeholder rectangle rather than drawing nothing.
            draw_car(surf, cx, cy, 1.0, PLAYER_COLOR)

    def _draw_hud(self, surf: pygame.Surface, ox: float) -> None:
        w, h = surf.get_size()
        speed_kmh = int(self.player.speed / MAX_SPEED * HUD_MAX_DISPLAY_SPEED)
        boxes = [
            ("TIME", f"{int(self.time_left):02d}"),
            ("SCORE", f"{int(self.score):06d}"),
            ("SPEED", f"{speed_kmh:03d}"),
        ]
        box_w = w / len(boxes)
        for i, (label, value) in enumerate(boxes):
            x0 = int(i * box_w) + 2
            rect = pygame.Rect(x0, h - 30, int(box_w) - 4, 26)
            pygame.draw.rect(surf, HUD_BORDER, rect, 1)
            surf.blit(self.font_hud.render(label, True, HUD_TEXT), (rect.x + 3, rect.y + 1))
            surf.blit(self.font_hud.render(value, True, HUD_TEXT), (rect.x + 3, rect.y + 13))

    def _draw_preset_flash(self, surf: pygame.Surface, ox: float) -> None:
        w, _h = surf.get_size()
        text = self.font_hud.render(self._preset_flash_name, True, MESSAGE_COLOR)
        surf.blit(text, text.get_rect(midtop=(w / 2 + ox, 4)))

    def _draw_message(self) -> None:
        text = "FINISH!" if self.finished else "TIME UP"
        sub = f"score {int(self.score)}  -  R restart  -  BACKSPACE reset"
        surf1 = self.font_message.render(text, True, MESSAGE_COLOR)
        surf2 = self.font_debug.render(sub, True, MESSAGE_COLOR)
        cx = self.cfg.output_width // 2
        cy = self.cfg.output_height // 2
        self.screen.blit(surf1, surf1.get_rect(center=(cx, cy - 10)))
        self.screen.blit(surf2, surf2.get_rect(center=(cx, cy + 14)))

    def _draw_debug_overlay(self) -> None:
        renderer, cfg = self.renderer, self.cfg
        max_in, max_out = renderer.max_disparity_range()
        fps = self.clock.get_fps()
        lines = [
            f"fps={fps:5.1f}  frame_ms={self.last_frame_ms:4.1f}  parallax={renderer.parallax_scale:.2f}([/])"
            f"  zero={'ON' if renderer.zero_parallax else 'off'}(Z)  flip={'ON' if renderer.flip_debug else 'off'}(I)",
            f"caps=[{max_out:+.0f},{max_in:+.0f}]px  player.z={self.player.z:7.1f}/{self.track_length:.0f}"
            f"  player.x={self.player.x:+.2f}  speed={self.player.speed:5.1f}",
            f"engine: {'on' if self.engine_sound.available else 'unavailable'}"
            f" preset={self.engine_sound.preset_name}(E) rpm={self.engine_sound.engine_rpm:.2f}"
            f" bucket={self.engine_sound._bucket}/{ENGINE_BUCKET_COUNT - 1}"
            f"  tire_screech: {'on' if self.tire_screech.available else 'unavailable'}"
            f" preset={self.tire_screech.preset_name}(T)"
            f" playing={pygame.mixer.Channel(self.tire_screech.CHANNEL).get_busy() if self.tire_screech.available else False}",
            f"player sprite: steer={self.player_visual_steer:+.2f}"
            f" -> {PLAYER_SPRITE_KEYS[self._player_sprite_index]}"
            f"  (assets {'loaded' if self._player_sprites else 'MISSING, using placeholder rect'})",
        ]
        # Only shown when something's actually wrong -- see sfx.py's
        # unavailable_reason: exactly the "is it a trigger bug or a
        # loudness/perception issue" question a real-hardware SFX report
        # can't otherwise answer without another guess-and-check round.
        if not self.engine_sound.available:
            lines.append(f"engine unavailable: {self.engine_sound.unavailable_reason}")
        if not self.tire_screech.available:
            lines.append(f"tire_screech unavailable: {self.tire_screech.unavailable_reason}")
        y = 4
        for line in lines:
            surf = self.font_debug.render(line, True, DEBUG_TEXT)
            self.screen.blit(surf, (6, y))
            y += 13


def run(test_frames: int | None = None) -> None:
    """Owns the whole process-lifetime session: pygame.init()/pygame.quit()
    are called exactly once each, here, no matter how many races are
    played. Between them, SELECT MUSIC and the race alternate in a loop --
    a normal quit (Esc / window close, from either screen) breaks out and
    falls through to the single pygame.quit() at the bottom; a Reset
    (Game.run() returning "reset") instead loops back to SELECT MUSIC with
    the same window/renderer/MusicPlayer, exactly the "don't quit the app,
    don't touch config.json" behavior the Maker Faire reset feature needs.
    """
    # Explicitly pin the mixer to a known-good format *before*
    # pygame.init() auto-initializes it, instead of trusting whatever
    # pygame/SDL would otherwise negotiate with the real output device.
    # 2026-09-04: real-hardware testing reported the engine/tire SFX not
    # merely quiet but genuinely never triggering (EngineSound.available
    # stuck False) despite BGM working fine -- BGM goes through the
    # separate pygame.mixer.music stream, unaffected by this, while SFX
    # goes through pygame.mixer.Sound/Channel, which sfx.py's
    # _mixer_format() refuses to use if the negotiated channel count isn't
    # 1 or 2 (e.g. some HDMI audio paths report more). Forcing channels=2
    # up front removes that whole class of failure; the retry below
    # covers the case where pre_init's hint wasn't honored for some
    # reason. See docs/PHASE2_RACE_LOG.md and sfx.py's unavailable_reason
    # (shown on the `D`-key debug overlay) for the other likely cause this
    # doesn't fix by itself: numpy simply not installed in the venv.
    pygame.mixer.pre_init(frequency=44100, size=-16, channels=2, buffer=512)
    pygame.init()
    if not pygame.mixer.get_init():
        try:
            pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=512)
        except pygame.error:
            pass
    pygame.display.set_caption("Virtual Boy Stereo Racing - Phase 2")
    open_connected_controllers()
    cfg = load_config()
    screen = _make_display(cfg)
    renderer = StereoRenderer(screen, cfg)
    music = MusicPlayer()

    while True:
        selected = MusicSelectScreen(renderer, music).run(test_frames=test_frames)
        if selected is None:
            # Quit from the select screen (Esc / window close) -- no race.
            break
        # MusicSelectScreen.run() already leaves music.index pointing at
        # the confirmed track as a side effect of its own
        # select()/next()/prev() calls -- select() here again anyway so
        # Game's music state doesn't silently depend on that invariant
        # holding in whatever returned `selected`.
        music.select(selected)

        outcome = Game(cfg, screen=screen, renderer=renderer, music=music).run(
            test_frames=test_frames
        )
        if outcome != "reset":
            break

    pygame.quit()


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 2 racing game")
    parser.add_argument(
        "--test-frames",
        type=int,
        default=None,
        help="Run N frames and exit automatically (smoke test / CI, no input needed).",
    )
    args = parser.parse_args()
    run(test_frames=args.test_frames)


if __name__ == "__main__":
    main()
