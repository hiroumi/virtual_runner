import os
import random
import sys
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pygame
import pytest

import game
from config import default_config
from music import BGM_DIR, MusicPlayer, MusicSelectScreen
from road import HILL_START, SEGMENT_LENGTH, elevation_at
from sfx import ENGINE_PRESET_ORDER, TIRE_SCREECH_PRESET_ORDER

BGM_ASSETS_PRESENT = BGM_DIR.is_dir() and any(BGM_DIR.glob("*.mp3"))
PLAYER_SPRITE_ASSETS_PRESENT = all(
    (game.PLAYER_ASSETS_DIR / f"player_{key}.png").is_file() for key in game.PLAYER_SPRITE_KEYS
)
ENEMY_SPRITE_ASSETS_PRESENT = all(
    (game.ENEMY_ASSETS_DIR / f"{key}.png").is_file() for key in game.ENEMY_SPRITE_KEYS
)


@pytest.fixture(autouse=True)
def _reset_player_sprite_cache():
    # game._load_player_sprites() caches at module level (deliberately,
    # so repeated Game() construction across Restart/Reset doesn't
    # re-decode 5 PNGs from disk every time) -- reset it before every
    # test so one test poisoning it (e.g. simulating missing assets)
    # can't leak into another.
    game._player_sprites_cache["loaded"] = False
    game._player_sprites_cache["sprites"] = {}
    yield
    game._player_sprites_cache["loaded"] = False
    game._player_sprites_cache["sprites"] = {}


@pytest.fixture(autouse=True)
def _reset_enemy_sprite_cache():
    # Same reasoning as _reset_player_sprite_cache above, for
    # game._load_enemy_sprites()'s module-level cache.
    game._enemy_sprites_cache["loaded"] = False
    game._enemy_sprites_cache["sprites"] = {}
    yield
    game._enemy_sprites_cache["loaded"] = False
    game._enemy_sprites_cache["sprites"] = {}


class FakeKeys(dict):
    def __getitem__(self, k):
        return self.get(k, False)


def _keys(**pressed):
    k = FakeKeys()
    for name, value in pressed.items():
        k[getattr(pygame, f"K_{name}")] = value
    return k


class FakeController:
    """Minimal stand-in for pygame._sdl2.controller.Controller, for
    exercising Game's 2026-09-04 gamepad wiring without real hardware --
    see gamepad.read_steer/read_accel/read_brake, which only ever call
    get_axis()/get_button() on whatever's passed in."""

    def __init__(self, axes=None, buttons=None):
        self._axes = axes or {}
        self._buttons = set(buttons or ())

    def get_axis(self, axis):
        return self._axes.get(axis, 0)

    def get_button(self, button):
        return button in self._buttons


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


def test_debug_overlay_shows_a_reason_when_sfx_is_unavailable(monkeypatch):
    # 2026-09-04: real-hardware report was the engine SFX simply never
    # triggering -- this is the diagnostic path added so the D-key
    # overlay can say why instead of just "unavailable".
    monkeypatch.setattr(pygame.mixer, "get_init", lambda: (44100, -16, 6))
    g = _make_game()
    assert g.engine_sound.available is False
    assert g.tire_screech.available is False
    g.show_debug = True
    g._draw()  # must not raise
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


def test_tire_screech_triggers_frequently_over_a_full_race():
    # Regression test for the 2026-09-04 threshold change: the old
    # TIRE_SCREECH_THRESHOLD=0.15 only crossed twice in a full lap
    # (~2.7s of screech out of ~74s total) -- reported as "実感できない"
    # (can't feel it). The lowered threshold should make screech play a
    # substantial fraction of the lap, not just a couple of rare blips.
    g = _make_game()
    keys = _keys(UP=True)
    screeching_frames = 0
    total_frames = 0
    for _ in range(6000):
        g.update(1 / 60, keys)
        total_frames += 1
        if pygame.mixer.Channel(g.tire_screech.CHANNEL).get_busy():
            screeching_frames += 1
        if g.finished or g.time_up:
            break
    assert g.finished or g.time_up  # sanity: the race actually completed
    assert screeching_frames / total_frames > 0.2  # well above the old ~3.6%
    pygame.quit()


def test_sfx_stop_when_the_race_finishes():
    g = _make_game()
    g.player.z = g.track_length - 0.01
    g.player.speed = game.MAX_SPEED
    g.engine_sound.update(1.0, active=True, dt=1 / 60)
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
        pygame.K_d, pygame.K_f, pygame.K_s, pygame.K_r, pygame.K_e, pygame.K_t,
    ]
    for key in keys:
        event = pygame.event.Event(pygame.KEYDOWN, key=key, mod=0)
        assert g._handle_keydown(event) is True
        g._draw()
    esc = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE, mod=0)
    assert g._handle_keydown(esc) is False
    assert g._outcome == "quit"
    pygame.quit()


# -- engine preset cycling (`E` key, 2026-09-04 engine-sound redesign) ----


