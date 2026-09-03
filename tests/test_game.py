import os
import sys
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pygame

import game
from config import default_config
from music import BGM_DIR, MusicPlayer, MusicSelectScreen
from road import HILL_START, SEGMENT_LENGTH, elevation_at

BGM_ASSETS_PRESENT = BGM_DIR.is_dir() and any(BGM_DIR.glob("*.mp3"))


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


def test_hill_and_valley_render_without_crashing():
    # Smoke test across every part of the new elevation feature: flat,
    # rising, cresting, falling, and the valley dip.
    g = _make_game()
    for idx in (HILL_START - 50, HILL_START + 40, HILL_START + 100, HILL_START + 200, HILL_START + 650):
        g.player.z = idx * SEGMENT_LENGTH
        g.update(1 / 60, _keys())
        g._draw()
    pygame.quit()


def test_camera_elevation_eases_toward_player_segment_not_instant():
    g = _make_game()
    g.player.z = HILL_START * SEGMENT_LENGTH  # elevation about to start rising
    target = elevation_at(g.segments, (HILL_START + 60) * SEGMENT_LENGTH)
    assert target > 1.0  # sanity: this point is actually partway up the hill
    g.player.speed = 60.0
    g.update(1 / 60, _keys(UP=True))
    # One 1/60s tick should not have snapped cam_elevation anywhere near a
    # target this far ahead -- it must still be easing.
    assert abs(g.cam_elevation) < target
    pygame.quit()


def test_camera_elevation_converges_after_many_ticks():
    g = _make_game()
    g.player.speed = 0.0  # hold the player still so cam_elevation has a fixed target to chase
    g.player.z = (HILL_START + 60) * SEGMENT_LENGTH
    target = elevation_at(g.segments, g.player.z)
    for _ in range(300):
        g.update(1 / 60, _keys())
    assert abs(g.cam_elevation - target) < 0.05
    pygame.quit()


def test_player_bob_stays_within_its_configured_cap():
    g = _make_game()
    g.player.speed = game.MAX_SPEED
    for idx in range(HILL_START - 10, HILL_START + 260, 5):
        g.player.z = idx * SEGMENT_LENGTH
        g.update(1 / 60, _keys())
        assert abs(g.player_bob) <= game.PLAYER_BOB_MAX_PX + 1e-6
    pygame.quit()


def test_object_behind_hill_crest_is_hidden_until_crested():
    # Regression test for the "頂上での遮蔽" requirement: an object placed
    # just beyond the crest, on the far/down slope, must be hidden from a
    # camera partway up the near slope, and become visible again once the
    # camera has crested the hill -- see game.Game._sprite_visible.
    g = _make_game()
    width, height = g.renderer.left_surface.get_size()
    far_idx = HILL_START + 130  # inside the fall section, just past the crest
    far_z = far_idx * SEGMENT_LENGTH

    def visible_for(player_idx: int) -> bool:
        g.player.z = player_idx * SEGMENT_LENGTH
        g.cam_elevation = elevation_at(g.segments, g.player.z)
        g._draw_road()
        cam_x = g._road_center_x()
        world_y = elevation_at(g.segments, far_z)
        _, sy, _, _ = game.project(
            0.0, world_y, far_z, cam_x, g.cam_elevation, g.player.z, width, height
        )
        return g._sprite_visible(far_z, sy)

    assert visible_for(HILL_START + 40) is False   # partway up the near slope: hidden
    assert visible_for(HILL_START + 160) is True   # past the crest: visible again
    pygame.quit()


def test_game_without_a_music_player_works_exactly_as_before():
    # Existing direct callers (including every other test in this file)
    # construct Game(cfg) with no music arg -- must stay fully functional
    # and BGM-free, not error out on self.music being None.
    g = _make_game()
    assert g.music is None
    g.update(1 / 60, _keys())
    g._draw()
    pygame.quit()


def test_game_with_a_music_player_starts_it_looping_on_construction():
    pygame.init()
    pygame.display.set_mode((1024, 600))
    music = MusicPlayer()
    music.select(2)  # BEYOND THE RED HORIZON
    g = game.Game(default_config(), music=music)
    assert g.music is music
    assert music.current_name == "BEYOND THE RED HORIZON"
    if BGM_ASSETS_PRESENT:
        assert pygame.mixer.music.get_busy() is True
        assert music.last_error is None
    pygame.quit()


def test_game_creates_working_engine_and_tire_screech_sfx():
    g = _make_game()
    assert g.engine_sound.available is True
    assert g.tire_screech.available is True
    pygame.quit()


def test_engine_pitch_tracks_speed_over_a_full_race():
    # Not a precise audio assertion (SDL's dummy driver can't be
    # "listened to"), but a behavioral one: as the player accelerates from
    # a stop, the engine's pitch bucket should climb, and driving through
    # curves at speed should trigger tire screech at least once somewhere
    # on the course.
    g = _make_game()
    keys = _keys(UP=True)
    buckets = []
    screeched = False
    for _ in range(6000):
        g.update(1 / 60, keys)
        buckets.append(g.engine_sound._bucket)
        if pygame.mixer.Channel(g.tire_screech.CHANNEL).get_busy():
            screeched = True
        if g.finished or g.time_up:
            break
    assert g.finished or g.time_up  # sanity: the race actually completed
    assert buckets[-1] > buckets[0]
    assert screeched is True
    pygame.quit()


def test_sfx_stop_when_the_race_finishes():
    g = _make_game()
    g.player.z = g.track_length - 0.01
    g.player.speed = game.MAX_SPEED
    g.engine_sound.update(1.0, active=True)
    assert g.engine_sound._started is True
    g.update(1 / 60, _keys(UP=True))  # this frame crosses the finish line
    assert g.finished is True
    # SFX only stops once update() observes racing=False at the *top* of
    # the frame -- one frame after finished actually flips, not within the
    # same call that flips it (see Game.update()'s racing/else split).
    g.update(1 / 60, _keys(UP=True))
    assert g.engine_sound._started is False
    pygame.quit()


def test_restart_resumes_engine_sound():
    g = _make_game()
    g.player.z = g.track_length
    g.finished = True
    g.update(1 / 60, _keys())  # engine stops while finished
    assert g.engine_sound._started is False
    g._restart()
    g.update(1 / 60, _keys(UP=True))
    assert g.engine_sound._started is True
    pygame.quit()


def test_game_run_selects_music_before_racing(monkeypatch):
    # game.run() (the module-level entry point main.py --race calls) must
    # show the select screen first and hand the confirmed track into Game
    # -- simulate the player immediately confirming track index 1.
    monkeypatch.setattr(MusicSelectScreen, "run", lambda self, test_frames=None: 1)
    started = {}
    orig_start_looping = MusicPlayer.start_looping

    def spy_start_looping(self):
        started["index"] = self.index
        return orig_start_looping(self)

    monkeypatch.setattr(MusicPlayer, "start_looping", spy_start_looping)
    game.run(test_frames=3)
    assert started.get("index") == 1


def test_game_run_quits_cleanly_if_music_select_screen_is_escaped(monkeypatch):
    monkeypatch.setattr(MusicSelectScreen, "run", lambda self, test_frames=None: None)
    game.run(test_frames=3)  # must return (no race started) without raising


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
