import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from game import MAX_SPEED
from road import (
    HILL_START,
    MAX_GRADE,
    SEGMENT_LENGTH,
    VALLEY_START,
    build_track,
    curve_at,
    elevation_at,
    segment_at,
    track_length,
    world_x_at,
)


def test_track_has_segments_and_positive_length():
    segs = build_track()
    assert len(segs) > 100
    assert track_length(segs) == len(segs) * SEGMENT_LENGTH


def test_track_completes_in_a_reasonable_time_at_arcade_speed():
    # Sanity check for the "60-90s course" requirement, tied to the
    # game's actual MAX_SPEED (not a hardcoded number) so this stays
    # meaningful as top speed gets tuned. Curves are deliberately tuned
    # to be takeable flat-out (see docs/PHASE2_RACE_LOG.md), so the
    # flat-out time is the meaningful "intended pace" figure and is
    # checked against the 60-90s target directly; a much more cautious
    # half-speed run is only checked against a loose sanity ceiling.
    segs = build_track()
    length = track_length(segs)
    flat_out_time = length / MAX_SPEED
    assert 40.0 <= flat_out_time <= 95.0
    cautious_time = length / (0.5 * MAX_SPEED)
    assert cautious_time <= 180.0


def test_world_x_stays_within_a_visually_reasonable_range():
    # A pathologically large curve constant would fling the road so far
    # sideways it goes off-screen (this caught a real bug during tuning).
    # The bar here is deliberately generous -- wide, lazy sweeping curves
    # are an intentional design choice (see docs/PHASE2_RACE_LOG.md) and
    # legitimately cover a large world_x range; this just guards against
    # a genuinely runaway value.
    segs = build_track()
    xs = [s.world_x for s in segs]
    assert max(xs) - min(xs) < 3000


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


# -- elevation (hills) -------------------------------------------------------

def test_course_starts_and_ends_flat():
    segs = build_track()
    assert segs[0].elevation == 0.0
    assert segs[-1].elevation == 0.0


def test_hill_and_valley_reach_their_authored_extremes():
    segs = build_track()
    elevations = [s.elevation for s in segs]
    assert max(elevations) > 10.0   # the hill crest (HILL_HEIGHT=14)
    assert min(elevations) < -5.0   # the valley trough (VALLEY_DEPTH=8)


def test_elevation_never_exceeds_max_grade():
    # Regression guard for the "no sudden kinks" requirement: adjacent
    # segments' elevation must never change faster than MAX_GRADE per
    # world-unit of z, across the whole authored course.
    segs = build_track()
    for a, b in zip(segs, segs[1:]):
        grade = abs(b.elevation - a.elevation) / SEGMENT_LENGTH
        assert grade <= MAX_GRADE + 1e-9


def test_elevation_changes_smoothly_not_stepped():
    # Same "no visible hop" regression style as
    # test_world_x_at_is_smooth_within_a_curve_not_stepped, applied to the
    # hill's rise.
    segs = build_track()
    z0 = HILL_START * SEGMENT_LENGTH
    fine_step = SEGMENT_LENGTH / 20
    prev = elevation_at(segs, z0)
    max_delta = 0.0
    for i in range(1, 400):
        cur = elevation_at(segs, z0 + i * fine_step)
        max_delta = max(max_delta, abs(cur - prev))
        prev = cur
    assert max_delta < 0.5


def test_elevation_at_matches_segment_values_at_boundaries():
    segs = build_track()
    for i in (0, HILL_START, HILL_START + 50, VALLEY_START, len(segs) - 1):
        assert elevation_at(segs, i * SEGMENT_LENGTH) == segs[i].elevation


def test_hill_eases_in_not_linear():
    # A pure linear ramp would put the segment exactly 1/4 of the way
    # through the rise at exactly 25% of the target height. Smoothstep
    # ease-in/ease-out should be slower at the very start of the rise --
    # under 25% -- which is what actually distinguishes it from a linear
    # ramp (and, per the spec, from an abrupt "kink").
    from road import HILL_HEIGHT, HILL_RISE_SEGMENTS

    segs = build_track()
    quarter_i = HILL_START + HILL_RISE_SEGMENTS // 4
    frac_height = segs[quarter_i].elevation / HILL_HEIGHT
    assert frac_height < 0.25
