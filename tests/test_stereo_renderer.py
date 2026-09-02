import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import default_config
from stereo_renderer import calculate_disparity


def test_disparity_is_zero_at_screen_depth():
    cfg = default_config()
    d = calculate_disparity(cfg.screen_depth, 1.0, cfg)
    assert abs(d) < 1e-6


def test_near_objects_get_positive_inward_disparity():
    cfg = default_config()
    near = calculate_disparity(cfg.screen_depth / 4, 1.0, cfg)
    assert near > 0


def test_far_objects_get_small_negative_or_zero_disparity():
    cfg = default_config()
    far = calculate_disparity(cfg.screen_depth * 20, 1.0, cfg)
    assert far <= 0
    assert far >= -cfg.max_negative_disparity_px


def test_disparity_monotonically_decreases_as_depth_increases():
    cfg = default_config()
    depths = [1.0, 3.0, 6.0, 12.0, 25.0, 50.0, 200.0]
    values = [calculate_disparity(d, 1.0, cfg) for d in depths]
    for a, b in zip(values, values[1:]):
        assert a >= b


def test_positive_disparity_never_exceeds_safety_cap():
    cfg = default_config()
    extreme_near = calculate_disparity(0.001, 5.0, cfg)  # absurd depth, absurd scale
    assert extreme_near <= cfg.max_disparity_px + 1e-6


def test_negative_disparity_never_exceeds_safety_cap():
    cfg = default_config()
    extreme_far = calculate_disparity(1_000_000.0, 5.0, cfg)
    assert extreme_far >= -cfg.max_negative_disparity_px - 1e-6


def test_zero_parallax_scale_means_zero_disparity_everywhere():
    cfg = default_config()
    for depth in (1.0, 10.0, 100.0):
        assert calculate_disparity(depth, 0.0, cfg) == 0.0


def test_non_positive_depth_does_not_crash_or_blow_up():
    cfg = default_config()
    d = calculate_disparity(0.0, 1.0, cfg)
    assert d <= cfg.max_disparity_px
    d2 = calculate_disparity(-5.0, 1.0, cfg)
    assert d2 <= cfg.max_disparity_px
