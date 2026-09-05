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
from collections import OrderedDict
from pathlib import Path

import numpy as np
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


# -- Enemy/traffic car sprites (2026-09-05) ----------------------------------
# 6 red/black pixel-art vehicles (assets/cars/enemies/) replacing the flat
# rectangle draw_car() drew for every traffic car previously -- extracted
# from a user-supplied sprite sheet by scripts/build_enemy_sprites.py, which
# also derives CANVAS_SIZE/ANCHOR below (regenerate & update this pair
# together if the sheet is ever rebuilt at a different size, same caveat as
# the player sprites above). Unlike the player car's 5 poses (near-identical
# footprints, so a flicker-free switch needs everyone the same size), these
# 6 crops intentionally differ in size -- the van/pickup are taller than the
# sedans -- so what's actually shared is just the canvas they sit on and the
# bottom-center anchor point within it: every vehicle's own tire-contact
# point lands at the same (cx, cy) even though their silhouettes differ.
ENEMY_ASSETS_DIR = Path(__file__).resolve().parent / "assets" / "cars" / "enemies"
ENEMY_SPRITE_KEYS = (
    "sports_coupe", "boxy_sedan", "compact_hatchback",
    "panel_van", "muscle_car", "pickup_truck",
)
# Spawn-rate weights, same order as ENEMY_SPRITE_KEYS -- the "初期案" ratios
# from CLAUDE_CODE_ENEMY_CARS_INSTRUCTIONS.txt.
ENEMY_SPRITE_WEIGHTS = (0.20, 0.20, 0.20, 0.15, 0.15, 0.10)
ENEMY_SPRITE_CANVAS_SIZE = (75, 58)
ENEMY_SPRITE_ANCHOR = (37, 58)  # bottom-center

# Fallback-only reference widths, in px -- used solely when the relevant
# sprite set failed to load (see Game._player_reference_width_px /
# _enemy_reference_opaque_width_px below, which is what every sizing
# calculation in _draw_traffic_car actually reads at runtime). 2026-09-05,
# 3rd real-hardware feedback round: comparing against these as hardcoded
# constants -- rather than the *actual rendered* opaque-pixel bbox of the
# player/boxy_sedan surfaces currently in memory -- was flagged as a risk
# in itself (a stale derivation could quietly drift from what's really on
# screen), so Game.__init__ now measures both directly off the loaded
# Surfaces via _opaque_sprite_width() and stores them per-instance; these
# module constants only cover the degenerate "sprites failed to load"
# case, which already falls back to draw_car()'s rectangle and so never
# actually exercises this number.
PLAYER_REFERENCE_WIDTH_PX = 71
ENEMY_REFERENCE_OPAQUE_WIDTH_PX = 63

