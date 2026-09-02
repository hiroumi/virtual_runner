"""Phase 1: stereo display calibrator.

Draws independent left/right test patterns into the two small viewport
rectangles that the Virtual Boy accessory's lenses actually look at
(NOT a naive 50/50 split of the screen), and lets the operator adjust
every relevant number in real time, then persist it to config.json.

Run directly: `python calibration.py`
"""
from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass
from enum import Enum, auto

import pygame

from config import Config, MIN_VIEWPORT_SIZE, Rect, load_config, save_config

# ---------------------------------------------------------------------------
# Colors. The calibrator itself doesn't need to follow the future game's
# red/black art direction, except in the dedicated Color test which exists
# specifically to compare how different reds/grays look through the
# accessory's red filter.
# ---------------------------------------------------------------------------
BLACK = (0, 0, 0)
WHITE = (255, 255, 255)
DIM = (60, 60, 60)
GRID_COLOR = (40, 40, 40)
BRIGHT = (200, 200, 200)
LABEL_COLOR = (120, 200, 255)
HUD_COLOR = (210, 210, 210)
HUD_DIM = (130, 130, 130)
TOAST_COLOR = (255, 220, 120)
WARN_COLOR = (255, 90, 90)

MAX_PARALLAX_PX = 40  # hard safety cap for the calibrator's test shapes
STEP_SMALL = 1
STEP_LARGE = 10


class Selection(Enum):
    LEFT = auto()
    RIGHT = auto()
    BOTH = auto()
    EYE_GAP = auto()
    PARALLAX_DEPTH = auto()


class AdjustMode(Enum):
    MOVE = auto()
    SIZE = auto()


class TestMode(Enum):
    GRID = auto()
    ALIGNMENT = auto()
    DEPTH = auto()
    PARALLAX = auto()
    CROP = auto()
    COLOR = auto()


TEST_MODE_ORDER = [
    TestMode.GRID,
    TestMode.ALIGNMENT,
    TestMode.DEPTH,
    TestMode.PARALLAX,
    TestMode.CROP,
    TestMode.COLOR,
]

SELECTION_LABEL = {
    Selection.LEFT: "LEFT",
    Selection.RIGHT: "RIGHT",
    Selection.BOTH: "BOTH (global move)",
    Selection.EYE_GAP: "EYE GAP",
    Selection.PARALLAX_DEPTH: "PARALLAX TEST DEPTH",
}


@dataclass
class UIState:
    selection: Selection = Selection.LEFT
    adjust_mode: AdjustMode = AdjustMode.MOVE
    test_mode_index: int = 0
    parallax_test_enabled: bool = True
    parallax_test_depth: float = 0.0  # -1.0 (pop out) .. +1.0 (recede)
    unsaved_changes: bool = False
    toast_text: str = ""
    toast_until: float = 0.0
    reset_armed_until: float = 0.0

    @property
    def test_mode(self) -> TestMode:
        return TEST_MODE_ORDER[self.test_mode_index]

    def toast(self, text: str, seconds: float = 2.5) -> None:
        self.toast_text = text
        self.toast_until = time.monotonic() + seconds


def _font(size: int) -> pygame.font.Font:
    return pygame.font.SysFont("consolas,couriernew,monospace", size)


