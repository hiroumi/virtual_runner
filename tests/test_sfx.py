"""Tests for the synthesized engine/tire-screech sound effects (sfx.py)."""
import os
import sys
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pygame
import pytest

import sfx
from sfx import (
    ENGINE_BUCKET_COUNT,
    ENGINE_DEFAULT_PRESET,
    ENGINE_PRESET_ORDER,
    ENGINE_PRESETS,
    TIRE_SCREECH_THRESHOLD,
    EngineSound,
    TireScreech,
    _engine_noise,
    _engine_wave,
    _harmonic_series_wave,
    _tire_screech_wave,
)


def _init():
    pygame.init()


def _run_to_target(engine: EngineSound, target_speed_frac: float, seconds: float = 2.0, dt: float = 1 / 60) -> None:
    """Steps update() enough frames for engine_rpm's smoothed chase to
    (nearly) reach target_speed_frac -- RPM no longer snaps instantly to
    speed, so tests that need a settled state must simulate time passing."""
    frames = max(1, int(seconds / dt))
    for _ in range(frames):
        engine.update(target_speed_frac, active=True, dt=dt)


def test_engine_presets_are_defined_and_consistent():
    assert set(ENGINE_PRESET_ORDER) == set(ENGINE_PRESETS.keys())
    assert len(ENGINE_PRESET_ORDER) == 3
    assert ENGINE_DEFAULT_PRESET in ENGINE_PRESETS
    for preset in ENGINE_PRESETS.values():
        assert preset.min_freq > 0
        assert preset.max_freq > preset.min_freq
        assert 0.0 <= preset.growl_weight_idle <= 1.0
        assert 0.0 <= preset.growl_weight_max <= 1.0


def test_harmonic_series_wave_stays_in_range_for_every_waveform():
    _init()
    t = np.arange(4410) / 44100.0
    for waveform in ("triangle", "sawtooth", "square"):
        wave = _harmonic_series_wave(waveform, 110.0, t, harmonics=6)
        assert wave.max() <= 1.0 + 1e-9
        assert wave.min() >= -1.0 - 1e-9
        assert wave.max() > 0.1  # not silent


def test_harmonic_series_wave_rejects_an_unknown_waveform():
    t = np.arange(100) / 44100.0
    with pytest.raises(ValueError):
        _harmonic_series_wave("sine", 110.0, t, harmonics=3)


def test_engine_noise_is_normalized_and_nonzero():
    _init()
    rng = np.random.default_rng(1)
    noise = _engine_noise(4410, rng)
    assert noise.max() <= 1.0 + 1e-9
    assert noise.min() >= -1.0 - 1e-9
    assert noise.max() > 0.1


def test_engine_wave_loops_on_an_exact_whole_number_of_cycles():
    # A fractional number of cycles in the buffer would leave an audible
    # seam/click every time the loop wraps -- _engine_wave snaps its
    # actual frequency so the buffer holds a whole number of periods.
    _init()
    sample_rate = 44100
    preset = ENGINE_PRESETS[ENGINE_DEFAULT_PRESET]
    wave, freq = _engine_wave(123.4, sample_rate, rpm_frac=0.5, preset=preset)
    n = len(wave)
    cycles = freq * n / sample_rate
    assert abs(cycles - round(cycles)) < 1e-6
    assert freq > 0


@pytest.mark.parametrize("preset_name", ENGINE_PRESET_ORDER)
@pytest.mark.parametrize("rpm_frac", [0.0, 0.5, 1.0])
def test_engine_wave_stays_within_the_normalized_range(preset_name, rpm_frac):
    _init()
    preset = ENGINE_PRESETS[preset_name]
    wave, _freq = _engine_wave(150.0, 44100, rpm_frac=rpm_frac, preset=preset)
    assert wave.max() <= 1.0
    assert wave.min() >= -1.0
    assert wave.max() > 0.05  # not silent, even at idle (rpm_frac=0)