# 2026-09-05, four rounds of real-hardware feedback:
#   1st: an up-close panel_van looked far bigger than the player car --
#        _draw_traffic_car was drawing sprites at draw_car()'s old
#        perspective scale directly (`sw / (ROAD_WIDTH * 3.5)`), which
#        blows up to several times the viewport width as a car's depth
#        approaches the player's (project()'s trans_z floor at
#        SEGMENT_LENGTH).
#   2nd: calibrating that scale down so a "standard" car (boxy_sedan)
#        exactly matches the player's width right at that closest depth
#        fixed the up-close case, but as a side effect shrank far/mid
#        traffic to a few illegible px -- accurate pinhole-camera
#        perspective, but poor gameplay legibility (the original spec
#        explicitly asked that vehicle types stay recognizable at range).
#   3rd: even after the 2nd round, close-up enemy cars still measured
#        ~1.2-1.5x the player's own visible width by eye on real
#        hardware, so the closest-depth target was lowered to 85%.
#   4th: a live `F7`-cycled A/B tool (100%/90%/80% of the 3rd round's
#        sizing, applied uniformly across every distance, not just up
#        close) let the actual choice be made by eye on real hardware
#        rather than guessed at from a description -- 80% won ("いい感
#        じです"). The values below are the 3rd round's curve and clamp
#        each multiplied by that same 0.8, baked in as the new baseline;
#        the F7 tool itself (ENEMY_SIZE_DEBUG_MULTIPLIERS,
#        _cycle_enemy_size_debug, its debug-overlay line) has been
#        removed now that the comparison is settled, per its own
#        "temporary" framing.
#
# ENEMY_SPRITE_TARGET_RATIO_POINTS below replaces the raw perspective
# scale for the sprite path entirely (draw_car()'s rectangle fallback
# still uses the plain distance `scale` -- see _draw_traffic_car) with an
# explicit, hand-tuned curve: for each distance `tz` (world units ahead,
# project()'s already-floored trans_z), what fraction of the player
# sprite's own on-screen opaque width the *standard* vehicle's own opaque
# width should be. Points are (tz, target_ratio), tz strictly ascending
# and target_ratio strictly descending -- that monotonic pairing is what
# guarantees _enemy_target_ratio's smoothstep interpolation never dips or
# pops between control points (unlike an earlier version of this curve
# that multiplied a "boost" onto the raw 1/tz scale: boost and scale
# individually smooth doesn't imply their product is). Beyond the last
# point the ratio holds constant, same reasoning as the perspective
# scale's own 0.35 floor plateauing at long range.
#
# Values: ~90m -> ~8%, ~60m -> ~14%, ~30m -> ~32%, at the closest
# representable depth (project()'s trans_z floor, "same depth as the
# player") -> ~68% -- all = the 3rd round's 10%/17.5%/40%/85% x0.8,
# confirmed on real hardware via the F7 A/B tool. Re-tune by editing the
# ratios directly and re-running the tests in the "Enemy car sizing"
# section of tests/test_game.py; see docs/PHASE2_RACE_LOG.md's
# "2026-09-05（18回目）" section for this round's derivation ("16回目"/
# "17回目" for the earlier ones).
ENEMY_SPRITE_TARGET_RATIO_POINTS = (
    (3.0, 0.68),    # same-depth calibration point (project()'s trans_z floor)
    (30.0, 0.32),
    (60.0, 0.14),
    (90.0, 0.08),
)

# Hard safety cap, independent of the curve above: no traffic car,
# regardless of vehicle type or distance, may ever draw wider on screen
# than this fraction of the player's own width -- catches muscle_car's
# own +5% WIDTH_MULT and any future curve mistuning. Matches the curve's
# own closest-point target (3rd round's 85% x the 4th round's 0.8).
ENEMY_SPRITE_MAX_WIDTH_RATIO = 0.68


def _smoothstep(edge0: float, edge1: float, x: float) -> float:
    t = max(0.0, min(1.0, (x - edge0) / (edge1 - edge0)))
    return t * t * (3.0 - 2.0 * t)


def _enemy_target_ratio(tz: float) -> float:
    """ENEMY_SPRITE_TARGET_RATIO_POINTS's target_ratio for a car at
    distance `tz` -- 1.0 right at the same-depth calibration point,
    smoothly falling at greater distances, holding flat beyond the last
    control point. Strictly monotonic in tz by construction (see the
    control points' own docstring), so displayed width never dips as a
    car gets closer."""
    points = ENEMY_SPRITE_TARGET_RATIO_POINTS
    if tz <= points[0][0]:
        return points[0][1]
    if tz >= points[-1][0]:
        return points[-1][1]
    for (tz0, r0), (tz1, r1) in zip(points, points[1:]):
        if tz0 <= tz <= tz1:
            t = _smoothstep(tz0, tz1, tz)
            return r0 + (r1 - r0) * t
    return points[-1][1]  # unreachable given the tz range checks above


