"""Phase 2, step 1: static stereo depth/disparity confirmation scene.

Not the racing game yet -- a fixed (non-scrolling) scene built entirely
out of original placeholder shapes (rectangles, lines, polygons; no
imported art), arranged to look roughly like a red/black pseudo-3D racer
(HUD strip, horizon, road, roadside trees, a distant car, the player's
own car) purely so the depth ordering is easy to judge by eye. Every
object is drawn through StereoRenderer.draw_world(depth, ...), so the
horizontal shift between left/right comes entirely from
stereo_renderer.calculate_disparity(depth, ...) -- nothing here hand-picks
a per-object pixel offset.

Per the project instructions:
- HUD is drawn with draw_flat() -> always zero disparity.
- Sky/mountains use a large depth -> small negative (outward) disparity.
- Roadside trees / near objects use small depth -> positive (inward).
- The player's own car uses the smallest depth -> the largest inward
  disparity, safety-clamped by cfg.max_disparity_px.

Run directly: `python phase2_test_scene.py`
"""
from __future__ import annotations

import argparse
import math

import pygame

from config import load_config, save_config
from stereo_renderer import StereoRenderer

BLACK = (0, 0, 0)
DARK_RED = (55, 0, 0)
MED_RED = (110, 15, 15)
ROAD_DARK = (35, 8, 8)
ROAD_LINE = (170, 25, 25)
CAR_RED = (190, 25, 25)
PLAYER_RED = (255, 45, 45)
TREE_RED = (150, 20, 20)
HUD_BORDER = (200, 40, 40)
HUD_TEXT = (255, 90, 90)
DEBUG_TEXT = (190, 190, 190)
DEBUG_WARN = (255, 210, 110)
CLAMP_COLOR = (255, 120, 120)

# Road dash depths, near -> far, purely to demonstrate that each road
# segment gets its own depth-appropriate disparity rather than one
# shared shift for the whole road.
ROAD_DASH_DEPTHS = [4.0, 7.0, 11.0, 16.0, 24.0, 40.0]


def _font(size: int) -> pygame.font.Font:
    return pygame.font.SysFont("consolas,couriernew,monospace", size)


