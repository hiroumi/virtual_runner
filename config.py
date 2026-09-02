"""Configuration model, defaults, and JSON persistence for the stereo display.

This module is shared by the Phase 1 calibrator and (later) the Phase 2 game.
Only the *result* of calibration (absolute viewport rectangles, swap/flip
flags, parallax scale) is persisted -- the interactive adjustment helpers
(eye gap, global move, per-eye offset) in the calibrator are just ways of
*editing* these rectangles, not separate persisted fields.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

CONFIG_PATH = Path(__file__).resolve().parent / "config.json"

# Minimum viewport size we ever allow (pixels). Below this the picture is
# not useful and something has clearly gone wrong (e.g. corrupt config).
MIN_VIEWPORT_SIZE = 20

# How many pixels of a viewport must remain on-screen. Prevents a viewport
# from being pushed fully off-screen and "disappearing" with no way back
# other than editing config.json by hand.
MIN_VISIBLE_MARGIN = 20


@dataclass
class Rect:
    x: int
    y: int
    width: int
    height: int

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict, default: "Rect") -> "Rect":
        try:
            return Rect(
                x=int(d["x"]),
                y=int(d["y"]),
                width=int(d["width"]),
                height=int(d["height"]),
            )
        except (KeyError, TypeError, ValueError):
            return Rect(default.x, default.y, default.width, default.height)

    def center(self) -> tuple[int, int]:
        return self.x + self.width // 2, self.y + self.height // 2

    def clamp(self, screen_w: int, screen_h: int) -> None:
        """Keep the rect at a sane size and at least partly on-screen."""
        self.width = max(MIN_VIEWPORT_SIZE, min(self.width, screen_w))
        self.height = max(MIN_VIEWPORT_SIZE, min(self.height, screen_h))
        min_x = -(self.width - MIN_VISIBLE_MARGIN)
        max_x = screen_w - MIN_VISIBLE_MARGIN
        min_y = -(self.height - MIN_VISIBLE_MARGIN)
        max_y = screen_h - MIN_VISIBLE_MARGIN
        self.x = max(min_x, min(self.x, max_x))
        self.y = max(min_y, min(self.y, max_y))


def _default_viewports(screen_w: int, screen_h: int) -> tuple[Rect, Rect]:
    """Safe placeholder layout: two small regions left-of-center and
    right-of-center. NOT derived from real device measurements -- this is
    only a starting point for the calibrator, see README."""
    width, height = 280, 200
    cy = screen_h // 2
    left_cx = screen_w // 4
    right_cx = screen_w - screen_w // 4
    left = Rect(left_cx - width // 2, cy - height // 2, width, height)
    right = Rect(right_cx - width // 2, cy - height // 2, width, height)
    return left, right


@dataclass
class Config:
    output_width: int = 1024
    output_height: int = 600
    fullscreen: bool = False
    left_viewport: Rect = field(default_factory=lambda: Rect(116, 200, 280, 200))
    right_viewport: Rect = field(default_factory=lambda: Rect(628, 200, 280, 200))
    swap_eyes: bool = False
    flip_left_h: bool = False
    flip_left_v: bool = False
    flip_right_h: bool = False
    flip_right_v: bool = False
    parallax_scale: float = 1.0
    content_scale: float = 1.0

    def clamp(self) -> None:
        self.output_width = max(320, int(self.output_width))
        self.output_height = max(240, int(self.output_height))
        self.left_viewport.clamp(self.output_width, self.output_height)
        self.right_viewport.clamp(self.output_width, self.output_height)
        self.parallax_scale = max(0.0, min(2.0, float(self.parallax_scale)))
        self.content_scale = max(0.25, min(3.0, float(self.content_scale)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "output_width": self.output_width,
            "output_height": self.output_height,
            "fullscreen": self.fullscreen,
            "left_viewport": self.left_viewport.to_dict(),
            "right_viewport": self.right_viewport.to_dict(),
            "swap_eyes": self.swap_eyes,
            "flip_left_h": self.flip_left_h,
            "flip_left_v": self.flip_left_v,
            "flip_right_h": self.flip_right_h,
            "flip_right_v": self.flip_right_v,
            "parallax_scale": self.parallax_scale,
            "content_scale": self.content_scale,
        }

    def copy(self) -> "Config":
        c = Config()
        c.__dict__.update(json_to_config(self.to_dict()).__dict__)
        return c


def default_config() -> Config:
    cfg = Config()
    left, right = _default_viewports(cfg.output_width, cfg.output_height)
    cfg.left_viewport = left
    cfg.right_viewport = right
    return cfg


def json_to_config(data: dict) -> Config:
    defaults = default_config()
    cfg = Config(
        output_width=int(data.get("output_width", defaults.output_width)),
        output_height=int(data.get("output_height", defaults.output_height)),
        fullscreen=bool(data.get("fullscreen", defaults.fullscreen)),
        left_viewport=Rect.from_dict(
            data.get("left_viewport", {}), defaults.left_viewport
        ),
        right_viewport=Rect.from_dict(
            data.get("right_viewport", {}), defaults.right_viewport
        ),
        swap_eyes=bool(data.get("swap_eyes", defaults.swap_eyes)),
        flip_left_h=bool(data.get("flip_left_h", defaults.flip_left_h)),
        flip_left_v=bool(data.get("flip_left_v", defaults.flip_left_v)),
        flip_right_h=bool(data.get("flip_right_h", defaults.flip_right_h)),
        flip_right_v=bool(data.get("flip_right_v", defaults.flip_right_v)),
        parallax_scale=float(data.get("parallax_scale", defaults.parallax_scale)),
        content_scale=float(data.get("content_scale", defaults.content_scale)),
    )
    cfg.clamp()
    return cfg


def load_config(path: Path = CONFIG_PATH) -> Config:
    """Load config.json, falling back to safe defaults if the file is
    missing, unreadable, or contains invalid values."""
    if not path.exists():
        return default_config()
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("config.json root must be an object")
        return json_to_config(data)
    except (json.JSONDecodeError, ValueError, TypeError, OSError):
        return default_config()


def save_config(cfg: Config, path: Path = CONFIG_PATH) -> None:
    cfg.clamp()
    tmp_path = path.with_suffix(".json.tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump(cfg.to_dict(), f, indent=2, ensure_ascii=False)
        f.write("\n")
    tmp_path.replace(path)