def _opaque_sprite_width(surf: pygame.Surface) -> int:
    """The vehicle's own visible pixel width within its canvas (as
    opposed to the canvas's full width, which includes transparent
    padding that differs in proportion per vehicle) -- what
    ENEMY_REFERENCE_OPAQUE_WIDTH_PX and ENEMY_SPRITE_MAX_WIDTH_RATIO's
    clamp are both defined in terms of."""
    alpha = pygame.surfarray.pixels_alpha(surf)
    mask = alpha > 0
    if not mask.any():
        return surf.get_width()
    xs = np.where(mask.any(axis=1))[0]
    return int(xs.max() - xs.min() + 1)


# Deliberately its own fixed seed, separate from _build_traffic's lane/
# position rng (random.Random(42)) -- sprite_id selection must never draw
# from that rng, or every lane pick after the first car would shift and the
# whole traffic layout (lanes, positions -- all already relied on by
# tests/replays) would change. _build_traffic instead finishes the existing
# lane/position/speed loop untouched, *then* makes a second pass with this
# separate Random instance to assign sprite_id -- see its comment.
ENEMY_SPRITE_RNG_SEED = 20260905


_enemy_sprites_cache: dict = {"loaded": False, "sprites": {}}


def _load_enemy_sprites() -> dict[str, pygame.Surface]:
    """Same all-or-nothing cached-load pattern as _load_player_sprites()
    (see its docstring) -- a partial set would let some traffic cars use
    real art and others silently fall back mid-race, worse than every car
    using the placeholder rectangle."""
    if _enemy_sprites_cache["loaded"]:
        return _enemy_sprites_cache["sprites"]
    sprites: dict[str, pygame.Surface] = {}
    try:
        for key in ENEMY_SPRITE_KEYS:
            path = ENEMY_ASSETS_DIR / f"{key}.png"
            surf = pygame.image.load(str(path)).convert_alpha()
            if surf.get_size() != ENEMY_SPRITE_CANVAS_SIZE:
                sprites = {}
                break
            sprites[key] = surf
    except (pygame.error, FileNotFoundError, OSError):
        sprites = {}
    _enemy_sprites_cache["sprites"] = sprites
    _enemy_sprites_cache["loaded"] = True
    return sprites


# -- Roadside palm trees (2026-09-05) ----------------------------------------
# 6 red/black pixel-art palms (assets/scenery/palms/) alongside the existing
# procedural roadside decor (draw_tree()/self.decor, unchanged) -- extracted
# from a user-supplied sprite sheet by scripts/build_palm_sprites.py, which
# also derives CANVAS_SIZE/ANCHOR below. Palms reuse the *same* projection,
# distance culling, and hill-crest occlusion _draw_decor_object already used
# for the procedural trees (see _draw_palm) -- no separate projection
# pipeline. Unlike the enemy cars, all 6 share one scale factor at asset-
# build time (see build_palm_sprites.py's docstring for why that's safe
# here); what matters at runtime is each sprite's own *measured opaque
# height* (self._palm_sprite_opaque_heights), never raw canvas height.
PALM_ASSETS_DIR = Path(__file__).resolve().parent / "assets" / "scenery" / "palms"
PALM_SPRITE_KEYS = (
    "palm_straight", "palm_lean_left", "palm_lean_right",
    "palm_short_wide", "palm_windblown", "palm_pair",
)
PALM_NON_PAIR_KEYS = tuple(k for k in PALM_SPRITE_KEYS if k != "palm_pair")
PALM_SPRITE_CANVAS_SIZE = (109, 162)
PALM_SPRITE_ANCHOR = (54, 156)  # root (trunk base) center

# How far outside the road edge palms sit -- same formula/offset the
# existing procedural roadside trees already use (seg.world_x + side *
# ROAD_WIDTH * 1.4 in _draw_decor_object), reused as-is for consistency
# rather than inventing a second placement convention.
PALM_ROAD_SIDE_OFFSET = ROAD_WIDTH * 1.4

