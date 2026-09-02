import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import Rect, default_config, load_config, save_config


def test_default_config_viewports_are_onscreen_and_symmetric():
    cfg = default_config()
    assert 0 <= cfg.left_viewport.x < cfg.output_width
    assert 0 <= cfg.right_viewport.x < cfg.output_width
    assert cfg.left_viewport.width == cfg.right_viewport.width
    assert cfg.left_viewport.height == cfg.right_viewport.height
    left_cx, _ = cfg.left_viewport.center()
    right_cx, _ = cfg.right_viewport.center()
    assert left_cx < right_cx  # left is actually left of right


def test_save_and_load_roundtrip(tmp_path):
    path = tmp_path / "config.json"
    cfg = default_config()
    cfg.left_viewport.x = 111
    cfg.parallax_scale = 0.5
    cfg.swap_eyes = True
    save_config(cfg, path)

    loaded = load_config(path)
    assert loaded.left_viewport.x == 111
    assert loaded.parallax_scale == 0.5
    assert loaded.swap_eyes is True


def test_missing_file_falls_back_to_defaults(tmp_path):
    path = tmp_path / "does_not_exist.json"
    cfg = load_config(path)
    default = default_config()
    assert cfg.output_width == default.output_width
    assert cfg.left_viewport.width == default.left_viewport.width


def test_corrupt_json_falls_back_to_defaults(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("{ not valid json", encoding="utf-8")
    cfg = load_config(path)
    default = default_config()
    assert cfg.output_width == default.output_width


def test_invalid_values_fall_back_to_defaults(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"left_viewport": "banana"}), encoding="utf-8")
    cfg = load_config(path)
    default = default_config()
    assert cfg.left_viewport.width == default.left_viewport.width


def test_rect_clamp_recovers_fully_offscreen_rect():
    rect = Rect(x=-10000, y=-10000, width=280, height=200)
    rect.clamp(1024, 600)
    # must still be at least partially visible
    assert rect.x + rect.width > 0
    assert rect.y + rect.height > 0
    assert rect.x < 1024
    assert rect.y < 600


def test_rect_clamp_enforces_minimum_size():
    rect = Rect(x=0, y=0, width=1, height=1)
    rect.clamp(1024, 600)
    assert rect.width >= 20
    assert rect.height >= 20
