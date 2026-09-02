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


def _add_section(segments: list[Segment], curve: float, length: int) -> None:
    ramp = min(20, max(1, length // 3))
    hold = max(0, length - 2 * ramp)
    for i in range(ramp):
        segments.append(Segment(index=len(segments), curve=curve * (i / ramp)))
    for _ in range(hold):
        segments.append(Segment(index=len(segments), curve=curve))
    for i in range(ramp):
        segments.append(Segment(index=len(segments), curve=curve * (1 - i / ramp)))


# One lap's worth of curve sections: (curve strength, length in segments).
# curve > 0 bends right, curve < 0 bends left. Chosen (and tuned by
# rendering test frames, see docs/PHASE2_RACE_LOG.md) so the whole course
# takes roughly 60-90s to finish at a believable arcade cruising speed.
TRACK_SECTIONS: list[tuple[float, int]] = [
    (0.0, 50),
    (0.10, 60),
    (0.0, 30),
    (-0.14, 70),
    (0.0, 40),
    (0.08, 40),
    (-0.08, 40),
    (0.0, 50),
    (0.16, 50),
    (0.0, 60),
    (-0.10, 50),
    (0.0, 80),
]


def build_track(sections: list[tuple[float, int]] = TRACK_SECTIONS) -> list[Segment]:
    segments: list[Segment] = []
    for curve, length in sections:
        _add_section(segments, curve, length)

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