# -- Placement (see _build_palms) --------------------------------------------
# All index values are segment indices (same units as HILL_START/
# VALLEY_START in road.py), not world_z. Deliberately index 60-1050 (out
# of 2100 total segments) rather than the whole track, per the "海岸道路
# らしい区間を中心に、詰め込みすぎない" ask -- the front-to-mid section,
# stopping well before the valley (VALLEY_START=1710). The first 60
# segments are left empty on purpose so the start-of-race view/HUD isn't
# immediately crowded.
PALM_PLACEMENT_START_INDEX = 60
PALM_PLACEMENT_END_INDEX = 1050
PALM_SPACING_MIN_SEGMENTS = 28
PALM_SPACING_MAX_SEGMENTS = 40
PALM_SAME_SIDE_MAX_STREAK = 2  # never more than this many placements in a row on one side
PALM_PAIR_PROBABILITY = 0.125  # midpoint of the requested 10-15%

# Deliberately its own fixed seed, separate from every other rng in this
# file (_build_traffic's lane rng random.Random(42) and sprite rng
# random.Random(ENEMY_SPRITE_RNG_SEED)) -- random.Random instances are
# fully independent objects with no shared global state, so this can
# never perturb those sequences regardless of call order, but it's still
# given its own distinct seed for clarity and so re-tuning palm density
# can't accidentally collide with either existing seed.
PALM_RNG_SEED = 20260905_02

# -- Sizing (see _draw_palm) --------------------------------------------------
# "How tall is a *standard* palm (palm_straight) on screen at scale=1.0"
# (the same `scale = max(0.3, sw / (ROAD_WIDTH * 6))` the procedural
# roadside trees already compute) -- deliberately independent of
# PALM_SPRITE_CANVAS_SIZE's arbitrary source-art resolution, tunable on
# its own. Other palm types come out taller/shorter than this in exact
# proportion to their own measured opaque height relative to
# palm_straight's, so palm_short_wide reads shorter and palm_pair's
# taller of its two crowns reads at roughly the same height as a single
# standard palm.
PALM_BASE_HEIGHT_PX = 40

# Safety cap, expressed as a fraction of the *actual* per-eye viewport
# height (self.renderer.left_surface.get_size()[1] at Game construction
# time) rather than a fixed px count, per the "固定のマジックナンバーに
# せず比率として定数化" requirement -- initial value keeps a palm from
# ever standing taller than 80% of the visible frame.
PALM_MAX_HEIGHT_VIEWPORT_FRAC = 0.80

# Once a palm's *natural* (unclamped) height would exceed the cap above
# by more than this fraction, it's culled outright rather than drawn
# frozen at the capped size -- avoids the "stopped growing" artifact of
# holding at max size for an extended stretch while still closing in.
PALM_NEAR_CULL_MARGIN = 1.15

# -- Runtime nearest-neighbor scale cache (see _get_cached_palm_sprite) -----
# Quantizing the target height to this many px before using it as a cache
# key means many frames' worth of "roughly the same distance" palms reuse
# one already-scaled Surface instead of calling pygame.transform.scale
# again -- the N150-class mini-PC performance ask. PALM_CACHE_MAX_ENTRIES
# bounds the cache so it can never grow unbounded over a long-running
# session (oldest entry evicted first, plain LRU).
PALM_CACHE_SIZE_QUANTUM_PX = 2
PALM_CACHE_MAX_ENTRIES = 200


_palm_sprites_cache: dict = {"loaded": False, "sprites": {}}


def _load_palm_sprites() -> dict[str, pygame.Surface]:
    """Same all-or-nothing cached-load pattern as _load_enemy_sprites()/
    _load_player_sprites() (see their docstrings)."""
    if _palm_sprites_cache["loaded"]:
        return _palm_sprites_cache["sprites"]
    sprites: dict[str, pygame.Surface] = {}
    try:
        for key in PALM_SPRITE_KEYS:
            path = PALM_ASSETS_DIR / f"{key}.png"
            surf = pygame.image.load(str(path)).convert_alpha()
            if surf.get_size() != PALM_SPRITE_CANVAS_SIZE:
                sprites = {}
                break
            sprites[key] = surf
    except (pygame.error, FileNotFoundError, OSError):
        sprites = {}
    _palm_sprites_cache["sprites"] = sprites
    _palm_sprites_cache["loaded"] = True
    return sprites