def test_e_key_cycles_to_the_next_engine_preset():
    g = _make_game()
    start = g.engine_sound.preset_name
    g._cycle_engine_preset()
    assert g.engine_sound.preset_name != start
    assert g.engine_sound.preset_name in ENGINE_PRESET_ORDER
    pygame.quit()


def test_e_key_wraps_around_after_cycling_through_every_preset():
    g = _make_game()
    original = g.engine_sound.preset_name
    for _ in range(len(ENGINE_PRESET_ORDER)):
        g._cycle_engine_preset()
    assert g.engine_sound.preset_name == original
    pygame.quit()


def test_e_key_sets_a_flash_message_that_expires():
    g = _make_game()
    g._cycle_engine_preset()
    assert g._preset_flash_name == f"ENGINE: {g.engine_sound.preset_name}"
    assert pygame.time.get_ticks() < g._preset_flash_until_ms
    g._draw()  # must not crash while the flash is showing
    pygame.quit()


def test_preset_flash_is_included_via_handle_keydown():
    g = _make_game()
    start = g.engine_sound.preset_name
    event = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_e, mod=0)
    assert g._handle_keydown(event) is True
    assert g.engine_sound.preset_name != start
    pygame.quit()


# -- tire screech preset cycling (`T` key, 2026-09-04) --------------------


def test_t_key_cycles_to_the_next_tire_screech_preset():
    g = _make_game()
    start = g.tire_screech.preset_name
    g._cycle_tire_preset()
    assert g.tire_screech.preset_name != start
    assert g.tire_screech.preset_name in TIRE_SCREECH_PRESET_ORDER
    pygame.quit()


def test_t_key_wraps_around_after_cycling_through_every_preset():
    g = _make_game()
    original = g.tire_screech.preset_name
    for _ in range(len(TIRE_SCREECH_PRESET_ORDER)):
        g._cycle_tire_preset()
    assert g.tire_screech.preset_name == original
    pygame.quit()


def test_t_key_sets_a_flash_message_that_expires():
    g = _make_game()
    g._cycle_tire_preset()
    assert g._preset_flash_name == f"TIRE: {g.tire_screech.preset_name}"
    assert pygame.time.get_ticks() < g._preset_flash_until_ms
    g._draw()  # must not crash while the flash is showing
    pygame.quit()


def test_t_key_via_handle_keydown_switches_the_tire_preset():
    g = _make_game()
    start = g.tire_screech.preset_name
    event = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_t, mod=0)
    assert g._handle_keydown(event) is True
    assert g.tire_screech.preset_name != start
    pygame.quit()


def test_engine_and_tire_preset_flashes_do_not_interfere_with_each_other():
    g = _make_game()
    g._cycle_engine_preset()
    assert g._preset_flash_name.startswith("ENGINE:")
    g._cycle_tire_preset()
    assert g._preset_flash_name.startswith("TIRE:")  # latest flash wins
    pygame.quit()


# -- Maker Faire "Reset" (Backspace / held gamepad Select-Back) ------------


def test_backspace_ends_the_key_loop_and_marks_the_outcome_as_reset():
    g = _make_game()
    event = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_BACKSPACE, mod=0)
    assert g._handle_keydown(event) is False
    assert g._outcome == "reset"
    pygame.quit()


def test_trigger_reset_clears_race_state_like_restart_does():
    g = _make_game()
    g.player.z = 500.0
    g.player.x = 1.5
    g.player.speed = 50.0
    g.score = 1234.0
    g.time_left = 10.0
    g.collision_cooldown = 0.5
    g.finished = True
    g.time_up = True
    g._trigger_reset()
    assert g.player.z == 0.0
    assert g.player.x == 0.0
    assert g.player.speed == 0.0
    assert g.score == 0.0
    assert g.time_left == game.RACE_TIME
    assert g.collision_cooldown == 0.0
    assert g.finished is False
    assert g.time_up is False
    pygame.quit()


def test_trigger_reset_rebuilds_traffic_to_its_starting_state():
    g = _make_game()
    original_positions = [car.z for car in g.traffic]
    for car in g.traffic:
        car.z += 999.0
    g._trigger_reset()
    assert [car.z for car in g.traffic] == original_positions
    pygame.quit()


def test_trigger_reset_stops_engine_and_tire_sfx():
    g = _make_game()
    g.update(1 / 60, _keys(UP=True))  # get the engine sound actually started
    assert g.engine_sound._started is True
    g._trigger_reset()
    assert g.engine_sound._started is False
    pygame.quit()


@pytest.mark.skipif(not BGM_ASSETS_PRESENT, reason="bgm/ assets not present")
def test_trigger_reset_stops_the_bgm():
    pygame.init()
    pygame.display.set_mode((1024, 600))
    music = MusicPlayer()
    music.select(2)  # BEYOND THE RED HORIZON
    g = game.Game(default_config(), music=music)
    assert pygame.mixer.music.get_busy() is True
    g._trigger_reset()
    assert pygame.mixer.music.get_busy() is False
    pygame.quit()


def test_trigger_reset_sets_the_outcome_to_reset():
    g = _make_game()
    g._trigger_reset()
    assert g._outcome == "reset"
    pygame.quit()


