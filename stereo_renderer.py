"""Shared stereo drawing layer -- Phase 2 (not implemented yet).

Phase 1 only ships the calibrator (see calibration.py), which owns its own
simple test-pattern drawing. This module is the placeholder seam the future
racing game will render through, so game code never has to know about
viewport rectangles, swap/flip, or parallax math directly.

Planned shape (do not build ahead of Phase 2 approval):

    class StereoRenderer:
        def __init__(self, screen: pygame.Surface, cfg: Config): ...

        def begin_frame(self) -> None:
            '''Clear both eye surfaces for a new frame.'''

        def draw_world(self, z_distance: float, draw_fn) -> None:
            '''Call draw_fn(eye_surface, parallax_offset_px) once per eye.
            parallax_offset_px is derived from z_distance and
            cfg.parallax_scale, clamped to a safe max, and applied with
            opposite sign per eye. HUD elements must be drawn separately
            with parallax_offset_px = 0.'''

        def present(self) -> None:
            '''Composite both eye surfaces into cfg.left_viewport /
            cfg.right_viewport on the real screen, honoring swap_eyes and
            the per-eye flip flags.'''

Game logic (`main.py` Phase 2 entry point, physics, AI cars, road
segments) must run its simulation exactly once per frame and only branch
per-eye at the final draw step, via `draw_world`. Never run the simulation
twice for left/right.
"""

raise NotImplementedError(
    "stereo_renderer.py is a Phase 2 placeholder. Phase 1 (calibration.py) "
    "does not use this module."
)
