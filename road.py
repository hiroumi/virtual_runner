"""Segment-based pseudo-3D road model (Phase 2 game).

Classic "OutRun-style" technique: the track is a long line of fixed-length
segments running away from the camera along world Z. Each segment carries
a `curve` value; integrating curve -> direction -> world_x twice gives a
smoothly bending road without ever needing real 3D geometry. Projecting a
segment to screen space only needs its distance from the camera.

World-unit scale here is deliberately the *same* one already used by
stereo_renderer/config (screen_depth=20, mountains at depth~250-300 in the
Phase 2 test scene) so a segment's distance from the camera can be fed
straight into calculate_disparity() with no unit conversion.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

SEGMENT_LENGTH = 3.0  # world units per segment
ROAD_WIDTH = 11.0     # half-width of the drivable road, world units (3 lanes)
RUMBLE_LENGTH = 3     # segments per alternating rumble-strip color band
DRAW_DISTANCE = 100   # segments rendered ahead of the camera

# Steepest allowed |delta elevation| per world-unit of z, checked by
# tests/test_road.py against every authored hill. A safety/design ceiling
# (not a physics limit) that keeps hills readable through the DRAW_DISTANCE
# window instead of a wall; see ELEVATION_CHECKPOINTS below for the actual
# authored values, which stay well under this on purpose so there's room to
# steepen them later the same way MAX_SPEED was tuned up over time.
MAX_GRADE = 0.09


@dataclass
class Segment:
    index: int
    curve: float = 0.0
    world_x: float = 0.0      # accumulated lateral center offset
    world_z: float = 0.0      # distance along the track from the start
    elevation: float = 0.0    # world_y of the road surface at this segment
    looks_dark: bool = False  # alternating road/rumble/grass color band
    cars: list = field(default_factory=list)   # indices into Game.traffic
    decor: list = field(default_factory=list)  # (side, kind) roadside decor


def _add_straight(segments: list[Segment], length: int) -> None:
    for _ in range(length):
        segments.append(Segment(index=len(segments), curve=0.0))


def _add_bend(segments: list[Segment], peak: float, length: int) -> None:
    """A self-cancelling curve event: curve follows one full sine cycle
    (0 -> +peak -> 0 -> -peak -> 0), so the *heading* (the running
    direction total in build_track) returns to exactly what it was
    before the bend. That's what makes the following straight actually
    render straight instead of carrying on at a permanent diagonal --
    only the lateral position (world_x) ends up shifted, which is what a
    real curve-then-straight-again road segment should look like.

    peak > 0 reads as a right-then-left bend (i.e. primarily rightward);
    peak < 0 is primarily leftward. A short `length` gives a snappy
    single bend; a longer one reads more like a lazy S-curve.
    """
    for i in range(length):
        t = i / length
        curve = peak * math.sin(2 * math.pi * t)
        segments.append(Segment(index=len(segments), curve=curve))


# One lap's worth of straights and bends, in order. Bends are
# self-cancelling (see _add_bend) so the road promptly reads as straight
# again right after each one -- no lingering diagonal drift -- while
# still allowing genuine S-curves and left/right bends. The big sweeping
# bends are deliberately low-peak/long rather than high-peak/short, so
# they can be taken at speed instead of forcing a lift off the gas; only
# the one chicane near the end is kept short and snappy on purpose.
# Chosen (and tuned by rendering test frames and driving simulations, see
# docs/PHASE2_RACE_LOG.md) so the whole course takes roughly 60-90s at a
# believable arcade cruising speed.
#
# Bend length was scaled with game.MAX_SPEED's increases so time-in-curve
# -- and therefore both the safety-margin math and the felt duration of
# each bend -- stays the same as top speed climbs, instead of the same
# bend suddenly feeling more sudden because it's now covered in less
# real time. On top of that, every big sweeping bend here has its length
# roughly doubled again and its peak curve roughly halved (peak*length
# held constant, so the safety margin doesn't change) to read as a wide,
# lazy highway curve you can hold flat-out through, rather than a
# tighter bend that's merely survivable at speed. The one chicane is
# only doubled in length, not halved in peak, since it's meant to stay a
# short, snappy flick for contrast.
TRACK_EVENTS: list[tuple[str, float, int]] = [
    ("straight", 0.0, 120),
    ("bend", 0.09, 210),   # long, gentle right sweep -- flat-out speed
    ("straight", 0.0, 115),
    ("bend", -0.11, 240),  # long, gentle left sweep
    ("straight", 0.0, 115),
    ("bend", 0.10, 290),   # lazy, wide S-curve
    ("straight", 0.0, 120),
    ("bend", 0.14, 190),   # medium right sweep, a bit more character
    ("straight", 0.0, 115),
    ("bend", -0.10, 190),  # medium left sweep
    ("straight", 0.0, 125),
    ("bend", 0.32, 110),   # snappy right-left chicane (kept tight on purpose)
    ("straight", 0.0, 160),  # final straight to the finish
]


# -- Elevation (hills) ------------------------------------------------------
# Vertical companion to the curve/world_x system above, but built
# differently on purpose: curve is integrated segment-by-segment (so bends
# self-cancel, see _add_bend), while elevation is authored as a short list
# of (segment_index, elevation) checkpoints and *smoothstep*-interpolated
# between them by apply_elevation(). That gives each hill an explicit start
# and end index (easy to place relative to TRACK_EVENTS, e.g. "overlap the
# tail of this bend") and a guaranteed ease-in/ease-out at both ends -- no
# risk of an integration error compounding over a long course the way a
# hand-tuned per-segment slope could.
HILL_HEIGHT = 14.0     # world units the first hill rises -- "strength" knob
VALLEY_DEPTH = 8.0     # world units the second feature (a dip) descends
HILL_RISE_SEGMENTS = 90     # segments used for each smooth transition --
HILL_CREST_SEGMENTS = 30    # "how many segments the height change spans"
HILL_FALL_SEGMENTS = 150    # (longer than the rise: "a bit long a descent")
VALLEY_DOWN_SEGMENTS = 50
VALLEY_HOLD_SEGMENTS = 15
VALLEY_UP_SEGMENTS = 50

# Placed mid-course on purpose (not a full-track redesign): HILL_START sits
# in the straight right after the "lazy, wide S-curve" bend and its descent
# deliberately runs on into the start of the following "medium right sweep"
# bend (TRACK_EVENTS index ~1210-1400, peak 0.14) -- a curve+grade section,
# but a gentle/medium one, not stacked with the sharp chicane. VALLEY_START
# sits in the straight before the chicane, clear of any curve, with a 5+
# segment flat buffer before the chicane begins at index 1830. See
# docs/PHASE2_RACE_LOG.md for the full placement reasoning.
HILL_START = 1095
VALLEY_START = 1710


def _smoothstep(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return t * t * (3.0 - 2.0 * t)


def _hill_checkpoints() -> list[tuple[int, float]]:
    h0 = HILL_START
    h1 = h0 + HILL_RISE_SEGMENTS
    h2 = h1 + HILL_CREST_SEGMENTS
    h3 = h2 + HILL_FALL_SEGMENTS
    v0 = VALLEY_START
    v1 = v0 + VALLEY_DOWN_SEGMENTS
    v2 = v1 + VALLEY_HOLD_SEGMENTS
    v3 = v2 + VALLEY_UP_SEGMENTS
    return [
        (h0, 0.0), (h1, HILL_HEIGHT), (h2, HILL_HEIGHT), (h3, 0.0),
        (v0, 0.0), (v1, -VALLEY_DEPTH), (v2, -VALLEY_DEPTH), (v3, 0.0),
    ]


ELEVATION_CHECKPOINTS: list[tuple[int, float]] = _hill_checkpoints()


def apply_elevation(
    segments: list[Segment],
    checkpoints: list[tuple[int, float]] = ELEVATION_CHECKPOINTS,
) -> None:
    """Sets seg.elevation for every segment by smoothstep-interpolating
    between consecutive (segment_index, elevation) checkpoints -- the
    ease-in/ease-out this gives at every checkpoint is what keeps a hill
    from ever reading as a kink. Segments before the first checkpoint or
    after the last hold flat at that checkpoint's value (the course starts
    and ends flat, since ELEVATION_CHECKPOINTS' first/last values are 0)."""
    if not checkpoints:
        return
    checkpoints = sorted(checkpoints, key=lambda c: c[0])
    for seg in segments:
        i = seg.index
        if i <= checkpoints[0][0]:
            seg.elevation = checkpoints[0][1]
            continue
        if i >= checkpoints[-1][0]:
            seg.elevation = checkpoints[-1][1]
            continue
        for (i0, h0), (i1, h1) in zip(checkpoints, checkpoints[1:]):
            if i0 <= i <= i1:
                t = 0.0 if i1 == i0 else (i - i0) / (i1 - i0)
                seg.elevation = h0 + (h1 - h0) * _smoothstep(t)
                break