def test_render_engine_preview_returns_the_requested_duration():
    _init()
    preset = ENGINE_PRESETS[ENGINE_DEFAULT_PRESET]
    sample_rate = 44100
    samples = sfx.render_engine_preview(preset, 0.5, sample_rate, duration_s=1.5)
    assert len(samples) == int(1.5 * sample_rate)
    assert samples.max() <= 1.0
    assert samples.min() >= -1.0


def test_tire_screech_wave_is_normalized_and_nonzero():
    _init()
    rng = np.random.default_rng(1)
    wave = _tire_screech_wave(44100, rng)
    assert wave.max() <= 1.0
    assert wave.min() >= -1.0
    assert wave.max() > 0.1  # not silent


def test_engine_sound_is_available_when_mixer_is_initialized():
    _init()
    e = EngineSound()
    assert e.available is True
    assert set(e._sounds_by_preset.keys()) == set(ENGINE_PRESET_ORDER)
    for name in ENGINE_PRESET_ORDER:
        assert len(e._sounds_by_preset[name]) == ENGINE_BUCKET_COUNT
    pygame.quit()


def test_engine_sound_defaults_to_the_default_preset():
    _init()
    e = EngineSound()
    assert e.preset_name == ENGINE_DEFAULT_PRESET
    pygame.quit()


def test_engine_bucket_increases_monotonically_with_speed():
    _init()
    e = EngineSound()
    prev = -1
    for speed_frac in (0.0, 0.1, 0.25, 0.4, 0.6, 0.8, 1.0):
        _run_to_target(e, speed_frac, seconds=2.0)
        assert e._bucket >= prev
        prev = e._bucket
    assert prev == ENGINE_BUCKET_COUNT - 1  # reached the top bucket at speed_frac=1.0
    pygame.quit()


def test_engine_rpm_does_not_snap_instantly_to_a_new_target():
    # Regression test for the RPM-smoothing redesign: a single frame's
    # update() must not jump engine_rpm straight to the target -- that
    # was the old (direct speed->pitch) behavior this replaced.
    _init()
    e = EngineSound()
    e.update(1.0, active=True, dt=1 / 60)
    assert 0.0 < e.engine_rpm < 0.3
    pygame.quit()


def test_engine_rpm_rises_faster_than_it_falls():
    _init()
    e = EngineSound()
    _run_to_target(e, 1.0, seconds=1.0)
    risen = e.engine_rpm
    assert risen > 0.5  # sanity: a full second of rise time got most of the way up

    _run_to_target(e, 0.0, seconds=1.0)
    fallen_amount = risen - e.engine_rpm

    # Reset and measure the same one second of *rise* from 0 for comparison.
    e2 = EngineSound()
    _run_to_target(e2, 1.0, seconds=1.0)
    risen_amount = e2.engine_rpm

    assert risen_amount > fallen_amount  # rises further in the same time than it falls
    pygame.quit()


def test_engine_sound_crossfades_between_alternating_channels():
    _init()
    e = EngineSound()
    e.update(0.0, active=True, dt=1 / 60)
    first_channel = e._active_channel
    _run_to_target(e, 1.0, seconds=2.0)  # long enough to guarantee a new bucket
    assert e._active_channel != first_channel
    pygame.quit()


def test_engine_sound_stop_marks_not_started_and_resets_rpm():
    _init()
    e = EngineSound()
    _run_to_target(e, 0.8, seconds=1.0)
    assert e._started is True
    assert e.engine_rpm > 0.0
    e.stop()
    assert e._started is False
    assert e.engine_rpm == 0.0
    e.stop()  # calling again on an already-stopped player must not raise
    pygame.quit()


def test_engine_sound_update_with_active_false_stops_it():
    _init()
    e = EngineSound()
    e.update(0.5, active=True, dt=1 / 60)
    assert e._started is True
    e.update(0.0, active=False, dt=1 / 60)
    assert e._started is False
    pygame.quit()


def test_set_preset_switches_the_active_preset():
    _init()
    e = EngineSound()
    other = next(name for name in ENGINE_PRESET_ORDER if name != e.preset_name)
    e.set_preset(other)
    assert e.preset_name == other
    pygame.quit()