def test_restart_is_unaffected_by_and_distinct_from_reset():
    # Restart (R) must NOT stop the BGM/SFX or mark the outcome as
    # "reset" -- that's exactly the behavior that's supposed to be unique
    # to Backspace/gamepad-hold Reset.
    pygame.init()
    pygame.display.set_mode((1024, 600))
    music = MusicPlayer()
    music.select(1)  # CRIMSON HIGHWAY
    g = game.Game(default_config(), music=music)
    g.score = 500.0
    g._restart()
    assert g.score == 0.0  # restart still clears race state...
    assert g._outcome == "quit"  # ...but does not request a session reset
    if BGM_ASSETS_PRESENT:
        assert pygame.mixer.music.get_busy() is True  # BGM keeps playing
        assert music.current_name == "CRIMSON HIGHWAY"  # selection unchanged
    pygame.quit()


def test_reset_does_not_touch_config_or_the_calibrated_viewport(monkeypatch):
    called = []
    monkeypatch.setattr(game, "save_config", lambda cfg, path=None: called.append(cfg))
    g = _make_game()
    left_before = g.cfg.left_viewport
    right_before = g.cfg.right_viewport
    parallax_before = g.cfg.parallax_scale
    g._trigger_reset()
    assert called == []
    assert g.cfg.left_viewport == left_before
    assert g.cfg.right_viewport == right_before
    assert g.cfg.parallax_scale == parallax_before
    pygame.quit()


def test_repeated_resets_do_not_crash():
    g = _make_game()
    for i in range(5):
        g.player.z = 100.0 * (i + 1)
        g.score = 50.0
        g.update(1 / 60, _keys(UP=True))
        g._trigger_reset()
        assert g.player.z == 0.0
        assert g.score == 0.0
    pygame.quit()


def test_backspace_during_the_race_returns_to_select_screen_and_starts_a_new_race(monkeypatch):
    # Full integration through the module-level game.run() loop: a
    # Backspace keypress mid-race must end that race, bring back SELECT
    # MUSIC (not quit the app), and then let a brand new race start
    # normally -- exactly the "next visitor" flow this feature exists for.
    calls = []

    def fake_select_run(self, test_frames=None):
        calls.append(self.music.index)
        self.music.select(0)
        return 0

    monkeypatch.setattr(MusicSelectScreen, "run", fake_select_run)
    pygame.init()
    pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_BACKSPACE, mod=0))
    game.run(test_frames=3)  # must not raise
    # Called once for the initial screen, once more after the reset.
    assert len(calls) == 2


def test_game_run_loops_back_to_select_screen_when_a_race_returns_reset(monkeypatch):
    outcomes = iter(["reset", "quit"])
    monkeypatch.setattr(game.Game, "run", lambda self, test_frames=None: next(outcomes))
    select_screen_runs = []

    def counting_select_run(self, test_frames=None):
        select_screen_runs.append(1)
        self.music.select(0)
        return 0

    monkeypatch.setattr(MusicSelectScreen, "run", counting_select_run)
    game.run(test_frames=3)
    assert len(select_screen_runs) == 2  # looped back exactly once after "reset"


def test_game_run_resets_when_the_gamepad_hold_triggers(monkeypatch):
    monkeypatch.setattr(game.GamepadResetHold, "triggered", lambda self: True)
    g = _make_game()
    outcome = g.run(test_frames=3)
    assert outcome == "reset"
    pygame.quit()


# -- Xbox controller racing input (2026-09-04) -----------------------------
# Real hardware (does Windows' Xbox controller actually get recognized as
# an SDL game controller, do the diagnostics print sensible values, does
# steering/accel/brake feel right) can't be verified in this environment --
# see docs/PHASE2_RACE_LOG.md. These exercise the wiring with a fake
# Controller double instead.


def test_gamepad_a_button_accelerates_like_up_arrow():
    g = _make_game()
    gamepad = FakeController(buttons={pygame.CONTROLLER_BUTTON_A})
    for _ in range(120):
        g.update(1 / 60, _keys(), gamepad)
    assert g.player.speed > 0.0
    pygame.quit()


def test_gamepad_b_button_brakes_like_down_arrow():
    g = _make_game()
    g.player.speed = game.MAX_SPEED
    gamepad = FakeController(buttons={pygame.CONTROLLER_BUTTON_B})
    g.update(1 / 60, _keys(), gamepad)
    assert g.player.speed < game.MAX_SPEED
    pygame.quit()


def test_gamepad_dpad_up_also_accelerates():
    # 2026-09-05: added as an alternative to A, not a replacement.
    g = _make_game()
    gamepad = FakeController(buttons={pygame.CONTROLLER_BUTTON_DPAD_UP})
    for _ in range(120):
        g.update(1 / 60, _keys(), gamepad)
    assert g.player.speed > 0.0
    pygame.quit()


def test_gamepad_dpad_down_also_brakes():
    g = _make_game()
    g.player.speed = game.MAX_SPEED
    gamepad = FakeController(buttons={pygame.CONTROLLER_BUTTON_DPAD_DOWN})
    g.update(1 / 60, _keys(), gamepad)
    assert g.player.speed < game.MAX_SPEED
    pygame.quit()


