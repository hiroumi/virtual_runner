"""Headless smoke test: run the calibrator for a few frames with SDL's
dummy video/audio drivers (no real window needed) and make sure it
doesn't crash, then exercise every key binding once."""
import os
import sys
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pygame

import calibration
import phase2_test_scene
from config import default_config


def test_calibrator_runs_headless_for_a_few_frames():
    calibration.run(test_frames=5)


def test_every_key_binding_executes_without_crashing(tmp_path, monkeypatch):
    # The 'S' key saves config.json -- redirect that to a scratch path so
    # this test never touches the real project config.json.
    monkeypatch.setattr(calibration, "save_config", lambda cfg, path=None: None)

    pygame.init()
    pygame.display.set_mode((1024, 600))
    app = calibration.Calibrator(default_config())

    keys = [
        pygame.K_1, pygame.K_2, pygame.K_3, pygame.K_4, pygame.K_5,
        pygame.K_TAB, pygame.K_LEFTBRACKET, pygame.K_RIGHTBRACKET,
        pygame.K_LEFT, pygame.K_RIGHT, pygame.K_UP, pygame.K_DOWN,
        pygame.K_PLUS, pygame.K_MINUS, pygame.K_p, pygame.K_x,
        pygame.K_h, pygame.K_v, pygame.K_f, pygame.K_s, pygame.K_r,
    ]
    for key in keys:
        event = pygame.event.Event(pygame.KEYDOWN, key=key, mod=0)
        assert app._handle_keydown(event) is True
        app._draw()

    # Esc must signal the run loop to stop.
    esc = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE, mod=0)
    assert app._handle_keydown(esc) is False
    pygame.quit()


def test_phase2_test_scene_runs_headless_for_a_few_frames():
    phase2_test_scene.run(test_frames=5)


def test_phase2_every_key_binding_executes_without_crashing(monkeypatch):
    monkeypatch.setattr(phase2_test_scene, "save_config", lambda cfg, path=None: None)

    pygame.init()
    pygame.display.set_mode((1024, 600))
    scene = phase2_test_scene.Phase2TestScene(default_config())

    for key in (pygame.K_UP, pygame.K_DOWN, pygame.K_z, pygame.K_i, pygame.K_f, pygame.K_s):
        event = pygame.event.Event(pygame.KEYDOWN, key=key, mod=0)
        assert scene._handle_keydown(event) is True
        scene._draw()

    esc = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE, mod=0)
    assert scene._handle_keydown(esc) is False
    pygame.quit()


def test_extreme_moves_never_fully_hide_a_viewport():
    pygame.init()
    pygame.display.set_mode((1024, 600))
    app = calibration.Calibrator(default_config())
    app.state.selection = calibration.Selection.LEFT
    for _ in range(2000):
        app._apply_directional(-calibration.STEP_LARGE, -calibration.STEP_LARGE)
    rect = app.cfg.left_viewport
    assert rect.x + rect.width > 0
    assert rect.y + rect.height > 0
    pygame.quit()