def test_set_preset_retriggers_playback_on_the_new_preset(monkeypatch):
    _init()
    e = EngineSound()
    e.update(0.5, active=True, dt=1 / 60)
    assert e._started is True
    channel_before = e._active_channel

    other = next(name for name in ENGINE_PRESET_ORDER if name != e.preset_name)
    e.set_preset(other)
    assert e._bucket == -1  # forced re-trigger on the next update()

    e.update(0.5, active=True, dt=1 / 60)
    assert e._active_channel != channel_before  # crossfaded to the new preset's sound
    pygame.quit()


def test_set_preset_ignores_an_unknown_name():
    _init()
    e = EngineSound()
    before = e.preset_name
    e.set_preset("NOT A REAL PRESET")
    assert e.preset_name == before
    pygame.quit()


def test_set_preset_to_the_current_preset_is_a_noop():
    _init()
    e = EngineSound()
    e.update(0.5, active=True, dt=1 / 60)
    bucket_before = e._bucket
    e.set_preset(e.preset_name)
    assert e._bucket == bucket_before  # no forced re-trigger
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
    assert "not initialized" in e.unavailable_reason
    e.update(0.5, active=True, dt=1 / 60)  # must not raise
    e.stop()
    pygame.quit()


def test_tire_screech_degrades_silently_when_mixer_unavailable(monkeypatch):
    _init()
    monkeypatch.setattr(pygame.mixer, "get_init", lambda: None)
    t = TireScreech()
    assert t.available is False
    assert "not initialized" in t.unavailable_reason
    t.update(1.0, active=True)  # must not raise
    t.stop()
    pygame.quit()


def test_engine_sound_degrades_silently_when_numpy_is_unavailable(monkeypatch):
    _init()
    monkeypatch.setattr(sfx, "np", None)
    e = EngineSound()
    assert e.available is False
    assert e.unavailable_reason == "numpy not installed"
    e.update(0.5, active=True, dt=1 / 60)
    pygame.quit()


def test_tire_screech_degrades_silently_when_numpy_is_unavailable(monkeypatch):
    _init()
    monkeypatch.setattr(sfx, "np", None)
    t = TireScreech()
    assert t.available is False
    assert t.unavailable_reason == "numpy not installed"
    t.update(1.0, active=True)
    pygame.quit()


# -- unavailable_reason diagnostics (2026-09-04: real-hardware report of
# the engine SFX simply never triggering, with no way to tell whether
# that was a mixer/numpy problem or a loudness/perception one) ----------


def test_mixer_format_reports_a_reason_when_the_mixer_is_uninitialized(monkeypatch):
    monkeypatch.setattr(pygame.mixer, "get_init", lambda: None)
    fmt, reason = sfx._mixer_format()
    assert fmt is None
    assert "not initialized" in reason


def test_mixer_format_reports_a_reason_for_an_unsupported_channel_count(monkeypatch):
    _init()
    monkeypatch.setattr(pygame.mixer, "get_init", lambda: (44100, -16, 6))
    fmt, reason = sfx._mixer_format()
    assert fmt is None
    assert "channel count" in reason
    pygame.quit()


def test_mixer_format_returns_no_reason_when_usable():
    _init()
    fmt, reason = sfx._mixer_format()
    assert fmt is not None
    assert reason is None
    pygame.quit()


def test_engine_sound_reports_unsupported_channel_count(monkeypatch):
    _init()
    monkeypatch.setattr(pygame.mixer, "get_init", lambda: (44100, -16, 6))
    e = EngineSound()
    assert e.available is False
    assert "channel count" in e.unavailable_reason
    pygame.quit()


def test_available_engine_and_tire_screech_have_no_unavailable_reason():
    _init()
    e = EngineSound()
    t = TireScreech()
    assert e.available is True
    assert e.unavailable_reason is None
    assert t.available is True
    assert t.unavailable_reason is None
    pygame.quit()