def build_scene(width: int, height: int, horizon_frac: float = 0.52):
    """Returns (objects, horizon_y). objects is a list of
    (name, depth, draw_fn) where draw_fn(surface, x_offset) draws that
    object shifted by x_offset (already carries the correct sign for the
    eye it's being drawn into)."""
    horizon = int(height * horizon_frac)
    # Keep every ground-layer object's lowest point above the HUD strip
    # (see _draw_hud: a 30px-tall band pinned to the bottom of the frame).
    ground_y = height - 36
    objects: list[tuple[str, float, object]] = []

    def draw_clouds(surf: pygame.Surface, ox: float) -> None:
        for cx_frac, cy, r in ((0.28, horizon * 0.28, 11), (0.58, horizon * 0.42, 15), (0.8, horizon * 0.2, 8)):
            cx = width * cx_frac + ox
            rect = pygame.Rect(0, 0, int(r * 2.2), int(r))
            rect.center = (int(cx), int(cy))
            pygame.draw.ellipse(surf, DARK_RED, rect)

    objects.append(("SKY / CLOUDS", 300.0, draw_clouds))

    def draw_mountains(surf: pygame.Surface, ox: float) -> None:
        pts = [
            (0, horizon), (width * 0.15, horizon - 22), (width * 0.30, horizon - 6),
            (width * 0.50, horizon - 28), (width * 0.70, horizon - 10),
            (width * 0.85, horizon - 20), (width, horizon),
        ]
        pygame.draw.polygon(surf, MED_RED, [(x + ox, y) for x, y in pts])

    objects.append(("MOUNTAINS", 250.0, draw_mountains))

    def draw_road(surf: pygame.Surface, ox: float) -> None:
        top_w, bottom_w = 16, width * 0.9
        cx = width / 2 + ox
        pts = [
            (cx - top_w / 2, horizon), (cx + top_w / 2, horizon),
            (cx + bottom_w / 2, height), (cx - bottom_w / 2, height),
        ]
        pygame.draw.polygon(surf, ROAD_DARK, pts)

    objects.append(("ROAD SURFACE", 40.0, draw_road))

    t_near, t_far = 1.0 / ROAD_DASH_DEPTHS[0], 1.0 / ROAD_DASH_DEPTHS[-1]
    for i, depth in enumerate(ROAD_DASH_DEPTHS):
        frac = (1.0 / depth - t_far) / (t_near - t_far)
        y = horizon + frac * (ground_y - horizon)
        w = 3 + frac * 13
        h = 2 + frac * 9

        def make_dash(y=y, w=w, h=h):
            def draw(surf: pygame.Surface, ox: float) -> None:
                cx = surf.get_width() / 2 + ox
                pygame.draw.rect(surf, ROAD_LINE, (cx - w / 2, y - h / 2, w, h))
            return draw

        objects.append((f"ROAD DASH[{i}] (z={depth:g})", depth, make_dash()))

    def draw_far_car(surf: pygame.Surface, ox: float) -> None:
        cx = width * 0.42 + ox
        cy = horizon + 6
        pygame.draw.rect(surf, CAR_RED, (cx - 6, cy - 4, 12, 6))

    objects.append(("FAR CAR", 22.0, draw_far_car))

    def make_tree(cx_frac: float, base_y: float, scale: float):
        def draw(surf: pygame.Surface, ox: float) -> None:
            cx = surf.get_width() * cx_frac + ox
            trunk_h = 22 * scale
            pygame.draw.line(surf, TREE_RED, (cx, base_y), (cx, base_y - trunk_h), max(2, int(2 * scale)))
            top = (cx, base_y - trunk_h)
            for angle_deg in (-135, -105, -75, -45):
                rad = math.radians(angle_deg)
                length = 16 * scale
                end = (top[0] + length * math.cos(rad), top[1] + length * math.sin(rad))
                pygame.draw.line(surf, TREE_RED, top, end, max(1, int(2 * scale)))
        return draw

    objects.append(("MID TREE (L)", 11.0, make_tree(0.14, horizon + 34, 1.0)))
    objects.append(("MID TREE (R)", 13.0, make_tree(0.88, horizon + 30, 0.9)))
    objects.append(("NEAR PALM (L)", 6.0, make_tree(0.03, ground_y, 1.6)))
    objects.append(("NEAR PALM (R)", 6.0, make_tree(0.97, ground_y - 6, 1.5)))

    def draw_player_car(surf: pygame.Surface, ox: float) -> None:
        cx = surf.get_width() / 2 + ox
        base_y = ground_y
        pygame.draw.rect(surf, PLAYER_RED, (cx - 24, base_y - 18, 48, 18))
        pygame.draw.rect(surf, PLAYER_RED, (cx - 15, base_y - 28, 30, 12))

    objects.append(("PLAYER CAR", 3.0, draw_player_car))

    return objects, horizon


