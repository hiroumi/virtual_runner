"""Shared stereo drawing layer.

Game code (and, for now, the Phase 2 static test scene) never touches
viewport rectangles, swap/flip, or per-eye pixel math directly -- it draws
once into a StereoRenderer, tagging each draw call with a world `depth`,
and this module works out how far left/right that thing should shift in
each eye.

Simulation must run exactly once per frame. Only drawing is duplicated
per eye, via `draw_world` / `draw_flat` below -- never call game logic
twice for left/right.

Disparity convention (world depth -> horizontal pixel shift per eye):

    left_eye_x  = projected_x + disparity / 2
    right_eye_x = projected_x - disparity / 2

Positive disparity means the object converges (left shifts right, right
shifts left -- "inward") which reads as popping out toward the viewer.
Negative disparity means it diverges ("outward"), which reads as sitting
behind the screen. `screen_depth` is the world distance at which
disparity is exactly zero; nothing needs special-casing per object type
-- near things naturally get positive disparity, far things naturally
get a small negative disparity, purely from their depth value.
"""
from __future__ import annotations

import pygame

from config import Config

# Below this world depth, 1/depth blows up. Nothing in the game should
# ever legitimately be closer than this to the camera; it's a numerical
# floor, not a gameplay-tunable value.
MIN_DEPTH = 0.5


def calculate_disparity(depth: float, parallax_scale: float, cfg: Config) -> float:
    """Horizontal disparity (px) for an object at world `depth`, given the
    live `parallax_scale` (may differ from cfg.parallax_scale -- callers
    can adjust strength at runtime without touching the saved config) and
    the safety limits in `cfg`. Depth <= 0 is treated as MIN_DEPTH."""
    depth = max(depth, MIN_DEPTH)
    raw = cfg.disparity_k * (1.0 / depth - 1.0 / cfg.screen_depth)
    d = raw * parallax_scale
    return max(-cfg.max_negative_disparity_px, min(cfg.max_disparity_px, d))


def _apply_flip(surface: pygame.Surface, h: bool, v: bool) -> pygame.Surface:
    if not h and not v:
        return surface
    return pygame.transform.flip(surface, h, v)


class StereoRenderer:
    """Owns the two per-eye drawing surfaces and composites them into the
    calibrated viewports on the real screen. Viewport position/size,
    swap_eyes, and flip flags come straight from `cfg` and are never
    modified here -- Phase 1 calibration already settled those."""

    def __init__(self, screen: pygame.Surface, cfg: Config):
        self.screen = screen
        self.cfg = cfg
        self.left_surface = pygame.Surface(
            (cfg.left_viewport.width, cfg.left_viewport.height)
        )
        self.right_surface = pygame.Surface(
            (cfg.right_viewport.width, cfg.right_viewport.height)
        )

        # Runtime-adjustable, independent from cfg.parallax_scale until
        # explicitly saved -- lets the operator try values live without
        # corrupting the calibrated config on a crash.
        self.parallax_scale = cfg.parallax_scale
        self.zero_parallax = False
        self.flip_debug = False  # inverts disparity sign, for A/B checking

    # -- per-frame lifecycle ------------------------------------------------
    def begin_frame(self, bg_color: tuple[int, int, int] = (0, 0, 0)) -> None:
        self.left_surface.fill(bg_color)
        self.right_surface.fill(bg_color)

    def compute_disparity(self, depth: float) -> float:
        if self.zero_parallax:
            return 0.0
        d = calculate_disparity(depth, self.parallax_scale, self.cfg)
        return -d if self.flip_debug else d

    def draw_world(self, depth: float, draw_fn) -> None:
        """Call draw_fn(surface, x_offset) once per eye. x_offset already
        has the correct sign for that eye baked in -- add it to whatever
        local x-coordinates draw_fn uses. Never apply a vertical offset
        here: left/right vertical (game) parallax is not a thing."""
        disparity = self.compute_disparity(depth)
        draw_fn(self.left_surface, disparity / 2)
        draw_fn(self.right_surface, -disparity / 2)

    def draw_flat(self, draw_fn) -> None:
        """Zero-parallax draw: HUD, labels, anything meant to sit exactly
        on the screen plane in both eyes."""
        draw_fn(self.left_surface, 0.0)
        draw_fn(self.right_surface, 0.0)

    def present(self) -> None:
        cfg = self.cfg
        left_content, right_content = self.left_surface, self.right_surface
        if cfg.swap_eyes:
            left_content, right_content = right_content, left_content
        left_content = _apply_flip(left_content, cfg.flip_left_h, cfg.flip_left_v)
        right_content = _apply_flip(right_content, cfg.flip_right_h, cfg.flip_right_v)
        self.screen.blit(left_content, (cfg.left_viewport.x, cfg.left_viewport.y))
        self.screen.blit(right_content, (cfg.right_viewport.x, cfg.right_viewport.y))

    # -- debug / safety introspection ---------------------------------------
    def max_disparity_range(self) -> tuple[float, float]:
        """(max inward px, max outward px) -- the hard safety caps from
        cfg. These are absolute pixel limits applied *after*
        parallax_scale in calculate_disparity, so turning parallax_scale
        up can never exceed them; that's the point of a safety cap."""
        return (self.cfg.max_disparity_px, -self.cfg.max_negative_disparity_px)
