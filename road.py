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
ROAD_WIDTH = 9.0      # half-width of the drivable road, world units
RUMBLE_LENGTH = 3     # segments per alternating rumble-strip color band
DRAW_DISTANCE = 100   # segments rendered ahead of the camera


@dataclass
class Segment:
    index: int
    curve: float = 0.0
    world_x: float = 0.0      # accumulated lateral center offset
    world_z: float = 0.0      # distance along the track from the start
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
# still allowing genuine S-curves and left/right bends. Chosen (and
# tuned by rendering test frames, see docs/PHASE2_RACE_LOG.md) so the
# whole course takes roughly 60-90s at a believable arcade cruising speed.
TRACK_EVENTS: list[tuple[str, float, int]] = [
    ("straight", 0.0, 60),
    ("bend", 0.30, 40),    # quick right bend, back to straight
    ("straight", 0.0, 45),
    ("bend", -0.40, 50),   # sharper left bend
    ("straight", 0.0, 45),
    ("bend", 0.35, 70),    # lazier S-curve (right then left)
    ("straight", 0.0, 50),
    ("bend", 0.45, 45),    # sharp right bend
    ("straight", 0.0, 45),
    ("bend", -0.30, 45),   # left bend
    ("straight", 0.0, 55),
    ("bend", 0.40, 35),    # snappy right-left chicane
    ("straight", 0.0, 90),  # final straight to the finish
]


def build_track(events: list[tuple[str, float, int]] = TRACK_EVENTS) -> list[Segment]:
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

    return segments


def segment_at(segments: list[Segment], world_z: float) -> Segment:
    """The segment a given world Z position falls on. Clamped to the
    track's ends rather than wrapping -- this is a point-to-point course,
    not an infinite loop."""
    idx = int(world_z / SEGMENT_LENGTH)
    idx = max(0, min(len(segments) - 1, idx))
    return segments[idx]


def track_length(segments: list[Segment]) -> float:
    return len(segments) * SEGMENT_LENGTH
