"""Builds the 6 assets/scenery/palms/*.png roadside palm tree sprites
(2026-09-05) from assets/source/palm_trees_sheet.png -- a 3-col x 2-row
sheet the user supplied, read left-to-right, top-to-bottom as:
palm_straight, palm_lean_left, palm_lean_right / palm_short_wide,
palm_windblown, palm_pair.

Like the enemy-car sheet (see scripts/build_enemy_sprites.py), this
sheet's alpha channel is fully opaque -- the "transparent" look is a
solid cyan chroma-key background baked into RGB, not real transparency.
Background removal uses a direct color test (green and blue channels
both high, red channel low -- true of the chroma-key, false of every
red/dark-red/black/light-red tree color) applied to the **whole image**,
not a border-connected flood fill. A border flood fill (as
build_enemy_sprites.py uses, to protect legitimate interior content like
windows/highlights) was tried first, but this sheet has no such
content -- the palette is exclusively tree colors -- and
palm_windblown's separated, curling fronds turned out to enclose small
cyan pockets that a flood fill can't reach from the sheet's outer
border, leaving near-pure-cyan islands (e.g. RGB~[1,233,255]) sitting
inside the art. The direct threshold removes those too, and is safe
specifically because the color test can never fire on real tree pixels.

Unlike the enemy cars (where a shared scale factor across all 6 types
caused a real sizing bug -- see build_enemy_sprites.py's docstring),
palms are scaled by ONE shared factor deliberately: game.py sizes each
palm at runtime from its own *measured opaque height* (see
Game._palm_sprite_opaque_heights), never from raw canvas dimensions, so
a shared canvas with different fill ratios per tree can't repeat that
bug here -- the lesson was applied proactively instead of needing a
second bugfix round.

Run this to rebuild the 6 PNGs from the source sheet (e.g. after the
user supplies a revised sheet):
    python scripts/build_palm_sprites.py
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pygame

ROOT = Path(__file__).resolve().parent.parent
SOURCE_SHEET = ROOT / "assets" / "source" / "palm_trees_sheet.png"
OUTPUT_DIR = ROOT / "assets" / "scenery" / "palms"

GRID_COLS = 3
GRID_ROWS = 2
# Reading order left-to-right, top-to-bottom, per
# CLAUDE_CODE_PALM_TREES_INSTRUCTIONS.txt.
SPRITE_NAMES = [
    "palm_straight", "palm_lean_left", "palm_lean_right",
    "palm_short_wide", "palm_windblown", "palm_pair",
]

# A pixel counts as "cyan background" if its green or blue channel
# exceeds its red channel by more than SPILL_MARGIN. Every genuine tree
# color in this sheet -- trunk/frond samples range from near-black
# through dark red ([84,6,6]) to the brightest pink highlights
# ([255,110-170,105-170]) -- keeps red as the clearly dominant channel;
# only the cyan background (~[12,243,248]) and its anti-aliased blend
# with tree edges (sampled down to ~[22,83,90], still green/blue >> red)
# ever cross this. A first version used a "both G and B high, R low"
# test instead (closer to build_enemy_sprites.py's), which correctly
# caught the solid background but left a visible speckle of dim
# cyan-tinted edge-blend pixels that didn't happen to be bright enough
# to trip it -- this channel-dominance test catches those too, since
# they still have G or B above R by a wide margin even at low overall
# brightness.
SPILL_MARGIN = 10

CROP_PAD = 4  # native-resolution px kept around each tree's tight bbox

# One shared scale factor for all 6 (see module docstring for why this
# is safe here, unlike the first enemy-car attempt) -- sized so the
# tallest source tree lands at this many native px tall. Downscaled
# further at runtime per-palm; this only controls how much pixel detail
# is preserved in the stored PNGs.
TARGET_MAX_NATIVE_HEIGHT_PX = 150
CANVAS_PAD = 6  # transparent margin (px) kept around the tallest scaled tree


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
    is_bg_candidate = (g > r + SPILL_MARGIN) | (b > r + SPILL_MARGIN)
    # A border-connected flood fill (matching build_enemy_sprites.py) was
    # tried first, but this art's palette is exclusively red/dark-red/
    # black/light-red -- there's no legitimate in-tree content that could
    # ever match is_bg_candidate, unlike the enemy-car sheet's windows/
    # highlights. Verified: palm_windblown in particular has small cyan
    # pockets enclosed *within* its frond silhouette (gaps between
    # separated frond tips) that aren't 4-connected to the sheet's outer
    # border -- a pure flood fill leaves those as near-pure cyan islands
    # (e.g. RGB~[1,233,255]) sitting inside otherwise-transparent art. A
    # direct global threshold (no connectivity requirement) removes both
    # the border-connected background *and* these interior pockets, and
    # is safe here specifically because the color test can't ever fire on
    # real tree pixels.
    is_bg = is_bg_candidate
    is_tree = ~is_bg

    cell_w, cell_h = w // GRID_COLS, h // GRID_ROWS

    crops: dict[str, pygame.Surface] = {}
    native_heights: dict[str, int] = {}
    for row in range(GRID_ROWS):
        for col in range(GRID_COLS):
            name = SPRITE_NAMES[row * GRID_COLS + col]
            cx0, cx1 = col * cell_w, (col + 1) * cell_w
            cy0, cy1 = row * cell_h, (row + 1) * cell_h
            bx0, bx1, by0, by1 = _tight_bbox(is_tree, cx0, cx1, cy0, cy1)
            bx0 = max(cx0, bx0 - CROP_PAD)
            by0 = max(cy0, by0 - CROP_PAD)
            bx1 = min(cx1 - 1, bx1 + CROP_PAD)
            by1 = min(cy1 - 1, by1 + CROP_PAD)
            crop_w, crop_h = bx1 - bx0 + 1, by1 - by0 + 1

            crop = pygame.Surface((crop_w, crop_h), pygame.SRCALPHA)
            crop.fill((0, 0, 0, 0))
            tree_mask = is_tree[bx0 : bx1 + 1, by0 : by1 + 1]
            crop_rgb = rgb[bx0 : bx1 + 1, by0 : by1 + 1, :].astype(np.uint8)
            alpha = np.where(tree_mask, 255, 0).astype(np.uint8)
            px = pygame.surfarray.pixels3d(crop)
            pa = pygame.surfarray.pixels_alpha(crop)
            px[:, :, :] = crop_rgb
            pa[:, :] = alpha
            del px, pa

            crops[name] = crop
            native_heights[name] = crop_h

    shared_scale = TARGET_MAX_NATIVE_HEIGHT_PX / max(native_heights.values())

    scaled: dict[str, pygame.Surface] = {}
    max_scaled_w = max_scaled_h = 0
    for name, crop in crops.items():
        native_w, native_h = crop.get_size()
        scaled_w = max(1, round(native_w * shared_scale))
        scaled_h = max(1, round(native_h * shared_scale))
        # pygame.transform.scale (not smoothscale) -- nearest-neighbor
        # sampling, no interpolation/antialiasing, per the spec.
        scaled[name] = pygame.transform.scale(crop, (scaled_w, scaled_h))
        max_scaled_w = max(max_scaled_w, scaled_w)
        max_scaled_h = max(max_scaled_h, scaled_h)

    canvas_w = max_scaled_w + 2 * CANVAS_PAD
    canvas_h = max_scaled_h + 2 * CANVAS_PAD
    anchor = (canvas_w // 2, canvas_h - CANVAS_PAD)  # root (trunk base) center

    sprites: dict[str, pygame.Surface] = {}
    for name, surf in scaled.items():
        sw, sh = surf.get_size()
        canvas = pygame.Surface((canvas_w, canvas_h), pygame.SRCALPHA)
        canvas.fill((0, 0, 0, 0))
        dest_x = anchor[0] - sw // 2
        dest_y = anchor[1] - sh
        canvas.blit(surf, (dest_x, dest_y))
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
