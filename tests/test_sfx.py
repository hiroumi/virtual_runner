"""Tests for the synthesized engine/tire-screech sound effects (sfx.py)."""
import os
import sys
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pygame
import pytest

import sfx
from sfx import (
    ENGINE_BUCKET_COUNT,
    TIRE_SCREECH_THRESHOLD,
    EngineSound,
    TireScreech,
    _engine_wave,
    _tire_screech_wave,
)


def _init():
    pygame.init()


def test_engine_wave_loops_on_an_exact_whole_number_of_cycles():
    # A fractional number of cycles in the buffer would leave an audible
    # seam/click every time the loop wraps -- _engine_wave snaps its
    # actual frequency so the buffer holds a whole number of periods.
    _init()
    sample_rate = 44100
    wave, freq = _engine_wave(123.4, sample_rate)
    n = len(wave)
    cycles = freq * n / sample_rate
    assert abs(cycles - round(cycles)) < 1e-6
    assert freq > 0


def test_engine_wave_stays_within_the_normalized_range():
    _init()
    wave, _freq = _engine_wave(150.0, 44100)
    assert wave.max() <= 1.0
    assert wave.min() >= -1.0


def test_tire_screech_wave_is_normalized_and_nonzero():
    _init()
    import numpy as np

    rng = np.random.default_rng(1)
    wave = _tire_screech_wave(44100, rng)
    assert wave.max() <= 1.0
    assert wave.min() >= -1.0
    assert wave.max() > 0.1  # not silent


def test_engine_sound_is_available_when_mixer_is_initialized():
    _init()
    e = EngineSound()
    assert e.available is True
    assert len(e._sounds) == ENGINE_BUCKET_COUNT
    pygame.quit()


def test_engine_bucket_increases_monotonically_with_speed():
    _init()
    e = EngineSound()
    prev = -1
    for speed_frac in (0.0, 0.1, 0.25, 0.4, 0.6, 0.8, 1.0):
        e.update(speed_frac, active=True)
        assert e._bucket >= prev
        prev = e._bucket
    pygame.quit()


def test_engine_sound_crossfades_between_alternating_channels():
    _init()
    e = EngineSound()
    e.update(0.0, active=True)
    first_channel = e._active_channel
    e.update(1.0, active=True)  # big enough jump to guarantee a new bucket
    assert e._active_channel != first_channel
    pygame.quit()


def test_engine_sound_stop_marks_not_started_and_is_idempotent():
    _init()
    e = EngineSound()
    e.update(0.5, active=True)
    assert e._started is True
    e.stop()
    assert e._started is False
    e.stop()  # calling again on an already-stopped player must not raise
    pygame.quit()


def test_engine_sound_update_with_active_false_stops_it():
    _init()
    e = EngineSound()
    e.update(0.5, active=True)
    assert e._started is True
    e.update(0.0, active=False)
    assert e._started is False
    pygame.quit()


def test_tire_screech_is_available_when_mixer_is_initialized():
    _init()
    t = TireScreech()
    assert t.available is True
    pygame.quit()


def test_tire_screech_triggers_above_threshold_and_not_below():
    _init()
    t = TireScreech()
    channel = pygame.mixer.Channel(TireScreech.CHANNEL)

    t.update(TIRE_SCREECH_THRESHOLD - 0.05, active=True)
    assert channel.get_busy() is False

    t.update(TIRE_SCREECH_THRESHOLD + 0.1, active=True)
    assert channel.get_busy() is True
    pygame.quit()


def test_tire_screech_does_not_retrigger_while_already_playing():
    _init()
    t = TireScreech()
    channel = pygame.mixer.Channel(TireScreech.CHANNEL)
    t.update(0.5, active=True)
    playing_sound = channel.get_sound()
    t.update(0.5, active=True)
    # same underlying Sound object still playing -- play() wasn't called again
    assert channel.get_sound() is playing_sound
    pygame.quit()


def test_tire_screech_fades_out_when_dropping_below_threshold():
    # pygame.mixer.Channel is a C extension type -- individual methods
    # can't be monkeypatched on an instance, so this checks the real,
    # observable fade behavior instead: not an abrupt stop (still busy
    # right after crossing back under threshold), but silent once the
    # fade has had time to complete.
    _init()
    t = TireScreech()
    channel = pygame.mixer.Channel(TireScreech.CHANNEL)
    t.update(0.5, active=True)
    assert channel.get_busy() is True

    t.update(0.0, active=True)
    assert channel.get_busy() is True  # fading, not stopped outright
    pygame.time.wait(sfx.TIRE_SCREECH_FADE_MS + 150)
    assert channel.get_busy() is False
    pygame.quit()


def test_tire_screech_update_with_active_false_stops_it():
    _init()
    t = TireScreech()
    channel = pygame.mixer.Channel(TireScreech.CHANNEL)
    t.update(0.5, active=True)
    assert channel.get_busy() is True
    t.update(0.5, active=False)  # not active overrides even a high proxy value
    pygame.time.wait(sfx.TIRE_SCREECH_FADE_MS + 150)
    assert channel.get_busy() is False
    pygame.quit()


def test_engine_sound_degrades_silently_when_mixer_unavailable(monkeypatch):
    _init()
    monkeypatch.setattr(pygame.mixer, "get_init", lambda: None)
    e = EngineSound()
    assert e.available is False
    e.update(0.5, active=True)  # must not raise
    e.stop()
    pygame.quit()


def test_tire_screech_degrades_silently_when_mixer_unavailable(monkeypatch):
    _init()
    monkeypatch.setattr(pygame.mixer, "get_init", lambda: None)
    t = TireScreech()
    assert t.available is False
    t.update(1.0, active=True)  # must not raise
    t.stop()
    pygame.quit()


def test_engine_sound_degrades_silently_when_numpy_is_unavailable(monkeypatch):
    _init()
    monkeypatch.setattr(sfx, "np", None)
    e = EngineSound()
    assert e.available is False
    e.update(0.5, active=True)
    pygame.quit()


def test_tire_screech_degrades_silently_when_numpy_is_unavailable(monkeypatch):
    _init()
    monkeypatch.setattr(sfx, "np", None)
    t = TireScreech()
    assert t.available is False
    t.update(1.0, active=True)
    pygame.quit()