def test_gamepad_left_stick_up_also_accelerates():
    g = _make_game()
    gamepad = FakeController(axes={pygame.CONTROLLER_AXIS_LEFTY: -32768})
    for _ in range(120):
        g.update(1 / 60, _keys(), gamepad)
    assert g.player.speed > 0.0
    pygame.quit()


def test_gamepad_left_stick_down_also_brakes():
    g = _make_game()
    g.player.speed = game.MAX_SPEED
    gamepad = FakeController(axes={pygame.CONTROLLER_AXIS_LEFTY: 32767})
    g.update(1 / 60, _keys(), gamepad)
    assert g.player.speed < game.MAX_SPEED
    pygame.quit()


def test_gamepad_dpad_steers_the_car():
    g = _make_game()
    g.player.speed = game.MAX_SPEED
    right = FakeController(buttons={pygame.CONTROLLER_BUTTON_DPAD_RIGHT})
    g.update(1 / 60, _keys(), right)
    assert g.player.x > 0.0
    pygame.quit()


def test_gamepad_analog_stick_steers_the_car():
    g = _make_game()
    g.player.speed = game.MAX_SPEED
    left_stick = FakeController(axes={pygame.CONTROLLER_AXIS_LEFTX: -32768})
    g.update(1 / 60, _keys(), left_stick)
    assert g.player.x < 0.0
    pygame.quit()


def test_gamepad_steer_within_deadzone_does_not_move_the_car():
    # Center-position drift on a real stick must never steer -- see
    # gamepad.STEER_DEADZONE.
    g = _make_game()
    g.player.speed = game.MAX_SPEED
    drifting = FakeController(axes={pygame.CONTROLLER_AXIS_LEFTX: 2000})  # well under the deadzone
    x_before = g.player.x
    g.update(1 / 60, _keys(), drifting)
    assert g.player.x == x_before
    pygame.quit()


def test_gamepad_and_keyboard_steering_can_be_used_together():
    # Neither input method is exclusive -- both keep working simultaneously.
    g = _make_game()
    g.player.speed = game.MAX_SPEED
    right = FakeController(buttons={pygame.CONTROLLER_BUTTON_DPAD_RIGHT})
    g.update(1 / 60, _keys(RIGHT=True), right)
    assert g.player.x > 0.0  # still steers, not confused by two input sources agreeing
    pygame.quit()


def test_game_update_works_with_no_gamepad_argument_at_all():
    # Default value (gamepad=None) -- existing keyboard-only callers
    # (every other test in this file) must keep working unmodified.
    g = _make_game()
    g.update(1 / 60, _keys(UP=True))
    assert g.player.speed > 0.0
    pygame.quit()


def test_start_button_restarts_the_race():
    g = _make_game()
    g.score = 500.0
    g.finished = True
    event = pygame.event.Event(pygame.CONTROLLERBUTTONDOWN, button=pygame.CONTROLLER_BUTTON_START, instance_id=0)
    g._handle_controller_button_down(event)
    assert g.score == 0.0
    assert g.finished is False
    pygame.quit()


def test_start_button_does_not_trigger_a_reset():
    g = _make_game()
    event = pygame.event.Event(pygame.CONTROLLERBUTTONDOWN, button=pygame.CONTROLLER_BUTTON_START, instance_id=0)
    g._handle_controller_button_down(event)
    assert g._outcome == "quit"  # Restart, not Reset
    pygame.quit()


def test_back_button_down_event_still_feeds_the_reset_hold():
    g = _make_game()
    event = pygame.event.Event(pygame.CONTROLLERBUTTONDOWN, button=pygame.CONTROLLER_BUTTON_BACK, instance_id=0)
    g._handle_controller_button_down(event)
    assert g.gamepad_reset_hold._started_ms is not None
    pygame.quit()


def test_a_button_press_does_not_restart_the_race():
    g = _make_game()
    g.score = 500.0
    event = pygame.event.Event(pygame.CONTROLLERBUTTONDOWN, button=pygame.CONTROLLER_BUTTON_A, instance_id=0)
    g._handle_controller_button_down(event)
    assert g.score == 500.0
    pygame.quit()


# -- player car sprites (2026-09-05) ----------------------------------------
# Real-hardware verification (does the sprite actually look like the
# intended direction, does the shear read clearly through the lenses) is
# out of reach here -- see docs/PHASE2_RACE_LOG.md. These check the
# selection logic, the anchor/canvas invariants that keep the car from
# jumping when the sprite changes, and that switching sprites never
# touches physics/collision state.


def _settle(g, keys=None, gamepad=None, seconds=2.0, dt=1 / 60):
    """Steps update() long enough for the smoothed player_visual_steer
    (and therefore the sprite category) to settle -- mirrors test_sfx.py's
    _run_to_target for engine RPM. Real gameplay never snaps the sprite
    straight to a category; tests that need a settled state simulate
    enough elapsed time instead of poking internal state directly."""
    keys = keys if keys is not None else _keys()
    for _ in range(max(1, int(seconds / dt))):
        g.update(dt, keys, gamepad)