def build_track(
    events: list[tuple[str, float, int]] = TRACK_EVENTS,
    elevation_checkpoints: list[tuple[int, float]] = ELEVATION_CHECKPOINTS,
) -> list[Segment]:
    segments: list[Segment] = []
    for kind, peak, length in events:
        if kind == "straight":
            _add_straight(segments, length)
        elif kind == "bend":
            _add_bend(segments, peak, length)
        else:
            raise ValueError(f"unknown track event kind: {kind!r}")

    direction = 0.0
    world_x = 0.0
    for i, seg in enumerate(segments):
        direction += seg.curve
        world_x += direction
        seg.world_x = world_x
        seg.world_z = i * SEGMENT_LENGTH
        seg.looks_dark = (i // RUMBLE_LENGTH) % 2 == 0

    apply_elevation(segments, elevation_checkpoints)

    return segments


def segment_at(segments: list[Segment], world_z: float) -> Segment:
    """The segment a given world Z position falls on. Clamped to the
    track's ends rather than wrapping -- this is a point-to-point course,
    not an infinite loop."""
    idx = int(world_z / SEGMENT_LENGTH)
    idx = max(0, min(len(segments) - 1, idx))
    return segments[idx]


def _interp_index_frac(segments: list[Segment], world_z: float) -> tuple[int, int, float]:
    idx_f = world_z / SEGMENT_LENGTH
    i0 = max(0, min(len(segments) - 1, int(idx_f)))
    i1 = min(i0 + 1, len(segments) - 1)
    frac = max(0.0, min(1.0, idx_f - i0))
    return i0, i1, frac


def world_x_at(segments: list[Segment], world_z: float) -> float:
    """world_x at an arbitrary (non-segment-aligned) world_z, linearly
    interpolated between the two nearest segments. During a curve,
    consecutive segments' world_x can differ by a large fraction of the
    road width, so using the coarse per-segment value directly as the
    camera's lateral reference makes the whole view visibly hop once per
    segment (roughly every 60-70ms at speed) instead of panning smoothly
    -- this is what fixes that."""
    i0, i1, frac = _interp_index_frac(segments, world_z)
    return segments[i0].world_x * (1 - frac) + segments[i1].world_x * frac


def curve_at(segments: list[Segment], world_z: float) -> float:
    """Same interpolation as world_x_at, for curve -- smooths the
    centrifugal force and the cornering visual cues (background pan, car
    lean) instead of having them step once per segment."""
    i0, i1, frac = _interp_index_frac(segments, world_z)
    return segments[i0].curve * (1 - frac) + segments[i1].curve * frac


def elevation_at(segments: list[Segment], world_z: float) -> float:
    """Same interpolation as world_x_at/curve_at, for elevation -- lets the
    camera-height reference and any object's projected height be sampled
    continuously instead of stepping once per segment."""
    i0, i1, frac = _interp_index_frac(segments, world_z)
    return segments[i0].elevation * (1 - frac) + segments[i1].elevation * frac


def track_length(segments: list[Segment]) -> float:
    return len(segments) * SEGMENT_LENGTH
