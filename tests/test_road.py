import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from road import SEGMENT_LENGTH, build_track, segment_at, track_length


def test_track_has_segments_and_positive_length():
    segs = build_track()
    assert len(segs) > 100
    assert track_length(segs) == len(segs) * SEGMENT_LENGTH


def test_track_completes_in_a_reasonable_time_at_arcade_speed():
    # Sanity check for the "60-90s course" requirement: at a plausible
    # average cruising speed, the course should take roughly that long.
    segs = build_track()
    length = track_length(segs)
    avg_speed = 30.0  # world units/sec, well under MAX_SPEED in game.py
    assert 40.0 <= length / avg_speed <= 120.0


def test_world_x_stays_within_a_visually_reasonable_range():
    # A pathologically large curve constant would fling the road so far
    # sideways it goes off-screen (this caught a real bug during tuning).
    segs = build_track()
    xs = [s.world_x for s in segs]
    assert max(xs) - min(xs) < 2000


def test_segment_at_clamps_to_track_bounds():
    segs = build_track()
    assert segment_at(segs, -100).index == 0
    assert segment_at(segs, 10**9).index == segs[-1].index


def test_straight_section_has_zero_curve():
    segs = build_track()
    assert segs[0].curve == 0.0
