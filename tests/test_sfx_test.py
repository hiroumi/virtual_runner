"""Tests for the SFX audition tool (sfx_test.py): WAV export and the
interactive comparison screen, for both the engine and tire screech
presets. Actual audio quality can't be judged here (headless SDL dummy
driver) -- these only verify generation, playback wiring, preset/speed
switching, and that nothing crashes."""
import os
import sys
import wave as wave_module
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pygame
import pytest

import sfx_test
from sfx import ENGINE_PRESET_ORDER, SPEED_LEVELS, TIRE_SCREECH_PRESET_ORDER


def test_export_debug_wavs_writes_one_file_per_engine_preset_and_speed_level_plus_tire_presets(tmp_path):
    written = sfx_test.export_debug_wavs(tmp_path, sample_rate=22050)
    expected = len(ENGINE_PRESET_ORDER) * len(SPEED_LEVELS) + len(TIRE_SCREECH_PRESET_ORDER)
    assert len(written) == expected
    for path in written:
        assert path.exists()
        assert path.parent == tmp_path


def test_export_debug_wavs_filenames_match_preset_and_speed(tmp_path):
    written = sfx_test.export_debug_wavs(tmp_path, sample_rate=22050)
    names = {p.name for p in written}
    assert "debug_engine_arcade_engine_idle.wav" in names
    assert "debug_engine_low_rumble_high.wav" in names
    assert "debug_engine_chip_engine_medium.wav" in names
    assert "debug_tire_classic_squeal.wav" in names
    assert "debug_tire_grip_slide.wav" in names
    assert "debug_tire_arcade_chirp.wav" in names


def test_exported_wav_is_valid_and_has_expected_duration(tmp_path):
    sample_rate = 22050
    written = sfx_test.export_debug_wavs(tmp_path, sample_rate=sample_rate)
    with wave_module.open(str(written[0]), "rb") as f:
        assert f.getframerate() == sample_rate
        assert f.getsampwidth() == 2
        assert f.getnchannels() == 1
        n_frames = f.getnframes()
        duration = n_frames / sample_rate
        assert abs(duration - sfx_test.DEBUG_WAV_DURATION_S) < 0.05


def test_export_creates_the_output_directory_if_missing(tmp_path):
    target = tmp_path / "nested" / "debug_wav"
    assert not target.exists()
    sfx_test.export_debug_wavs(target, sample_rate=22050)
    assert target.is_dir()


def test_sfx_test_screen_runs_headless_for_a_few_frames():
    pygame.init()
    sfx_test.SfxTestScreen().run(test_frames=5)
    pygame.quit()


def test_sfx_test_screen_switches_preset_and_speed(monkeypatch):
    pygame.init()
    screen = sfx_test.SfxTestScreen()
    events = iter([
        [pygame.event.Event(pygame.KEYDOWN, key=pygame.K_b, mod=0)],
        [pygame.event.Event(pygame.KEYDOWN, key=pygame.K_3, mod=0)],
    ])
    monkeypatch.setattr(pygame.event, "get", lambda: next(events, []))
    screen.run(test_frames=2)
    assert screen.engine.preset_name == "ARCADE ENGINE"
    assert screen.speed_name == "medium"
    pygame.quit()


def test_sfx_test_screen_switches_tire_screech_preset(monkeypatch):
    pygame.init()
    screen = sfx_test.SfxTestScreen()
    monkeypatch.setattr(
        pygame.event, "get",
        lambda: [pygame.event.Event(pygame.KEYDOWN, key=pygame.K_y, mod=0)],
    )
    screen.run(test_frames=1)
    assert screen.tire.preset_name == "GRIP SLIDE"
    pygame.quit()


def test_sfx_test_screen_space_plays_the_tire_screech_now(monkeypatch):
    pygame.init()
    screen = sfx_test.SfxTestScreen()
    monkeypatch.setattr(
        pygame.event, "get",
        lambda: [pygame.event.Event(pygame.KEYDOWN, key=pygame.K_SPACE, mod=0)],
    )
    screen.run(test_frames=1)
    assert pygame.mixer.Channel(sfx_test.sfx.TireScreech.CHANNEL).get_busy() is True
    pygame.quit()


def test_sfx_test_screen_escape_key_quits(monkeypatch):
    pygame.init()
    screen = sfx_test.SfxTestScreen()
    monkeypatch.setattr(
        pygame.event, "get",
        lambda: [pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE, mod=0)],
    )
    screen.run(test_frames=None)  # must return, not hang, once Esc is seen
    pygame.quit()


def test_run_function_launches_and_exits_cleanly():
    sfx_test.run(test_frames=3)  # covers pygame.init()/mixer pre_init/quit wiring