def test_player_sprite_defaults_to_straight():
    g = _make_game()
    assert game.PLAYER_SPRITE_KEYS[g._player_sprite_index] == "straight"
    pygame.quit()


def test_player_sprite_switches_to_hard_left_holding_keyboard_left():
    g = _make_game()
    _settle(g, keys=_keys(LEFT=True))
    assert game.PLAYER_SPRITE_KEYS[g._player_sprite_index] == "hard_left"
    pygame.quit()


def test_player_sprite_switches_to_hard_right_holding_keyboard_right():
    g = _make_game()
    _settle(g, keys=_keys(RIGHT=True))
    assert game.PLAYER_SPRITE_KEYS[g._player_sprite_index] == "hard_right"
    pygame.quit()


def test_player_sprite_returns_to_straight_when_input_released():
    g = _make_game()
    _settle(g, keys=_keys(LEFT=True))
    assert game.PLAYER_SPRITE_KEYS[g._player_sprite_index] == "hard_left"
    _settle(g, keys=_keys())  # release
    assert game.PLAYER_SPRITE_KEYS[g._player_sprite_index] == "straight"
    pygame.quit()


def test_player_sprite_switches_to_hard_left_via_dpad():
    g = _make_game()
    gamepad = FakeController(buttons={pygame.CONTROLLER_BUTTON_DPAD_LEFT})
    _settle(g, gamepad=gamepad)
    assert game.PLAYER_SPRITE_KEYS[g._player_sprite_index] == "hard_left"
    pygame.quit()


def test_player_sprite_switches_to_hard_right_via_dpad():
    g = _make_game()
    gamepad = FakeController(buttons={pygame.CONTROLLER_BUTTON_DPAD_RIGHT})
    _settle(g, gamepad=gamepad)
    assert game.PLAYER_SPRITE_KEYS[g._player_sprite_index] == "hard_right"
    pygame.quit()


def test_player_sprite_mild_left_via_partial_analog_stick():
    # A partial deflection (not full-left) should settle in the "left"
    # category, not "hard_left" -- this is the case only the analog
    # stick (not keyboard/D-pad, both purely digital +-1) can reach.
    g = _make_game()
    gamepad = FakeController(axes={pygame.CONTROLLER_AXIS_LEFTX: -13000})  # ~ -0.40
    _settle(g, gamepad=gamepad)
    assert game.PLAYER_SPRITE_KEYS[g._player_sprite_index] == "left"
    pygame.quit()


def test_player_sprite_mild_right_via_partial_analog_stick():
    g = _make_game()
    gamepad = FakeController(axes={pygame.CONTROLLER_AXIS_LEFTX: 13000})  # ~ +0.40
    _settle(g, gamepad=gamepad)
    assert game.PLAYER_SPRITE_KEYS[g._player_sprite_index] == "right"
    pygame.quit()


def test_player_sprite_hard_left_via_full_analog_stick_deflection():
    g = _make_game()
    gamepad = FakeController(axes={pygame.CONTROLLER_AXIS_LEFTX: -32768})
    _settle(g, gamepad=gamepad)
    assert game.PLAYER_SPRITE_KEYS[g._player_sprite_index] == "hard_left"
    pygame.quit()


def test_player_sprite_straight_within_deadzone():
    g = _make_game()
    gamepad = FakeController(axes={pygame.CONTROLLER_AXIS_LEFTX: 2000})  # well under the deadzone
    _settle(g, gamepad=gamepad)
    assert game.PLAYER_SPRITE_KEYS[g._player_sprite_index] == "straight"
    pygame.quit()


def test_player_sprite_index_does_not_flicker_at_a_boundary():
    # A value oscillating right at the hard_left/left boundary (-0.55)
    # must not flip the sprite back and forth every call -- the
    # hysteresis margin (PLAYER_SPRITE_HYSTERESIS) requires clearing the
    # boundary by more than a hair to actually switch.
    g = _make_game()
    g._player_sprite_index = game.PLAYER_SPRITE_KEYS.index("left")
    seen = set()
    for _ in range(20):
        g._update_player_sprite_index(-0.551)  # just past the nominal boundary
        seen.add(g._player_sprite_index)
        g._update_player_sprite_index(-0.549)  # just short of it again
        seen.add(g._player_sprite_index)
    # Without hysteresis this would toggle between "left" and "hard_left"
    # on every call; with it, it should stay put.
    assert len(seen) == 1
    pygame.quit()


def test_player_sprite_index_handles_a_large_single_frame_jump():
    # Not the normal case (the smoothed value changes gradually), but the
    # category-resolution logic must still land on the *correct* category
    # rather than only moving one step, if it's ever called with a big jump.
    g = _make_game()
    g._player_sprite_index = game.PLAYER_SPRITE_KEYS.index("hard_left")
    g._update_player_sprite_index(0.9)
    assert game.PLAYER_SPRITE_KEYS[g._player_sprite_index] == "hard_right"
    pygame.quit()


