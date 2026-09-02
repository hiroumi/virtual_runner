import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from road import SEGMENT_LENGTH, build_track, curve_at, segment_at, track_length, world_x_at


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


def test_world_x_at_matches_segment_values_at_boundaries():
    segs = build_track()
    for i in (0, 50, 200, len(segs) - 1):
        assert world_x_at(segs, i * SEGMENT_LENGTH) == segs[i].world_x


def test_curve_at_matches_segment_values_at_boundaries():
    segs = build_track()
    for i in (0, 50, 200, len(segs) - 1):
        assert curve_at(segs, i * SEGMENT_LENGTH) == segs[i].curve


def test_world_x_at_is_smooth_within_a_curve_not_stepped():
    # Regression test: using the coarse per-segment world_x as a
    # continuously-sampled camera reference made the whole view visibly
    # hop once per segment while cornering (reported as choppy/janky
    # cornering). world_x_at must vary smoothly with world_z instead of
    # jumping by a large fraction of a segment's world_x delta in a
    # single small step.
    segs = build_track()
    # segments 390-420 are inside one of the sharper bends (see
    # docs/PHASE2_RACE_LOG.md tuning notes).
    z0 = 390 * SEGMENT_LENGTH
    fine_step = SEGMENT_LENGTH / 20
    prev = world_x_at(segs, z0)
    max_delta = 0.0
    for i in range(1, 400):
        cur = world_x_at(segs, z0 + i * fine_step)
        max_delta = max(max_delta, abs(cur - prev))
        prev = cur
    # A per-segment jump in this region is > 3 world units (see the
    # bug report); a fine step should move a small, bounded fraction
    # of that.
    assert max_delta < 0.5


def test_curve_at_interpolates_between_segments():
    segs = build_track()
    # Find two adjacent segments with different curve values.
    for i in range(len(segs) - 1):
        if segs[i].curve != segs[i + 1].curve:
            midpoint = curve_at(segs, (i + 0.5) * SEGMENT_LENGTH)
            expected = (segs[i].curve + segs[i + 1].curve) / 2
            assert abs(midpoint - expected) < 1e-9
            break
    else:
        raise AssertionError("expected at least one curve change between segments")