class Phase2TestScene:
    def __init__(self, cfg):
        self.cfg = cfg
        self.screen = self._make_display()
        self.renderer = StereoRenderer(self.screen, cfg)
        self.objects, self.horizon = build_scene(
            cfg.left_viewport.width, cfg.left_viewport.height
        )
        self.font_hud = _font(13)
        self.font_debug = _font(12)
        self.clock = pygame.time.Clock()

    def _make_display(self) -> pygame.Surface:
        flags = pygame.FULLSCREEN if self.cfg.fullscreen else 0
        return pygame.display.set_mode(
            (self.cfg.output_width, self.cfg.output_height), flags
        )

    def run(self, test_frames: int | None = None) -> None:
        pygame.key.set_repeat(300, 40)
        running = True
        frame = 0
        while running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.KEYDOWN:
                    if not self._handle_keydown(event):
                        running = False
            self._draw()
            pygame.display.flip()
            self.clock.tick(60)
            frame += 1
            if test_frames is not None and frame >= test_frames:
                running = False
        pygame.quit()

    def _handle_keydown(self, event: pygame.event.Event) -> bool:
        renderer, cfg = self.renderer, self.cfg
        shift = bool(event.mod & pygame.KMOD_SHIFT)
        step = 0.2 if shift else 0.05
        key = event.key

        if key == pygame.K_ESCAPE:
            return False
        elif key == pygame.K_UP:
            renderer.parallax_scale = min(2.0, renderer.parallax_scale + step)
        elif key == pygame.K_DOWN:
            renderer.parallax_scale = max(0.0, renderer.parallax_scale - step)
        elif key == pygame.K_z:
            renderer.zero_parallax = not renderer.zero_parallax
        elif key == pygame.K_i:
            renderer.flip_debug = not renderer.flip_debug
        elif key == pygame.K_f:
            cfg.fullscreen = not cfg.fullscreen
            self.screen = self._make_display()
            renderer.screen = self.screen
        elif key == pygame.K_s:
            cfg.parallax_scale = renderer.parallax_scale
            save_config(cfg)
        return True

    def _draw(self) -> None:
        renderer = self.renderer
        renderer.begin_frame(BLACK)
        for _name, depth, draw_fn in self.objects:
            renderer.draw_world(depth, draw_fn)
        renderer.draw_flat(self._draw_hud)
        renderer.present()
        self._draw_debug_overlay()

    def _draw_hud(self, surf: pygame.Surface, ox: float) -> None:
        w, h = surf.get_size()
        boxes = [("TIME", "60"), ("SCORE", "000000"), ("SPEED", "000")]
        box_w = w / len(boxes)
        for i, (label, value) in enumerate(boxes):
            x0 = int(i * box_w) + 2
            rect = pygame.Rect(x0, h - 30, int(box_w) - 4, 26)
            pygame.draw.rect(surf, HUD_BORDER, rect, 1)
            lbl = self.font_hud.render(label, True, HUD_TEXT)
            val = self.font_hud.render(value, True, HUD_TEXT)
            surf.blit(lbl, (rect.x + 3, rect.y + 1))
            surf.blit(val, (rect.x + 3, rect.y + 13))

    def _clamp_note(self, d: float) -> str:
        cfg = self.cfg
        if abs(d - cfg.max_disparity_px) < 1e-6:
            return "  (CLAMPED +)"
        if abs(d + cfg.max_negative_disparity_px) < 1e-6:
            return "  (CLAMPED -)"
        return ""

    def _draw_debug_overlay(self) -> None:
        renderer, cfg = self.renderer, self.cfg
        max_in, max_out = renderer.max_disparity_range()
        header = [
            f"parallax={renderer.parallax_scale:.2f}(Up/Dn) zero={'ON' if renderer.zero_parallax else 'off'}(Z)"
            f" flip={'ON' if renderer.flip_debug else 'off'}(I) caps=[{max_out:+.0f},{max_in:+.0f}]px"
            f" screen_z={cfg.screen_depth:g} F=full S=save Esc=quit",
        ]

        rows = []
        dash_disparities = []
        for name, depth, _fn in self.objects:
            d = renderer.compute_disparity(depth)
            if name.startswith("ROAD DASH"):
                dash_disparities.append(d)
                continue
            rows.append(f"{name:<16}z={depth:>5.1f} d={d:+6.1f}px{self._clamp_note(d)}")
        if dash_disparities:
            rows.insert(
                2,
                f"{'ROAD DASHES x' + str(len(dash_disparities)):<16}"
                f"z={ROAD_DASH_DEPTHS[0]:.0f}..{ROAD_DASH_DEPTHS[-1]:.0f} "
                f"d={dash_disparities[0]:+.1f}..{dash_disparities[-1]:+.1f}px",
            )

        lines = header + rows
        y = 4
        line_h = 13
        for i, line in enumerate(lines):
            color = DEBUG_WARN if i == 0 else DEBUG_TEXT
            if "CLAMPED" in line:
                color = CLAMP_COLOR
            surf = self.font_debug.render(line, True, color)
            self.screen.blit(surf, (6, y))
            y += line_h


def run(test_frames: int | None = None) -> None:
    pygame.init()
    pygame.display.set_caption("Phase 2 - Stereo Depth Test Scene")
    cfg = load_config()
    Phase2TestScene(cfg).run(test_frames=test_frames)


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 2 static stereo depth confirmation scene")
    parser.add_argument(
        "--test-frames",
        type=int,
        default=None,
        help="Render N frames and exit automatically (smoke test / CI, no input needed).",
    )
    args = parser.parse_args()
    run(test_frames=args.test_frames)


if __name__ == "__main__":
    main()