def test_player_sprite_selection_does_not_change_player_x_or_collision():
    # Sprite selection must be read-only with respect to physics --
    # steering (and therefore player.x / collision) must come out
    # identical whether or not sprite assets are available.
    def run_with(sprites_available):
        g = _make_game()
        if not sprites_available:
            g._player_sprites = {}
        keys = _keys(UP=True, RIGHT=True)
        for _ in range(180):
            g.update(1 / 60, keys)
        return g.player.x, g.player.z, g.player.speed, g.collision_cooldown

    with_sprites = run_with(True)
    without_sprites = run_with(False)
    assert with_sprites == without_sprites
    pygame.quit()


@pytest.mark.skipif(not PLAYER_SPRITE_ASSETS_PRESENT, reason="player sprite PNGs not present")
def test_all_five_player_sprites_share_the_same_canvas_size():
    # _load_player_sprites() needs an active display surface for
    # .convert_alpha() -- _make_game() sets one up (a call with none
    # active degrades to the "missing assets" fallback rather than
    # raising, per this module's usual philosophy, which is exactly
    # what silently broke this test before it called _make_game() first).
    g = _make_game()
    sprites = g._player_sprites
    assert set(sprites.keys()) == set(game.PLAYER_SPRITE_KEYS)
    sizes = {surf.get_size() for surf in sprites.values()}
    assert sizes == {game.PLAYER_SPRITE_CANVAS_SIZE}
    pygame.quit()


@pytest.mark.skipif(not PLAYER_SPRITE_ASSETS_PRESENT, reason="player sprite PNGs not present")
def test_player_sprites_load_successfully_and_draw_without_crashing():
    g = _make_game()
    assert g._player_sprites  # non-empty -- assets loaded, not the fallback
    g._draw()  # must not crash
    pygame.quit()


def test_missing_player_sprite_files_falls_back_to_the_placeholder_rect(monkeypatch, tmp_path):
    monkeypatch.setattr(game, "PLAYER_ASSETS_DIR", tmp_path)  # empty dir, no PNGs there
    g = _make_game()
    assert g._player_sprites == {}
    g._draw()  # must not crash -- falls back to draw_car()
    pygame.quit()


def test_player_sprite_cache_is_shared_across_game_instances():
    g1 = _make_game()
    assert game._player_sprites_cache["loaded"] is True
    g2 = game.Game(default_config(), screen=g1.screen, renderer=g1.renderer)
    assert g2._player_sprites is g1._player_sprites  # same dict object, not re-loaded
    pygame.quit()


def test_draw_does_not_mutate_player_sprite_selection():
    # renderer.draw_world calls _draw_player_car once per eye -- both
    # calls must use the same sprite (StereoRenderer only applies
    # horizontal disparity, see its own docstring), so drawing must never
    # itself change which sprite is selected.
    g = _make_game()
    _settle(g, keys=_keys(LEFT=True))
    index_before = g._player_sprite_index
    g._draw()  # draws both eyes
    assert g._player_sprite_index == index_before
    pygame.quit()


def test_restart_resets_player_sprite_to_straight():
    g = _make_game()
    _settle(g, keys=_keys(RIGHT=True))
    assert game.PLAYER_SPRITE_KEYS[g._player_sprite_index] != "straight"
    g._restart()
    assert game.PLAYER_SPRITE_KEYS[g._player_sprite_index] == "straight"
    assert g.player_visual_steer == 0.0
    pygame.quit()


def test_trigger_reset_resets_player_sprite_to_straight():
    g = _make_game()
    _settle(g, keys=_keys(LEFT=True))
    g._trigger_reset()
    assert game.PLAYER_SPRITE_KEYS[g._player_sprite_index] == "straight"
    pygame.quit()


def test_player_car_still_bobs_with_road_elevation_using_sprites():
    # Regression check for "坂道で既に実装されているプレイヤー車の上下動にも
    # 追従させてください" -- _draw_player_car's cy must still include
    # player_bob after switching to sprite drawing.
    g = _make_game()
    g.player.speed = game.MAX_SPEED
    for idx in range(HILL_START - 10, HILL_START + 100, 10):
        g.player.z = idx * SEGMENT_LENGTH
        g.update(1 / 60, _keys())
        g._draw()  # must not crash at any point along the hill
    assert g.player_bob != 0.0  # sanity: the hill actually produced some bob
    pygame.quit()


def test_debug_overlay_shows_steering_value_and_sprite_name():
    g = _make_game()
    _settle(g, keys=_keys(RIGHT=True))
    g.show_debug = True
    g._draw()  # must not crash while the overlay is showing
    pygame.quit()


# -- Enemy/traffic car sprites (2026-09-05) ----------------------------------

