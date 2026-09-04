"""Builds the 6 assets/cars/enemies/*.png traffic-car sprites (2026-09-05)
from assets/source/enemy_cars_sheet.png -- a 2-row x 3-col sheet the user
supplied, read left-to-right, top-to-bottom as: sports_coupe, boxy_sedan,
compact_hatchback / panel_van, muscle_car, pickup_truck.

Like the earlier player-car sheet (see assets/cars/player/
build_from_spritesheet.py), this sheet's alpha channel is fully opaque --
the "transparent" look is a white/light-gray checkerboard baked into RGB.
Unlike a simple brightness threshold (which would also erase interior
bright/desaturated pixels -- windows, taillight glass, highlights, plate
background), background removal here is a **flood fill from the sheet's
outer border** over pixels that look like checkerboard (bright AND low
saturation): only pixels reachable from the edge through other
background-like pixels get alpha=0. An interior bright patch that isn't
4-connected to the border through background-colored pixels survives
untouched.

Regular cars and the van/pickup are intentionally *not* forced to the
same pixel footprint -- a single shared scale factor (chosen so the
largest car fits the target box) is applied to all 6 crops so their
relative size differences from the source sheet are preserved, then all
6 are placed on one shared transparent canvas with their own bounding
box's bottom-center (tire contact) at one fixed anchor point.

Run this to rebuild the 6 PNGs from the source sheet (e.g. after the
user supplies a revised sheet):
    python scripts/build_enemy_sprites.py
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pygame

ROOT = Path(__file__).resolve().parent.parent
SOURCE_SHEET = ROOT / "assets" / "source" / "enemy_cars_sheet.png"
OUTPUT_DIR = ROOT / "assets" / "cars" / "enemies"

GRID_COLS = 3
GRID_ROWS = 2
# Reading order left-to-right, top-to-bottom, per
# CLAUDE_CODE_ENEMY_CARS_INSTRUCTIONS.txt.
SPRITE_NAMES = [
    "sports_coupe", "boxy_sedan", "compact_hatchback",
    "panel_van", "muscle_car", "pickup_truck",
]

# A pixel counts as "checkerboard background" if it's bright (high max
# channel) AND low-saturation (small max-min channel spread) -- true of
# both checkerboard shades, false of the cars' saturated red paint and
# also false of most interior bright details (window glass has a visible
# tint, taillight glass is red-tinted, highlights sit on red bodywork).
BG_BRIGHTNESS_MIN = 200
BG_SATURATION_MAX = 30

# Padding (source-resolution px) kept around each car's crop before
# placing it on the shared canvas.
CROP_PAD = 4

# Target box (post shared-scale) that the single largest car must fit
# inside -- chosen from the spec's "regular cars ~64x40-88x48px, van/
# pickup keep their extra height/width" guidance. The shared scale factor
# is derived from whichever source car is actually largest, so this is a
# ceiling, not every car's actual size.
MAX_CANVAS_SIZE = (92, 56)
CANVAS_PAD = 4


def _flood_fill_background(is_bg_candidate: "np.ndarray") -> "np.ndarray":
    """is_bg_candidate: bool array (w, h), True where a pixel *looks*
    like background by color alone. Returns a bool array, True only
    where a pixel is both a candidate AND reachable from the image
    border through other candidate pixels (4-connected) -- i.e. the
    real background, not an interior look-alike patch.

    Implemented as iterative dilation restricted to the candidate mask
    (grows the known-background region one ring at a time until it stops
    changing) rather than a per-pixel BFS queue, so a 1536x1024 sheet
    finishes in well under a second with only numpy.
    """
    reached = np.zeros_like(is_bg_candidate)
    reached[0, :] |= is_bg_candidate[0, :]
    reached[-1, :] |= is_bg_candidate[-1, :]
    reached[:, 0] |= is_bg_candidate[:, 0]
    reached[:, -1] |= is_bg_candidate[:, -1]

    while True:
        grown = reached.copy()
        grown[1:, :] |= reached[:-1, :]
        grown[:-1, :] |= reached[1:, :]
        grown[:, 1:] |= reached[:, :-1]
        grown[:, :-1] |= reached[:, 1:]
        grown &= is_bg_candidate
        if np.array_equal(grown, reached):
            return reached
        reached = grown


def _tight_bbox(mask: "np.ndarray", x0: int, x1: int, y0: int, y1: int) -> tuple[int, int, int, int]:
    """Tight (x0, x1_inclusive, y0, y1_inclusive) bbox of True pixels of
    mask within the given cell rect."""
    sub = mask[x0:x1, y0:y1]
    xs = np.where(sub.any(axis=1))[0]
    ys = np.where(sub.any(axis=0))[0]
    return xs.min() + x0, xs.max() + x0, ys.min() + y0, ys.max() + y0


def build_sprites(sheet_path: Path = SOURCE_SHEET) -> dict[str, pygame.Surface]:
    sheet = pygame.image.load(str(sheet_path)).convert_alpha()
    w, h = sheet.get_size()
    rgb = pygame.surfarray.pixels3d(sheet).astype(np.int16).copy()  # (w, h, 3)
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    maxc = np.maximum(np.maximum(r, g), b)
    minc = np.minimum(np.minimum(r, g), b)
    sat = maxc - minc
    bg_candidate = (maxc > BG_BRIGHTNESS_MIN) & (sat < BG_SATURATION_MAX)
    is_bg = _flood_fill_background(bg_candidate)
    is_car = ~is_bg

    cell_w, cell_h = w // GRID_COLS, h // GRID_ROWS

    crops: dict[str, pygame.Surface] = {}
    native_sizes: dict[str, tuple[int, int]] = {}
    for row in range(GRID_ROWS):
        for col in range(GRID_COLS):
            name = SPRITE_NAMES[row * GRID_COLS + col]
            cx0, cx1 = col * cell_w, (col + 1) * cell_w
            cy0, cy1 = row * cell_h, (row + 1) * cell_h
            bx0, bx1, by0, by1 = _tight_bbox(is_car, cx0, cx1, cy0, cy1)
            bx0 = max(cx0, bx0 - CROP_PAD)
            by0 = max(cy0, by0 - CROP_PAD)
            bx1 = min(cx1 - 1, bx1 + CROP_PAD)
            by1 = min(cy1 - 1, by1 + CROP_PAD)
            crop_w, crop_h = bx1 - bx0 + 1, by1 - by0 + 1

            crop = pygame.Surface((crop_w, crop_h), pygame.SRCALPHA)
            crop.fill((0, 0, 0, 0))
            car_mask = is_car[bx0 : bx1 + 1, by0 : by1 + 1]
            crop_rgb = rgb[bx0 : bx1 + 1, by0 : by1 + 1, :].astype(np.uint8)
            alpha = np.where(car_mask, 255, 0).astype(np.uint8)
            px = pygame.surfarray.pixels3d(crop)
            pa = pygame.surfarray.pixels_alpha(crop)
            px[:, :, :] = crop_rgb
            pa[:, :] = alpha
            del px, pa

            crops[name] = crop
            native_sizes[name] = (crop_w, crop_h)

    # One shared scale factor for all 6, derived from whichever source
    # car is actually largest -- this is what keeps the van/pickup's
    # real size advantage over the sedans intact instead of normalizing
    # everyone to the same footprint.
    max_native_w = max(sz[0] for sz in native_sizes.values())
    max_native_h = max(sz[1] for sz in native_sizes.values())
    fit_w = (MAX_CANVAS_SIZE[0] - 2 * CANVAS_PAD) / max_native_w
    fit_h = (MAX_CANVAS_SIZE[1] - 2 * CANVAS_PAD) / max_native_h
    shared_scale = min(fit_w, fit_h)

    canvas_w = int(round(max_native_w * shared_scale)) + 2 * CANVAS_PAD
    canvas_h = int(round(max_native_h * shared_scale)) + 2 * CANVAS_PAD
    anchor = (canvas_w // 2, canvas_h - CANVAS_PAD)

    sprites: dict[str, pygame.Surface] = {}
    for name, crop in crops.items():
        native_w, native_h = native_sizes[name]
        scaled_w = max(1, int(round(native_w * shared_scale)))
        scaled_h = max(1, int(round(native_h * shared_scale)))
        # pygame.transform.scale (not smoothscale) -- nearest-neighbor
        # sampling, no interpolation/antialiasing, per the spec.
        scaled = pygame.transform.scale(crop, (scaled_w, scaled_h))

        canvas = pygame.Surface((canvas_w, canvas_h), pygame.SRCALPHA)
        canvas.fill((0, 0, 0, 0))
        dest_x = anchor[0] - scaled_w // 2
        dest_y = anchor[1] - scaled_h
        canvas.blit(scaled, (dest_x, dest_y))
        sprites[name] = canvas

    return sprites


def main() -> None:
    pygame.init()
    pygame.display.set_mode((100, 100))  # needed for .convert_alpha()
    sprites = build_sprites()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, surf in sprites.items():
        path = OUTPUT_DIR / f"{name}.png"
        pygame.image.save(surf, str(path))
        print(path, surf.get_size())
    pygame.quit()


if __name__ == "__main__":
    main()
