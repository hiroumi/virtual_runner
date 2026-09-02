import os
import sys
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pygame

import game
from config import default_config


class FakeKeys(dict):
    def __getitem__(self, k):
        return self.get(k, False)


def _keys(**pressed):
    k = FakeKeys()
    for name, value in pressed.items():
        k[getattr(pygame, f"K_{name}")] = value
    return k


def _make_game():
    pygame.init()
    pygame.display.set_mode((1024, 600))
    return game.Game(default_config())


def test_game_runs_headless_for_a_few_frames():
    game.run(test_frames=5)


def test_accelerating_increases_speed_up_to_max():
    g = _make_game()
    keys = _keys(UP=True)
    for _ in range(300):
        g.update(1 / 60, keys)
    assert g.player.speed == game.MAX_SPEED
    pygame.quit()


def test_coasting_decelerates_to_zero():
    g = _make_game()
    g.player.speed = game.MAX_SPEED
    keys = _keys()
    for _ in range(300):
        g.update(1 / 60, keys)
    assert g.player.speed == 0.0
    pygame.quit()


def test_offroad_caps_speed_lower_than_onroad():
    g = _make_game()
    g.player.x = 1.5  # off the road (|x| > 1.0)
    keys = _keys(UP=True)
    for _ in range(300):
        g.update(1 / 60, keys)
    assert g.player.speed == game.OFFROAD_MAX_SPEED
    pygame.quit()


def test_collision_with_traffic_car_reduces_speed():
    g = _make_game()
    g.player.speed = game.MAX_SPEED
    car = g.traffic[0]
    g.player.z = car.z
    g.player.x = car.x
    before = g.player.speed
    g.update(1 / 60, _keys())
    assert g.player.speed < before
    pygame.quit()


def test_collision_cooldown_prevents_repeated_penalty_same_frame_cluster():
    g = _make_game()
    g.player.speed = game.MAX_SPEED
    car = g.traffic[0]
    g.player.z = car.z
    g.player.x = car.x
    g.update(1 / 60, _keys())
    speed_after_first_hit = g.player.speed
    g.update(1 / 60, _keys())
    # still within cooldown -> no second penalty this tick
    assert g.player.speed == speed_after_first_hit or g.player.speed < speed_after_first_hit
    assert g.collision_cooldown > 0.0
    pygame.quit()


def test_reaching_track_end_sets_finished():
    g = _make_game()
    g.player.z = g.track_length - 0.01
    g.player.speed = game.MAX_SPEED
    g.update(1 / 60, _keys(UP=True))
    assert g.finished is True
    pygame.quit()


def test_time_running_out_sets_time_up():
    g = _make_game()
    g.time_left = 0.001
    g.update(1 / 60, _keys())
    assert g.time_up is True
    pygame.quit()


def test_finished_state_freezes_simulation():
    g = _make_game()
    g.player.z = g.track_length
    g.finished = True
    z_before = g.player.z
    score_before = g.score
    g.update(1 / 60, _keys(UP=True))
    assert g.player.z == z_before
    assert g.score == score_before
    pygame.quit()


def test_restart_resets_state():
    g = _make_game()
    g.player.z = 500.0
    g.finished = True
    g.score = 1234.0
    g._restart()
    assert g.player.z == 0.0
    assert g.finished is False
    assert g.score == 0.0
    pygame.quit()


def test_every_key_binding_executes_without_crashing(monkeypatch):
    monkeypatch.setattr(game, "save_config", lambda cfg, path=None: None)
    g = _make_game()
    keys = [
        pygame.K_LEFTBRACKET, pygame.K_RIGHTBRACKET, pygame.K_z, pygame.K_i,
        pygame.K_d, pygame.K_f, pygame.K_s, pygame.K_r,
    ]
    for key in keys:
        event = pygame.event.Event(pygame.KEYDOWN, key=key, mod=0)
        assert g._handle_keydown(event) is True
        g._draw()
    esc = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE, mod=0)
    assert g._handle_keydown(esc) is False
    pygame.quit()