# Captured from _build_traffic() before sprite_id existed (random.Random(42),
# same start/end/step/lane_centers) -- this is the "before" half of the
# "same seed -> identical lane/position/speed" regression the sprite_id
# change must never break, since sprite_id assignment now runs from its own
# separate Random(ENEMY_SPRITE_RNG_SEED) *after* this exact sequence.
_TRAFFIC_LAYOUT_BEFORE_SPRITES = [
    (360.0, 0.666667, 28.0), (630.0, -0.666667, 28.0), (900.0, -0.666667, 28.0),
    (1170.0, 0.666667, 28.0), (1440.0, 0.0, 28.0), (1710.0, -0.666667, 28.0),
    (1980.0, -0.666667, 28.0), (2250.0, -0.666667, 28.0), (2520.0, 0.666667, 28.0),
    (2790.0, -0.666667, 28.0), (3060.0, 0.666667, 28.0), (3330.0, 0.666667, 28.0),
    (3600.0, 0.666667, 28.0), (3870.0, -0.666667, 28.0), (4140.0, 0.666667, 28.0),
    (4410.0, 0.0, 28.0), (4680.0, -0.666667, 28.0), (4950.0, -0.666667, 28.0),
    (5220.0, -0.666667, 28.0), (5490.0, -0.666667, 28.0), (5760.0, -0.666667, 28.0),
    (6030.0, 0.666667, 28.0),
]


def test_traffic_lane_position_and_speed_are_unchanged_by_sprite_id_assignment():
    g = _make_game()
    actual = [(round(c.z, 4), round(c.x, 6), round(c.speed, 4)) for c in g.traffic]
    assert actual == _TRAFFIC_LAYOUT_BEFORE_SPRITES
    pygame.quit()


def test_enemy_sprite_rng_is_independent_of_the_lane_rng():
    # Direct proof, not just an outcome match: draining extra values from
    # random.Random(42) right after building traffic (as _build_traffic's
    # own lane rng would if sprite_id shared it) must NOT match what the
    # real, separate ENEMY_SPRITE_RNG_SEED stream produces -- i.e. these
    # really are two unrelated streams, not one that happens to agree here.
    g = _make_game()
    actual_ids = [c.sprite_id for c in g.traffic]

    lane_centers = [
        (2 * i - (game.LANE_COUNT - 1)) / game.LANE_COUNT for i in range(game.LANE_COUNT)
    ]
    lane_rng = random.Random(42)
    for _ in g.traffic:
        lane_rng.choice(lane_centers)  # replays exactly what _build_traffic already consumed
    if_shared_ids = [
        lane_rng.choices(game.ENEMY_SPRITE_KEYS, weights=game.ENEMY_SPRITE_WEIGHTS)[0]
        for _ in g.traffic
    ]
    assert actual_ids != if_shared_ids

    sprite_rng = random.Random(game.ENEMY_SPRITE_RNG_SEED)
    expected_ids = [
        sprite_rng.choices(game.ENEMY_SPRITE_KEYS, weights=game.ENEMY_SPRITE_WEIGHTS)[0]
        for _ in g.traffic
    ]
    assert actual_ids == expected_ids
    pygame.quit()


def test_sprite_id_assigned_once_and_stable_across_frames():
    g = _make_game()
    ids_before = [c.sprite_id for c in g.traffic]
    assert all(sid in game.ENEMY_SPRITE_KEYS for sid in ids_before)
    for _ in range(30):
        g.update(1 / 60, _keys(UP=True))
    ids_after = [c.sprite_id for c in g.traffic]
    assert ids_after == ids_before
    pygame.quit()


def test_restart_keeps_the_same_sprite_id_sequence():
    # _build_traffic() reruns on Restart, but with the same two fixed
    # seeds every time -- so the resulting sprite_id sequence should be
    # identical race to race, matching the existing "deterministic traffic
    # layout" property (_build_traffic uses random.Random(42), not
    # unseeded random).
    g = _make_game()
    ids_before = [c.sprite_id for c in g.traffic]
    g._restart()
    ids_after = [c.sprite_id for c in g.traffic]
    assert ids_after == ids_before
    pygame.quit()


@pytest.mark.skipif(not ENEMY_SPRITE_ASSETS_PRESENT, reason="enemy sprite PNGs not present")
def test_all_six_enemy_sprites_are_rgba_with_real_transparency():
    g = _make_game()
    sprites = g._enemy_sprites
    assert set(sprites.keys()) == set(game.ENEMY_SPRITE_KEYS)
    for key, surf in sprites.items():
        assert surf.get_bitsize() == 32 and surf.get_flags() & pygame.SRCALPHA
        alpha = pygame.surfarray.pixels_alpha(surf)
        assert alpha.min() == 0, f"{key}: no fully-transparent pixels"
        assert alpha.max() == 255, f"{key}: no fully-opaque pixels"
    pygame.quit()


