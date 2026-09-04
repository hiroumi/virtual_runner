"""Generates the player car's 5 placeholder sprites (2026-09-05).

No image-generation tool was available for this task, so per the
project's "everything is generated, no external art" approach (see
README's "no original Nintendo art" note, and sfx.py's synthesized
audio for the same philosophy applied to sound), these are built with
plain pygame drawing primitives at a small "native pixel" grid (16
columns x 12 rows), each native pixel drawn as a PIX x PIX block of
solid color -- no antialiasing, no interpolation, so the result is
already crisp blocky pixel art with no scaling step needed at all
(the game draws these 1:1, never scaled, so "nearest-neighbor when
scaled" is satisfied by simply never scaling).

A rear 3/4 "turn" pose is built by shearing each row's column span
sideways by an amount that grows from top (roof, near the pivot) to
bottom (tail, swings the most) -- a deliberately simple approximation
(not a true rotated 3D projection) appropriate for small placeholder
pixel art. `left`/`hard_left` are produced by horizontally flipping
`right`/`hard_right` (explicitly allowed by the spec), so only
`straight`, `right`, and `hard_right` are hand-authored below.

Run this to (re)generate the PNGs:
    python assets/cars/player/generate_placeholder_sprites.py
"""
from __future__ import annotations

from pathlib import Path

import pygame

PIX = 4  # size, in real pixels, of one "native" pixel-art pixel
GRID_COLS = 16
GRID_ROWS = 12
CANVAS_SIZE = (GRID_COLS * PIX, GRID_ROWS * PIX)  # (64, 48)

# Ground-contact + horizontal-center reference point, in real pixels,
# shared by all 5 sprites -- game.py blits each sprite so this exact
# point lands on the player's (cx, cy) each frame, which is what keeps
# the tire contact point and body centerline from jumping when the
# sprite changes (see game.py's PLAYER_SPRITE_ANCHOR).
ANCHOR = (GRID_COLS * PIX // 2, GRID_ROWS * PIX)  # (32, 48): bottom-center

# Virtual-Boy-style red/black-only palette (RGBA) -- matches the rest of
# the project's strict red/black visual language (see game.py's color
# constants): no other hues anywhere, including for taillights, which
# use the palette's brightest step rather than a real taillight's
# orange/red to stay consistent with that constraint.
BLACK = (0, 0, 0, 255)          # outline / window glass / tires only
DARK = (100, 15, 15, 255)       # body shadow / rear valance / underbody gap
MID = (190, 35, 35, 255)        # body base color
BRIGHT = (255, 90, 90, 255)     # body highlight / roof / window pillars
GLOW = (255, 215, 205, 255)     # taillights -- much paler than BRIGHT so they
                                 # read as a distinct light source, not just
                                 # "more body highlight"

TRANSPARENT = (0, 0, 0, 0)

# Each row: a list of (start_col, end_col_exclusive, color) segments, in
# the *straight* (unsheared) pose's coordinates -- symmetric around the
# col7/col8 boundary (pixel x=32), which is exactly ANCHOR's x. Only 10
# columns wide at its widest (cols 3-12), deliberately leaving 3 columns
# of margin on each side so the sheared turn poses have room to lean
# without any part of the car clipping off the 16-column canvas.
STRAIGHT_ROWS: dict[int, list[tuple[int, int, tuple]]] = {
    1: [(7, 9, BRIGHT)],                                              # roof cap
    2: [(6, 7, BRIGHT), (7, 9, BLACK), (9, 10, BRIGHT)],              # rear window
    3: [(6, 7, BRIGHT), (7, 9, BLACK), (9, 10, BRIGHT)],              # rear window
    4: [(5, 10, MID)],                                                 # body shoulder
    5: [(4, 7, MID), (7, 9, BRIGHT), (9, 11, MID)],                    # body + crease
    6: [(3, 7, MID), (7, 9, BRIGHT), (9, 12, MID)],                    # body + crease
    7: [(3, 12, MID)],                                                 # body, widest
    8: [(3, 5, GLOW), (5, 10, DARK), (10, 12, GLOW)],                  # bumper + tails
    9: [(3, 5, GLOW), (5, 10, DARK), (10, 12, GLOW)],                  # bumper + tails
    10: [(2, 4, BLACK), (4, 11, DARK), (11, 13, BLACK)],               # valance + tires
    11: [(2, 4, BLACK), (4, 11, DARK), (11, 13, BLACK)],               # contact row --
                                                                         # DARK (not BLACK)
                                                                         # under the body so
                                                                         # the tires read as
                                                                         # distinctly darker
}

# How far (in native columns) the bottom row shears at full ("hard")
# turn intensity -- roof rows (low row index) shear proportionally less
# since the formula scales by row/max_row, reading as "the roof stays
# put while the tail swings out," a simple stand-in for perspective
# rotation. 2 columns of headroom on each side (see STRAIGHT_ROWS'
# comment) keeps every element on-canvas even at MAX_SHIFT_COLS.
MAX_SHIFT_COLS = 2.0


def _sheared_rows(mag: float) -> dict[int, list[tuple[int, int, tuple]]]:
    """`mag` > 0 shifts toward higher column numbers (the "right" lean);
    build `left` by flipping a `mag` > 0 render instead of calling this
    with a negative `mag`."""
    max_row = max(STRAIGHT_ROWS.keys())
    out: dict[int, list[tuple[int, int, tuple]]] = {}
    for row, segments in STRAIGHT_ROWS.items():
        shift = round(mag * MAX_SHIFT_COLS * (row / max_row))
        out[row] = [(start + shift, end + shift, color) for start, end, color in segments]
    return out


def _render(rows: dict[int, list[tuple[int, int, tuple]]]) -> pygame.Surface:
    surf = pygame.Surface(CANVAS_SIZE, pygame.SRCALPHA)
    surf.fill(TRANSPARENT)
    for row, segments in rows.items():
        y = row * PIX
        for start_col, end_col, color in segments:
            start_col = max(0, min(GRID_COLS, start_col))
            end_col = max(0, min(GRID_COLS, end_col))
            if end_col <= start_col:
                continue
            rect = (start_col * PIX, y, (end_col - start_col) * PIX, PIX)
            surf.fill(color, rect)
    return surf


def build_sprites() -> dict[str, pygame.Surface]:
    """Returns all 5 poses, keyed exactly as game.py's PLAYER_SPRITE_KEYS
    expects. `left`/`hard_left` are pygame.transform.flip() of
    `right`/`hard_right` -- explicitly permitted by the spec, and keeps
    the two turn directions guaranteed-symmetric by construction rather
    than by two independently hand-tuned designs."""
    straight = _render(STRAIGHT_ROWS)
    right = _render(_sheared_rows(0.5))
    hard_right = _render(_sheared_rows(1.0))
    left = pygame.transform.flip(right, True, False)
    hard_left = pygame.transform.flip(hard_right, True, False)
    return {
        "hard_left": hard_left,
        "left": left,
        "straight": straight,
        "right": right,
        "hard_right": hard_right,
    }


def main() -> None:
    pygame.init()
    # A real display surface isn't needed for SRCALPHA Surface creation/
    # saving, but pygame.Surface with per-pixel alpha works without one
    # regardless -- no pygame.display.set_mode() call needed here.
    out_dir = Path(__file__).resolve().parent
    for name, surf in build_sprites().items():
        path = out_dir / f"player_{name}.png"
        pygame.image.save(surf, str(path))
        print(path)
    pygame.quit()


if __name__ == "__main__":
    main()
