"""Builds the 5 production player_*.png sprites (2026-09-05) from
source_spritesheet.png -- a single image the user supplied containing
all 5 poses side by side, left to right: hard_left, left, straight,
right, hard_right.

This sheet carries real per-pixel alpha (verified with
pygame.surfarray.pixels_alpha: 0 at the corners, full 0-255 range
across the image), so car regions are detected directly from alpha
-- a pixel counts as "car" if alpha > ALPHA_THRESHOLD. (An earlier
sheet the user tried had no real alpha -- background baked into RGB
as flat gray -- and needed a color-based heuristic instead; this one
didn't, so the simpler alpha path is used here.)

The 5 cars' bounding boxes all land within 1px of the same bottom row
in the source, so no per-car vertical offset guessing was needed --
each crop is placed onto a shared canvas with its own bbox-bottom at
one fixed anchor row (and bbox-center at one fixed anchor column).

Run this to rebuild the 5 PNGs from the source sheet (e.g. after the
user supplies a revised sheet):
    python assets/cars/player/build_from_spritesheet.py
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pygame

HERE = Path(__file__).resolve().parent
SOURCE_SHEET = HERE / "source_spritesheet.png"

POSE_NAMES = ["hard_left", "left", "straight", "right", "hard_right"]

ALPHA_THRESHOLD = 10  # alpha > this counts as "car" pixel

# Padding (source-resolution px) kept around the widest/tallest car
# bounding box when building the shared native-resolution canvas, before
# downscaling to the final in-game size.
NATIVE_PAD = 6

# Final in-game canvas size (post-downscale) -- chosen to keep roughly
# the same footprint, relative to the calibrated 280px-wide viewport, as
# the previous placeholder (64/280 = 23%) while giving this much more
# detailed art a bit more room (88/280 = 31%) than the old minimalist
# pixel art needed. Mirrored in game.py's PLAYER_SPRITE_CANVAS_SIZE --
# the two must match exactly, or _load_player_sprites() rejects the set.
FINAL_CANVAS_SIZE = (88, 48)


def _detect_car_regions(is_car: "np.ndarray") -> list[tuple[int, int]]:
    """is_car: bool array shaped (width, height). Returns the 5
    contiguous x-ranges (start, end_exclusive) that contain any "car"
    pixel, left to right."""
    col_has = is_car.any(axis=1)
    regions = []
    in_region = False
    start = 0
    for x, has in enumerate(col_has):
        if has and not in_region:
            in_region, start = True, x
        elif not has and in_region:
            in_region = False
            regions.append((start, x))
    if in_region:
        regions.append((start, len(col_has)))
    return regions


def _bbox(is_car: "np.ndarray", x0: int, x1: int) -> tuple[int, int, int, int]:
    """Tight (x0, x1_inclusive, y0, y1_inclusive) bounding box of "car"
    pixels within source columns [x0, x1)."""
    sub = is_car[x0:x1, :]
    xs = np.where(sub.any(axis=1))[0]
    ys = np.where(sub.any(axis=0))[0]
    return xs.min() + x0, xs.max() + x0, ys.min(), ys.max()


def build_sprites(sheet_path: Path = SOURCE_SHEET) -> dict[str, pygame.Surface]:
    sheet = pygame.image.load(str(sheet_path)).convert_alpha()
    alpha = pygame.surfarray.pixels_alpha(sheet).copy()  # (w, h)
    is_car = alpha > ALPHA_THRESHOLD

    regions = _detect_car_regions(is_car)
    if len(regions) != len(POSE_NAMES):
        raise ValueError(
            f"expected {len(POSE_NAMES)} car regions in {sheet_path.name}, found {len(regions)}: {regions}"
        )

    boxes = {}
    max_w = max_h = 0
    for name, (x0, x1) in zip(POSE_NAMES, regions):
        bx0, bx1, by0, by1 = _bbox(is_car, x0, x1)
        boxes[name] = (bx0, bx1, by0, by1)
        max_w = max(max_w, bx1 - bx0 + 1)
        max_h = max(max_h, by1 - by0 + 1)

    native_w = max_w + 2 * NATIVE_PAD
    native_h = max_h + 2 * NATIVE_PAD
    native_anchor = (native_w // 2, native_h - NATIVE_PAD)

    sprites: dict[str, pygame.Surface] = {}
    for name in POSE_NAMES:
        bx0, bx1, by0, by1 = boxes[name]
        crop_w, crop_h = bx1 - bx0 + 1, by1 - by0 + 1

        # Extract this car's pixels straight from the source sheet
        # (real alpha already gives us clean edges -- no need to
        # rebuild the RGBA data by hand).
        crop = sheet.subsurface(pygame.Rect(bx0, by0, crop_w, crop_h)).copy()

        # Place onto the shared native canvas: bbox bottom (tire
        # contact) at native_anchor's y, bbox horizontal center at
        # native_anchor's x -- the invariant every pose shares.
        native = pygame.Surface((native_w, native_h), pygame.SRCALPHA)
        native.fill((0, 0, 0, 0))
        dest_x = native_anchor[0] - crop_w // 2
        dest_y = native_anchor[1] - crop_h
        native.blit(crop, (dest_x, dest_y))

        # pygame.transform.scale (not smoothscale) -- nearest-neighbor
        # sampling, no interpolation/antialiasing, per the spec.
        final = pygame.transform.scale(native, FINAL_CANVAS_SIZE)
        sprites[name] = final

    return sprites


def main() -> None:
    pygame.init()
    pygame.display.set_mode((100, 100))  # needed for .convert_alpha()
    sprites = build_sprites()
    for name, surf in sprites.items():
        path = HERE / f"player_{name}.png"
        pygame.image.save(surf, str(path))
        print(path, surf.get_size())
    pygame.quit()


if __name__ == "__main__":
    main()