class Calibrator:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.state = UIState()
        self.clock = pygame.time.Clock()
        self.screen = self._make_display()
        self.font_small = _font(14)
        self.font_hud = _font(15)
        self.font_big = _font(20)

    def _make_display(self) -> pygame.Surface:
        flags = pygame.FULLSCREEN if self.cfg.fullscreen else 0
        return pygame.display.set_mode(
            (self.cfg.output_width, self.cfg.output_height), flags
        )

    # -- main loop ----------------------------------------------------
    def run(self, test_frames: int | None = None) -> None:
        pygame.key.set_repeat(350, 40)
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

    # -- input ----------------------------------------------------------
    def _handle_keydown(self, event: pygame.event.Event) -> bool:
        """Return False to quit the app."""
        cfg, state = self.cfg, self.state
        key = event.key
        shift = bool(event.mod & pygame.KMOD_SHIFT)
        step = STEP_LARGE if shift else STEP_SMALL

        if key == pygame.K_ESCAPE:
            return False

        if key == pygame.K_1:
            state.selection = Selection.LEFT
        elif key == pygame.K_2:
            state.selection = Selection.RIGHT
        elif key == pygame.K_3:
            state.selection = Selection.BOTH
        elif key == pygame.K_4:
            state.selection = Selection.EYE_GAP
        elif key == pygame.K_5:
            state.selection = Selection.PARALLAX_DEPTH
        elif key == pygame.K_TAB:
            state.adjust_mode = (
                AdjustMode.SIZE if state.adjust_mode == AdjustMode.MOVE else AdjustMode.MOVE
            )
        elif key in (pygame.K_LEFTBRACKET, pygame.K_RIGHTBRACKET):
            delta = -1 if key == pygame.K_LEFTBRACKET else 1
            state.test_mode_index = (state.test_mode_index + delta) % len(TEST_MODE_ORDER)
        elif key in (pygame.K_LEFT, pygame.K_RIGHT, pygame.K_UP, pygame.K_DOWN):
            dx = step if key == pygame.K_RIGHT else -step if key == pygame.K_LEFT else 0
            dy = step if key == pygame.K_DOWN else -step if key == pygame.K_UP else 0
            self._apply_directional(dx, dy)
        elif key in (pygame.K_PLUS, pygame.K_EQUALS, pygame.K_KP_PLUS):
            cfg.content_scale = min(3.0, cfg.content_scale + (0.2 if shift else 0.05))
            state.unsaved_changes = True
        elif key in (pygame.K_MINUS, pygame.K_KP_MINUS):
            cfg.content_scale = max(0.25, cfg.content_scale - (0.2 if shift else 0.05))
            state.unsaved_changes = True
        elif key == pygame.K_p:
            state.parallax_test_enabled = not state.parallax_test_enabled
        elif key == pygame.K_x:
            cfg.swap_eyes = not cfg.swap_eyes
            state.unsaved_changes = True
        elif key == pygame.K_h:
            self._toggle_flip(horizontal=True)
        elif key == pygame.K_v:
            self._toggle_flip(horizontal=False)
        elif key == pygame.K_f:
            cfg.fullscreen = not cfg.fullscreen
            self.screen = self._make_display()
            state.unsaved_changes = True
        elif key == pygame.K_s:
            save_config(cfg)
            state.unsaved_changes = False
            state.toast("Saved to config.json")
        elif key == pygame.K_r:
            now = time.monotonic()
            if now < state.reset_armed_until:
                from config import default_config

                self.cfg = default_config()
                self.state = UIState()
                self.state.toast("Reset to default values (not yet saved - press S)")
            else:
                state.reset_armed_until = now + 3.0
                state.toast("Press R again within 3s to RESET to defaults", 3.0)
        return True

    def _apply_directional(self, dx: int, dy: int) -> None:
        cfg, state = self.cfg, self.state
        if state.selection == Selection.EYE_GAP:
            cfg.left_viewport.x -= dx
            cfg.right_viewport.x += dx
            cfg.left_viewport.y -= dy
            cfg.right_viewport.y += dy
        elif state.selection == Selection.PARALLAX_DEPTH:
            if dx != 0:
                state.parallax_test_depth = max(
                    -1.0, min(1.0, state.parallax_test_depth + dx * 0.02)
                )
            return  # doesn't touch cfg / doesn't need clamping below
        else:
            targets = []
            if state.selection in (Selection.LEFT, Selection.BOTH):
                targets.append(cfg.left_viewport)
            if state.selection in (Selection.RIGHT, Selection.BOTH):
                targets.append(cfg.right_viewport)
            for rect in targets:
                if state.adjust_mode == AdjustMode.MOVE:
                    rect.x += dx
                    rect.y += dy
                else:
                    rect.width = max(MIN_VIEWPORT_SIZE, rect.width + dx)
                    rect.height = max(MIN_VIEWPORT_SIZE, rect.height + dy)
        cfg.left_viewport.clamp(cfg.output_width, cfg.output_height)
        cfg.right_viewport.clamp(cfg.output_width, cfg.output_height)
        state.unsaved_changes = True

    def _toggle_flip(self, horizontal: bool) -> None:
        cfg, sel = self.cfg, self.state.selection
        targets = []
        if sel in (Selection.LEFT, Selection.BOTH):
            targets.append("left")
        if sel in (Selection.RIGHT, Selection.BOTH):
            targets.append("right")
        for side in targets:
            attr = f"flip_{side}_{'h' if horizontal else 'v'}"
            setattr(cfg, attr, not getattr(cfg, attr))
        if targets:
            self.state.unsaved_changes = True

    # -- drawing ----------------------------------------------------------
    def _draw(self) -> None:
        screen, cfg, state = self.screen, self.cfg, self.state
        screen.fill(BLACK)

        left_content = self._render_eye_surface("LEFT", cfg.left_viewport)
        right_content = self._render_eye_surface("RIGHT", cfg.right_viewport)

        if cfg.swap_eyes:
            left_content, right_content = right_content, left_content

        left_content = self._apply_flip(left_content, cfg.flip_left_h, cfg.flip_left_v)
        right_content = self._apply_flip(right_content, cfg.flip_right_h, cfg.flip_right_v)

        screen.blit(left_content, (cfg.left_viewport.x, cfg.left_viewport.y))
        screen.blit(right_content, (cfg.right_viewport.x, cfg.right_viewport.y))

        self._draw_hud()
        self._draw_toast()

    @staticmethod
    def _apply_flip(surface: pygame.Surface, h: bool, v: bool) -> pygame.Surface:
        if not h and not v:
            return surface
        return pygame.transform.flip(surface, h, v)

    def _render_eye_surface(self, label: str, rect: Rect) -> pygame.Surface:
        surf = pygame.Surface((rect.width, rect.height))
        surf.fill(BLACK)
        mode = self.state.test_mode
        scale = self.cfg.content_scale

        pygame.draw.rect(surf, DIM, surf.get_rect(), 2)
        text = self.font_small.render(label, True, LABEL_COLOR)
        surf.blit(text, (6, 4))
        coord = self.font_small.render(
            f"{rect.x},{rect.y} {rect.width}x{rect.height}", True, HUD_DIM
        )
        surf.blit(coord, (6, rect.height - 18))

        if mode == TestMode.GRID:
            self._draw_grid(surf, scale)
            self._draw_cross(surf)
            self._draw_corners(surf, scale)
            self._draw_circle(surf, scale)
        elif mode == TestMode.ALIGNMENT:
            self._draw_cross(surf)
            self._draw_corners(surf, scale)
        elif mode == TestMode.DEPTH:
            self._draw_depth(surf, label, scale)
        elif mode == TestMode.PARALLAX:
            self._draw_parallax(surf, label, scale)
        elif mode == TestMode.CROP:
            self._draw_crop(surf)
        elif mode == TestMode.COLOR:
            self._draw_color_bars(surf)
        return surf

    def _draw_grid(self, surf: pygame.Surface, scale: float) -> None:
        w, h = surf.get_size()
        step = max(8, int(20 * scale))
        for x in range(0, w, step):
            pygame.draw.line(surf, GRID_COLOR, (x, 0), (x, h))
        for y in range(0, h, step):
            pygame.draw.line(surf, GRID_COLOR, (0, y), (w, y))

    def _draw_cross(self, surf: pygame.Surface) -> None:
        w, h = surf.get_size()
        cx, cy = w // 2, h // 2
        pygame.draw.line(surf, BRIGHT, (cx, 0), (cx, h))
        pygame.draw.line(surf, BRIGHT, (0, cy), (w, cy))

    def _draw_corners(self, surf: pygame.Surface, scale: float) -> None:
        w, h = surf.get_size()
        size = max(6, int(12 * scale))
        corners = [(0, 0, 1, 1), (w, 0, -1, 1), (0, h, 1, -1), (w, h, -1, -1)]
        for x, y, sx, sy in corners:
            pygame.draw.line(surf, WHITE, (x, y), (x + size * sx, y))
            pygame.draw.line(surf, WHITE, (x, y), (x, y + size * sy))

    def _draw_circle(self, surf: pygame.Surface, scale: float) -> None:
        w, h = surf.get_size()
        radius = int(min(w, h) * 0.3 * scale)
        pygame.draw.circle(surf, BRIGHT, (w // 2, h // 2), max(4, radius), 2)

    def _depth_offset_px(self, unit: float) -> float:
        if not self.state.parallax_test_enabled:
            return 0.0
        return unit * self.cfg.parallax_scale * MAX_PARALLAX_PX

    def _draw_depth(self, surf: pygame.Surface, label: str, scale: float) -> None:
        w, h = surf.get_size()
        sign = -1 if label == "LEFT" else 1
        layers = [
            (0.2, 10 * scale, (140, 30, 30), h * 0.30),   # far / background
            (0.5, 18 * scale, (190, 40, 40), h * 0.52),   # mid
            (1.0, 28 * scale, (255, 60, 60), h * 0.75),   # near / foreground
        ]
        for unit, size, color, cy in layers:
            offset = sign * self._depth_offset_px(unit)
            cx = w / 2 + offset
            rect = pygame.Rect(0, 0, size * 2, size * 2)
            rect.center = (int(cx), int(cy))
            pygame.draw.rect(surf, color, rect)

    def _draw_parallax(self, surf: pygame.Surface, label: str, scale: float) -> None:
        w, h = surf.get_size()
        sign = -1 if label == "LEFT" else 1
        offset = sign * self._depth_offset_px(self.state.parallax_test_depth)
        cx, cy = w / 2 + offset, h / 2
        radius = int(min(w, h) * 0.18 * scale)
        pygame.draw.circle(surf, (255, 70, 70), (int(cx), int(cy)), max(4, radius))
        depth_text = self.font_small.render(
            f"depth {self.state.parallax_test_depth:+.2f}", True, HUD_DIM
        )
        surf.blit(depth_text, (6, 22))

    def _draw_crop(self, surf: pygame.Surface) -> None:
        w, h = surf.get_size()
        pygame.draw.rect(surf, WHITE, (0, 0, w - 1, h - 1), 1)
        for frac in (0.1, 0.25, 0.5, 0.75, 0.9):
            x = int(w * frac)
            y = int(h * frac)
            pygame.draw.line(surf, DIM, (x, 0), (x, 6))
            pygame.draw.line(surf, DIM, (x, h - 6), (x, h))
            pygame.draw.line(surf, DIM, (0, y), (6, y))
            pygame.draw.line(surf, DIM, (w - 6, y), (w, y))
        for (cx, cy) in [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)]:
            pygame.draw.circle(surf, (255, 220, 60), (cx, cy), 4, 1)

    def _draw_color_bars(self, surf: pygame.Surface) -> None:
        w, h = surf.get_size()
        swatches = [
            ("BLK", (0, 0, 0)),
            ("R25", (64, 0, 0)),
            ("R50", (128, 0, 0)),
            ("R75", (192, 0, 0)),
            ("RED", (255, 0, 0)),
            ("GY3", (64, 64, 64)),
            ("GY6", (128, 128, 128)),
            ("GY9", (192, 192, 192)),
            ("WHT", (255, 255, 255)),
        ]
        bar_w = w / len(swatches)
        for i, (name, color) in enumerate(swatches):
            x0 = int(i * bar_w)
            x1 = int((i + 1) * bar_w)
            pygame.draw.rect(surf, color, (x0, 30, x1 - x0, h - 60))
            text_color = WHITE if sum(color) < 300 else BLACK
            label = self.font_small.render(name, True, text_color)
            surf.blit(label, (x0 + 2, h - 26))

    # -- HUD --------------------------------------------------------------
    def _draw_hud(self) -> None:
        cfg, state = self.cfg, self.state
        lines_left = [
            f"MODE: {state.test_mode.name}   [ / ] to cycle",
            f"SELECT: {SELECTION_LABEL[state.selection]}   (1 2 3 4 5)",
            f"ADJUST: {state.adjust_mode.name}   (Tab to switch)",
            f"LEFT   x={cfg.left_viewport.x} y={cfg.left_viewport.y} "
            f"w={cfg.left_viewport.width} h={cfg.left_viewport.height} "
            f"flipH={cfg.flip_left_h} flipV={cfg.flip_left_v}",
            f"RIGHT  x={cfg.right_viewport.x} y={cfg.right_viewport.y} "
            f"w={cfg.right_viewport.width} h={cfg.right_viewport.height} "
            f"flipH={cfg.flip_right_h} flipV={cfg.flip_right_v}",
            f"eye_gap(center-to-center)={self._eye_gap_px()}px  "
            f"swap_eyes={cfg.swap_eyes}",
            f"parallax_scale={cfg.parallax_scale:.2f}  content_scale={cfg.content_scale:.2f}  "
            f"parallax_test={'ON' if state.parallax_test_enabled else 'OFF'} (P)",
            f"fullscreen={cfg.fullscreen} (F)   "
            + ("UNSAVED CHANGES (press S)" if state.unsaved_changes else "saved"),
        ]
        y = 6
        for line in lines_left:
            color = WARN_COLOR if "UNSAVED" in line else HUD_COLOR
            surf = self.font_hud.render(line, True, color)
            self.screen.blit(surf, (8, y))
            y += 17

        legend = [
            "arrows: move/resize   shift+arrows: x10   +/-: content scale",
            "1 left  2 right  3 both  4 eye-gap  5 parallax-depth",
            "Tab: move<->size   [ ]: test mode   P: parallax on/off   X: swap eyes",
            "H/V: flip h/v   F: fullscreen   S: save   R R: reset   Esc: quit",
        ]
        y = cfg.output_height - 6 - 15 * len(legend)
        for line in legend:
            surf = self.font_small.render(line, True, HUD_DIM)
            self.screen.blit(surf, (8, y))
            y += 15

    def _eye_gap_px(self) -> int:
        lx, _ = self.cfg.left_viewport.center()
        rx, _ = self.cfg.right_viewport.center()
        return rx - lx

    def _draw_toast(self) -> None:
        state = self.state
        if time.monotonic() >= state.toast_until or not state.toast_text:
            return
        surf = self.font_big.render(state.toast_text, True, TOAST_COLOR)
        rect = surf.get_rect(center=(self.cfg.output_width // 2, 24))
        self.screen.blit(surf, rect)


def run(test_frames: int | None = None) -> None:
    pygame.init()
    pygame.display.set_caption("Virtual Boy Stereo Calibrator - Phase 1")
    cfg = load_config()
    app = Calibrator(cfg)
    app.run(test_frames=test_frames)


def main() -> None:
    parser = argparse.ArgumentParser(description="Virtual Boy stereo display calibrator")
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