@pytest.mark.skipif(not ENEMY_SPRITE_ASSETS_PRESENT, reason="enemy sprite PNGs not present")
def test_enemy_sprites_share_one_canvas_size_and_ground_anchor():
    g = _make_game()
    sprites = g._enemy_sprites
    sizes = {surf.get_size() for surf in sprites.values()}
    assert sizes == {game.ENEMY_SPRITE_CANVAS_SIZE}  # one shared canvas, per the spec

    anchor_x, anchor_y = game.ENEMY_SPRITE_ANCHOR
    bottom_rows = {}
    for key, surf in sprites.items():
        alpha = pygame.surfarray.pixels_alpha(surf)
        opaque_rows = [y for y in range(surf.get_height()) if (alpha[:, y] > 0).any()]
        assert opaque_rows, f"{key}: sprite is fully transparent"
        bottom_rows[key] = opaque_rows[-1]
        assert opaque_rows[-1] < anchor_y  # tire pixels sit above the anchor row, never past it

    # All 6 vehicles' actual tire-contact row must land within a couple px
    # of each other despite differing footprints (van/pickup vs. sedans) --
    # that's what "接地アンカーが車種間で揃う" means in practice.
    assert max(bottom_rows.values()) - min(bottom_rows.values()) <= 3


@pytest.mark.skipif(not ENEMY_SPRITE_ASSETS_PRESENT, reason="enemy sprite PNGs not present")
def test_enemy_sprites_load_successfully_and_draw_without_crashing():
    g = _make_game()
    assert g._enemy_sprites  # non-empty -- assets loaded, not the fallback
    g.player.z = g.traffic[0].z - 50.0  # bring a car within DRAW_DISTANCE
    g._draw()  # must not crash
    pygame.quit()


def test_missing_enemy_sprite_files_falls_back_to_the_placeholder_rect(monkeypatch, tmp_path):
    monkeypatch.setattr(game, "ENEMY_ASSETS_DIR", tmp_path)  # empty dir, no PNGs there
    g = _make_game()
    assert g._enemy_sprites == {}
    g.player.z = g.traffic[0].z - 50.0  # bring a car within DRAW_DISTANCE
    g._draw()  # must not crash -- falls back to draw_car() for every traffic car
    pygame.quit()


def test_enemy_sprite_cache_is_shared_across_game_instances():
    g1 = _make_game()
    assert game._enemy_sprites_cache["loaded"] is True
    g2 = game.Game(default_config(), screen=g1.screen, renderer=g1.renderer)
    assert g2._enemy_sprites is g1._enemy_sprites  # same dict object, not re-loaded
    pygame.quit()


def test_draw_does_not_change_traffic_sprite_ids():
    # renderer.draw_world calls _draw_traffic_car's draw() once per eye --
    # both must render the same vehicle at the same size (StereoRenderer
    # only applies horizontal disparity), so drawing must never reassign
    # sprite_id.
    g = _make_game()
    g.player.z = g.traffic[0].z - 50.0  # bring a car within DRAW_DISTANCE
    ids_before = [c.sprite_id for c in g.traffic]
    g._draw()  # draws both eyes
    ids_after = [c.sprite_id for c in g.traffic]
    assert ids_after == ids_before
    pygame.quit()


@pytest.mark.skipif(not ENEMY_SPRITE_ASSETS_PRESENT, reason="enemy sprite PNGs not present")
def test_traffic_sprite_display_size_grows_monotonically_as_it_gets_closer():
    g = _make_game()
    car = g.traffic[0]
    sprite = g._enemy_sprites[car.sprite_id]
    cam_x = g._road_center_x()
    width, height = g.renderer.left_surface.get_size()
    prev_scaled_w = 0
    for z in range(int(car.z), int(g.player.z) - 1, -400):
        world_x = game.world_x_at(g.segments, z) + car.x * game.ROAD_WIDTH
        world_y = game.elevation_at(g.segments, z)
        sx, sy, sw, tz = game.project(
            world_x, world_y, z, cam_x, g.cam_elevation, g.player.z, width, height
        )
        scale = max(0.35, sw / (game.ROAD_WIDTH * 3.5))
        scaled_w = max(1, round(sprite.get_width() * scale))
        assert scaled_w >= prev_scaled_w
        prev_scaled_w = scaled_w
    pygame.quit()


def test_enemy_sprite_scaling_uses_nearest_neighbor_not_smoothscale(monkeypatch):
    # pygame.transform.smoothscale antialiases (blurs pixel-art edges);
    # scale() doesn't -- the spec explicitly requires the latter.
    calls = {"smoothscale": 0, "scale": 0}
    real_scale = pygame.transform.scale

    def counting_scale(surf, size):
        calls["scale"] += 1
        return real_scale(surf, size)

    def failing_smoothscale(surf, size):
        calls["smoothscale"] += 1
        raise AssertionError("pygame.transform.smoothscale must not be used for enemy sprites")

    monkeypatch.setattr(pygame.transform, "scale", counting_scale)
    monkeypatch.setattr(pygame.transform, "smoothscale", failing_smoothscale)

    g = _make_game()
    # Bring the nearest traffic car within DRAW_DISTANCE so it's actually
    # drawn -- at the default player.z=0 it's still off in the distance
    # and _draw_traffic_car returns before ever touching pygame.transform.
    g.player.z = g.traffic[0].z - 50.0
    if g._enemy_sprites:
        g._draw()
        assert calls["scale"] > 0
    assert calls["smoothscale"] == 0
    pygame.quit()