def _opaque_bbox_height(surf: pygame.Surface) -> int:
    """The tree's own visible pixel height within its canvas (as opposed
    to the canvas's full height, which includes transparent margin) --
    what PALM_BASE_HEIGHT_PX's relative sizing and the near-cull check
    are both defined in terms of. Mirrors _opaque_sprite_width's
    reasoning for the enemy car sprites."""
    alpha = pygame.surfarray.pixels_alpha(surf)
    mask = alpha > 0
    if not mask.any():
        return surf.get_height()
    ys = np.where(mask.any(axis=0))[0]
    return int(ys.max() - ys.min() + 1)


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
    def __init__(self, z: float, x: float, speed: float, sprite_id: str | None = None):
        self.z = z
        self.x = x
        self.speed = speed
        # Which of ENEMY_SPRITE_KEYS this car is drawn as -- assigned once
        # in _build_traffic and never reassigned for this car's lifetime
        # (it only ever advances along z, never respawns elsewhere).
        self.sprite_id = sprite_id


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
        self._enemy_sprites = _load_enemy_sprites()
        # Precomputed once (not per frame/per draw) -- each sprite's own
        # opaque pixel width, used by _draw_traffic_car's
        # ENEMY_SPRITE_MAX_WIDTH_RATIO clamp.
        self._enemy_sprite_opaque_widths = {
            key: _opaque_sprite_width(surf) for key, surf in self._enemy_sprites.items()
        }
        # 2026-09-05, 3rd real-hardware feedback round: the two reference
        # widths _draw_traffic_car sizes every enemy car against are
        # measured here, directly off the actual Surfaces this Game loaded
        # (the same ones _draw_player_car/_draw_traffic_car blit) --
        # deliberately not the PLAYER_REFERENCE_WIDTH_PX/
        # ENEMY_REFERENCE_OPAQUE_WIDTH_PX module constants above, which
        # only cover the fallback (assets failed to load) case. Comparing
        # against a stale hardcoded number instead of what's actually
        # rendered was flagged as part of why the previous round's
        # calibration didn't match what was seen on real hardware.
        self._player_reference_width_px = (
            _opaque_sprite_width(self._player_sprites["straight"])
            if "straight" in self._player_sprites
            else PLAYER_REFERENCE_WIDTH_PX
        )
        self._enemy_reference_opaque_width_px = self._enemy_sprite_opaque_widths.get(
            "boxy_sedan", ENEMY_REFERENCE_OPAQUE_WIDTH_PX
        )

        self.palms = self._build_palms()
        self._palm_sprites = _load_palm_sprites()
        self._palm_sprite_opaque_heights = {
            key: _opaque_bbox_height(surf) for key, surf in self._palm_sprites.items()
        }
        self._palm_reference_opaque_height = self._palm_sprite_opaque_heights.get("palm_straight")
        # PALM_MAX_HEIGHT_VIEWPORT_FRAC resolved to an actual px value once,
        # against this Game's real per-eye viewport -- never a hardcoded
        # px constant (see PALM_MAX_HEIGHT_VIEWPORT_FRAC's own comment).
        _, viewport_h = self.renderer.left_surface.get_size()
        self._palm_max_height_px = PALM_MAX_HEIGHT_VIEWPORT_FRAC * viewport_h
        # sprite_id+quantized-height -> already-nearest-neighbor-scaled
        # Surface, shared by both eyes and every palm of that type/size
        # this frame or a later one -- see _get_cached_palm_sprite.
        # OrderedDict so the LRU eviction in PALM_CACHE_MAX_ENTRIES is a
        # cheap popitem(last=False).
        self._palm_scaled_cache: OrderedDict[tuple[str, int], tuple[pygame.Surface, float]] = (
            OrderedDict()
        )
        # This frame's actually-drawn (not culled/off-screen/hill-hidden)
        # palms, as (sprite_id, distance_ahead, side, anchor_screen_pos) --
        # reset and repopulated every _draw() call, read by
        # _draw_debug_overlay().
        self._palm_debug_visible: list[tuple[str, float, float, tuple[float, float]]] = []

        # Combines self.decor (procedural trees, untouched) and self.palms
        # into one list, sorted once by world_z descending (farthest
        # first) so _draw() can paint every roadside object -- old trees
        # and new palms alike -- in a single far-to-near pass, the
        # painter's-algorithm order needed for near objects to correctly
        # hide far ones. self.decor/self.palms themselves keep their own
        # original (unsorted-by-distance) order and content, unaffected --
        # this is a separate derived view, not a replacement.
        self._roadside_draw_order: list[tuple[str, float, float, object]] = sorted(
            [("tree", wz, side, scale) for wz, side, scale in self.decor]
            + [("palm", wz, side, sprite_id) for wz, side, sprite_id in self.palms],
            key=lambda item: item[1],
            reverse=True,
        )

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

        # Sprite (vehicle model) assignment happens in a second pass, after
        # every lane/position/speed above is already finalized, using its
        # own independent Random(ENEMY_SPRITE_RNG_SEED) -- never rng itself.
        # That keeps this method's rng.choice() call sequence (and so the
        # lane/position layout every existing test and replay relies on)
        # byte-for-byte identical to before sprite_id existed.
        sprite_rng = random.Random(ENEMY_SPRITE_RNG_SEED)
        for car in cars:
            car.sprite_id = sprite_rng.choices(ENEMY_SPRITE_KEYS, weights=ENEMY_SPRITE_WEIGHTS)[0]
        return cars

    def _build_decor(self) -> list[tuple[float, float, float]]:
        """(world_z, side, scale) for roadside trees, evenly spaced."""
        decor = []
        for i in range(10, len(self.segments) - 5, 14):
            side = 1.0 if (i // 14) % 2 == 0 else -1.0
            decor.append((i * SEGMENT_LENGTH, side, 1.0 + (i % 5) * 0.08))
        return decor

    def _build_palms(self) -> list[tuple[float, float, str]]:
        """(world_z, side, sprite_id) for roadside palm trees --
        PALM_PLACEMENT_START_INDEX..PALM_PLACEMENT_END_INDEX, spaced
        PALM_SPACING_MIN_SEGMENTS..PALM_SPACING_MAX_SEGMENTS segments
        apart, side/type chosen by a dedicated random.Random(
        PALM_RNG_SEED) that never touches any other rng in this file
        (see PALM_RNG_SEED's own comment) -- existing traffic/course
        generation is unaffected regardless of when this runs relative
        to them. One entry per position (palm_pair's sprite already
        depicts two trunks, so there's never a second, separately-placed
        tree at the same spot to double up with)."""
        rng = random.Random(PALM_RNG_SEED)
        palms: list[tuple[float, float, str]] = []
        idx = PALM_PLACEMENT_START_INDEX
        side = rng.choice((-1.0, 1.0))
        streak = 0
        max_idx = min(PALM_PLACEMENT_END_INDEX, len(self.segments) - 1)
        while True:
            idx += rng.randint(PALM_SPACING_MIN_SEGMENTS, PALM_SPACING_MAX_SEGMENTS)
            if idx > max_idx:
                break
            # Force a flip once the run hits the cap; otherwise flip with
            # even odds -- keeps the left/right split close to 50:50
            # while capping any one side's run length, and avoids a
            # perfectly rigid left-right-left-right alternation too.
            if streak >= PALM_SAME_SIDE_MAX_STREAK or rng.random() < 0.5:
                side = -side
                streak = 1
            else:
                streak += 1
            if rng.random() < PALM_PAIR_PROBABILITY:
                sprite_id = "palm_pair"
            else:
                sprite_id = rng.choice(PALM_NON_PAIR_KEYS)
            palms.append((idx * SEGMENT_LENGTH, side, sprite_id))
        return palms

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
        self._palm_debug_visible = []
        for kind, wz, side, extra in self._roadside_draw_order:
            if kind == "tree":
                self._draw_decor_object(wz, side, extra)
            else:
                self._draw_palm(wz, side, extra)
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

    def _get_cached_palm_sprite(self, sprite_id: str, target_h_px: float) -> tuple[pygame.Surface, float]:
        """Returns (scaled_surface, actual_scale_applied) for `sprite_id`
        at (quantized) `target_h_px` tall, computing and caching a fresh
        pygame.transform.scale() only on a cache miss. `actual_scale_applied`
        reflects the quantized size actually produced, not the raw
        `target_h_px` requested -- callers must use it (not their own
        pre-quantization scale) for anchor placement, or the drawn
        sprite's root would drift a fraction of a px from where the math
        says it should be."""
        sprite = self._palm_sprites[sprite_id]
        native_w, native_h = sprite.get_size()
        q = PALM_CACHE_SIZE_QUANTUM_PX
        quantized_h = max(q, round(target_h_px / q) * q)
        key = (sprite_id, quantized_h)
        cached = self._palm_scaled_cache.get(key)
        if cached is not None:
            self._palm_scaled_cache.move_to_end(key)
            return cached
        actual_scale = quantized_h / native_h
        quantized_w = max(1, round(native_w * actual_scale))
        # pygame.transform.scale (not smoothscale) -- nearest-neighbor
        # sampling, no interpolation/antialiasing, matching the source
        # pixel art.
        scaled = pygame.transform.scale(sprite, (quantized_w, quantized_h))
        result = (scaled, actual_scale)
        self._palm_scaled_cache[key] = result
        if len(self._palm_scaled_cache) > PALM_CACHE_MAX_ENTRIES:
            self._palm_scaled_cache.popitem(last=False)  # evict oldest (LRU)
        return result

    def _draw_palm(self, world_z: float, side: float, sprite_id: str) -> None:
        """Same projection/culling/hill-occlusion structure as
        _draw_decor_object (world_z ahead of the camera, offset outside
        the road edge by the same PALM_ROAD_SIDE_OFFSET convention) --
        only the final draw call differs (a cached, nearest-neighbor-
        scaled sprite instead of draw_tree()'s procedural lines)."""
        seg = self._segment_at(world_z)
        cam_x = self._road_center_x()
        cam_y = self.cam_elevation
        cam_z = self.player.z
        width, height = self.renderer.left_surface.get_size()
        world_x = seg.world_x + side * PALM_ROAD_SIDE_OFFSET
        world_y = elevation_at(self.segments, world_z)
        sx, sy, sw, tz = project(world_x, world_y, world_z, cam_x, cam_y, cam_z, width, height)
        if tz > SEGMENT_LENGTH * (DRAW_DISTANCE + 1) or world_z < cam_z:
            return
        if not self._sprite_visible(world_z, sy):
            return

        sprite = self._palm_sprites.get(sprite_id)
        opaque_h = self._palm_sprite_opaque_heights.get(sprite_id)
        reference_h = self._palm_reference_opaque_height
        if sprite is None or not opaque_h or not reference_h:
            # Missing/broken palm assets -- fall back to the same
            # procedural placeholder the existing roadside trees use,
            # rather than drawing nothing or crashing.
            def draw_fallback(surf: pygame.Surface, ox: float) -> None:
                draw_tree(surf, sx + ox, sy, max(0.3, sw / (ROAD_WIDTH * 6)), TREE_COLOR)

            self.renderer.draw_world(tz, draw_fallback)
            return

        distance_scale = max(0.3, sw / (ROAD_WIDTH * 6))  # same formula _draw_decor_object uses
        height_ratio = opaque_h / reference_h  # this palm's own height relative to palm_straight
        target_h_px = PALM_BASE_HEIGHT_PX * distance_scale * height_ratio
        if target_h_px > self._palm_max_height_px * PALM_NEAR_CULL_MARGIN:
            return  # too close -- cull promptly rather than freeze at the capped size
        target_h_px = min(target_h_px, self._palm_max_height_px)

        scaled_sprite, sprite_scale = self._get_cached_palm_sprite(sprite_id, target_h_px)
        anchor_x, anchor_y = PALM_SPRITE_ANCHOR
        dest_x = sx - anchor_x * sprite_scale
        dest_y = sy - anchor_y * sprite_scale

        self._palm_debug_visible.append((sprite_id, world_z - self.player.z, side, (sx, sy)))

        def draw(surf: pygame.Surface, ox: float) -> None:
            surf.blit(scaled_sprite, (dest_x + ox, dest_y))

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

        # draw_car()'s rectangle fallback still uses this plain
        # distance-based perspective scale, unchanged. The sprite path
        # below uses ENEMY_SPRITE_TARGET_RATIO_POINTS instead (see its
        # docstring for why) -- `scale` itself no longer drives sprite
        # size at all, only the fallback rectangle.
        scale = max(0.35, sw / (ROAD_WIDTH * 3.5))
        sprite = self._enemy_sprites.get(car.sprite_id)
        scaled_sprite = None
        dest_x = dest_y = 0.0
        if sprite is not None:
            target_reference_w = self._player_reference_width_px * _enemy_target_ratio(tz)
            sprite_scale = target_reference_w / self._enemy_reference_opaque_width_px
            # Hard cap: whatever the curve above says, this car's own
            # visible width may never exceed ENEMY_SPRITE_MAX_WIDTH_RATIO
            # of the player's on-screen width.
            opaque_w = self._enemy_sprite_opaque_widths.get(car.sprite_id)
            if opaque_w:
                max_sprite_scale = (
                    self._player_reference_width_px * ENEMY_SPRITE_MAX_WIDTH_RATIO
                ) / opaque_w
                sprite_scale = min(sprite_scale, max_sprite_scale)
            sprite_w, sprite_h = sprite.get_size()
            scaled_w = max(1, round(sprite_w * sprite_scale))
            scaled_h = max(1, round(sprite_h * sprite_scale))
            # pygame.transform.scale (not smoothscale) -- nearest-neighbor
            # sampling, no interpolation/antialiasing, matching the source
            # pixel art. Scaled once here (not inside draw()) so both eyes
            # blit the exact same surface at the exact same size.
            scaled_sprite = pygame.transform.scale(sprite, (scaled_w, scaled_h))
            anchor_x, anchor_y = ENEMY_SPRITE_ANCHOR
            dest_x = sx - anchor_x * sprite_scale
            dest_y = sy - anchor_y * sprite_scale

        def draw(surf: pygame.Surface, ox: float) -> None:
            if scaled_sprite is not None:
                surf.blit(scaled_sprite, (dest_x + ox, dest_y))
            else:
                draw_car(surf, sx + ox, sy, scale, TRAFFIC_COLOR)

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

    def _palm_debug_line(self) -> str:
        """"表示中のヤシの木の本数、sprite_id、Z距離、左右どちら側か、
        根元アンカー位置" -- count of everything _draw_palm actually drew
        this frame (not culled/off-screen/hill-hidden), plus the nearest
        one's own detail as a representative sample (all of them won't
        fit on one debug line)."""
        visible = self._palm_debug_visible
        if not visible:
            return "palms: 0 visible"
        nearest = min(visible, key=lambda p: p[1])
        sprite_id, distance, side, (anchor_x, anchor_y) = nearest
        side_label = "right" if side > 0 else "left"
        return (
            f"palms: {len(visible)} visible  nearest={sprite_id} z={distance:6.1f}"
            f" side={side_label}  anchor=({anchor_x:.0f},{anchor_y:.0f})"
        )

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
            self._palm_debug_line(),
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
