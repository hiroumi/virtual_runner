"""Synthesized sound effects: engine drone (pitch follows speed) and tire
screech (triggered by hard cornering). No audio files -- every waveform is
generated once at startup with numpy and handed to pygame.mixer via
pygame.sndarray, matching this project's "everything is generated, no
external art/assets required for gameplay" approach (see README's "no
original Nintendo art" note; BGM is the one deliberate exception, since
it's user-supplied original music, not a placeholder).

Degrades silently and completely if numpy or pygame.mixer aren't usable
(no audio device, mixer failed to init, etc.) -- every public method
becomes a no-op rather than raising, exactly like music.py's tolerance
for a missing BGM file. Sound effects are optional polish; they must
never be able to crash the race.
"""
from __future__ import annotations

import math

import pygame

try:
    import numpy as np
except ImportError:  # pragma: no cover -- exercised only if numpy truly missing
    np = None

SAMPLE_DTYPE = "int16"

# -- Engine ------------------------------------------------------------------
# Pitch is quantized into buckets (pygame can't retune a looping Sound in
# real time), each a pre-rendered loop crossfaded in as speed_frac crosses
# into its range -- enough buckets that the steps read as continuous
# pitch travel rather than audible jumps.
ENGINE_BUCKET_COUNT = 16
ENGINE_MIN_FREQ = 70.0          # Hz, idle
ENGINE_MAX_FREQ = 240.0         # Hz, redline
ENGINE_LOOP_SECONDS = 0.22      # each bucket's pre-rendered loop length
ENGINE_CROSSFADE_MS = 90        # fade between old/new bucket on a pitch change
# 2026-09-04: real-hardware feedback was "barely audible." Measured why --
# a handful of pure sine harmonics summed and normalized has RMS ~0.37 of
# full digital scale (a plain sine alone would be ~0.71), nowhere near the
# loudness of a mastered BGM track, so even before the (also too low)
# ENGINE_VOLUME multiplier, the source signal itself was quiet. Fixed with
# both a volume increase (0.32 -> 0.8) and _soft_clip: tanh-based
# saturation pushes RMS up toward the 1.0 peak by driving mid-amplitude
# samples closer to the clip ceiling (a standard "make it sound louder
# without just raising the peak" trick) without hard-clipping/crackling.
#
# 2026-09-04 (second pass): after confirming Reset works on real hardware,
# the user reported the SFX were *still* barely noticeable even with the
# above fix, so both knobs were pushed further (ENGINE_VOLUME to 1.0,
# ENGINE_SATURATION_DRIVE to 5.0). That turned out to be chasing the wrong
# problem: real-hardware debugging (see the mixer pre_init / numpy fix and
# unavailable_reason elsewhere in this file's history) found the engine
# sound had actually not been *triggering at all* up to that point, on
# that machine -- so neither the first nor second volume pass had ever
# really been heard. Once the real bug was fixed and the sound finally
# played, the "make it louder" settings from these two blind passes turned
# out to be too much: "ちょっとうるさい" (a bit too loud/harsh). Rolled
# back to the first pass's numbers as a clean, previously-reasoned
# starting point now that the sound is confirmed to actually be audible --
# simulated RMS 0.525, peak 0.954 (see docs/PHASE2_RACE_LOG.md).
ENGINE_VOLUME = 0.8
ENGINE_SATURATION_DRIVE = 2.5    # higher = louder/grittier, see _soft_clip
ENGINE_HARMONICS = ((1, 1.0), (2, 0.5), (3, 0.3), (4, 0.15), (5, 0.08))
ENGINE_WOBBLE_HZ = 7.0          # slow tremolo for a rougher, less pure-tone feel
ENGINE_WOBBLE_DEPTH = 0.05

# -- Tire screech --------------------------------------------------------
# abs(current_curve) * speed_frac is already computed every frame in
# Game.update() as the centrifugal-drift proxy -- reused here as a stand-in
# for lateral tire force, since there's no real slip/grip model. Above the
# threshold: a short noise-screech clip plays, retriggering back-to-back
# for as long as the threshold holds (so a multi-second bend gets
# continuous screech, not one clip cut short); below it, fades out quickly.
TIRE_SCREECH_THRESHOLD = 0.15
TIRE_SCREECH_SECONDS = 0.35
TIRE_SCREECH_FADE_MS = 120
# 2026-09-04 (second pass, see ENGINE_VOLUME's comment): raised again to
# 1.0/2.4 after "still barely audible" feedback -- which, like the
# engine's second pass, turned out to be chasing a real trigger bug (the
# SFX weren't playing at all on that machine yet), not an actual loudness
# ceiling. Rolled back to the first pass's 0.8/1.6 once the real bug was
# fixed and the SFX turned out to be too loud/harsh at the maxed-out
# settings ("ちょっとうるさい"). Simulated RMS 0.319, peak 0.9.
TIRE_SCREECH_VOLUME = 0.8
TIRE_SCREECH_SATURATION_DRIVE = 1.6  # gentler than the engine's -- too much
                                      # saturation flattens the noise into
                                      # featureless static instead of a screech


def _mixer_format():
    """((sample_rate, channels), None) from the live mixer, or
    (None, reason) if unusable -- the reason string is surfaced as
    EngineSound/TireScreech.unavailable_reason (and game.py's `D`-key
    debug overlay) specifically so a real-hardware "SFX isn't audible"
    report can be told apart from "SFX never even started" without
    needing another guess-and-check round to find out which."""
    init = pygame.mixer.get_init()
    if not init:
        return None, "pygame.mixer not initialized (no audio device, or mixer init failed)"
    sample_rate, _size, channels = init
    if sample_rate <= 0:
        return None, f"invalid mixer sample rate ({sample_rate})"
    if channels not in (1, 2):
        return None, f"unsupported mixer channel count ({channels}, expected 1 or 2)"
    return (sample_rate, channels), None


def _soft_clip(x: "np.ndarray", drive: float) -> "np.ndarray":
    """tanh saturation, rescaled so a full-scale input (peak exactly 1.0)
    still peaks at exactly 1.0 after saturation -- raises RMS (perceived
    loudness) by pulling mid-amplitude samples up toward the ceiling,
    without pushing the peak past it or hard-clipping into crackle."""
    return np.tanh(x * drive) / math.tanh(drive)


def _to_sound(mono: "np.ndarray", channels: int) -> pygame.mixer.Sound:
    clipped = np.clip(mono, -1.0, 1.0)
    ints = (clipped * 32767.0).astype(np.int16)
    arr = ints if channels == 1 else np.column_stack([ints, ints])
    return pygame.sndarray.make_sound(np.ascontiguousarray(arr))


def _engine_wave(target_freq: float, sample_rate: int) -> tuple["np.ndarray", float]:
    """Additive-synthesis engine drone, snapped to an exact whole number of
    cycles within its buffer so the loop has no seam/click -- returns the
    waveform and the actual (slightly snapped) frequency used."""
    n = max(1, int(round(ENGINE_LOOP_SECONDS * sample_rate)))
    cycles = max(1, int(round(target_freq * n / sample_rate)))
    freq = cycles * sample_rate / n
    t = np.arange(n) / sample_rate
    total_amp = sum(amp for _, amp in ENGINE_HARMONICS)
    wave = np.zeros(n)
    for harmonic, amp in ENGINE_HARMONICS:
        wave += amp * np.sin(2 * math.pi * freq * harmonic * t)
    wave /= total_amp
    wave = _soft_clip(wave, ENGINE_SATURATION_DRIVE)
    wobble = 1.0 + ENGINE_WOBBLE_DEPTH * np.sin(2 * math.pi * ENGINE_WOBBLE_HZ * t)
    wave *= wobble
    return wave * 0.95, freq


def _tire_screech_wave(sample_rate: int, rng: "np.random.Generator") -> "np.ndarray":
    """Noise-based screech: high-passed noise (first difference removes the
    low-frequency rumble that would otherwise read as engine/road noise,
    not tire squeal) mixed with a couple of vibrato'd resonant tones for
    an "eeee" character, shaped by a quick-attack/gentle-release envelope."""
    n = max(1, int(round(TIRE_SCREECH_SECONDS * sample_rate)))
    t = np.arange(n) / sample_rate

    noise = rng.uniform(-1.0, 1.0, n)
    noise = np.diff(noise, prepend=noise[0])

    vibrato_hz = 1900.0 + 220.0 * np.sin(2 * math.pi * 11.0 * t)
    phase = 2 * math.pi * np.cumsum(vibrato_hz) / sample_rate
    tone = np.sin(phase)
    tone2 = np.sin(phase * 1.5)

    mix = 0.5 * noise + 0.35 * tone + 0.25 * tone2

    attack = max(1, int(0.02 * sample_rate))
    release = max(1, int(0.08 * sample_rate))
    env = np.ones(n)
    env[:attack] = np.linspace(0.0, 1.0, attack)
    env[-release:] = np.linspace(1.0, 0.0, release)
    mix *= env

    peak = np.max(np.abs(mix))
    if peak > 1e-9:
        mix = mix / peak
    mix = _soft_clip(mix, TIRE_SCREECH_SATURATION_DRIVE)
    return mix * 0.9


class EngineSound:
    """Owns two alternating mixer channels so a pitch-bucket change can
    crossfade instead of hard-cutting -- see ENGINE_CROSSFADE_MS."""

    CHANNEL_A = 0
    CHANNEL_B = 1

    def __init__(self):
        self.available = False
        self.unavailable_reason: str | None = None
        self._sounds: list[pygame.mixer.Sound] = []
        self._bucket = -1
        self._active_channel = None  # which of CHANNEL_A/B is currently "live"
        self._started = False

        if np is None:
            self.unavailable_reason = "numpy not installed"
            return
        fmt, reason = _mixer_format()
        if fmt is None:
            self.unavailable_reason = reason
            return
        sample_rate, channels = fmt
        try:
            for i in range(ENGINE_BUCKET_COUNT):
                frac = i / max(1, ENGINE_BUCKET_COUNT - 1)
                target = ENGINE_MIN_FREQ + (ENGINE_MAX_FREQ - ENGINE_MIN_FREQ) * frac
                wave, _actual_freq = _engine_wave(target, sample_rate)
                sound = _to_sound(wave, channels)
                sound.set_volume(ENGINE_VOLUME)
                self._sounds.append(sound)
            self.available = True
        except (pygame.error, ValueError) as exc:
            self._sounds = []
            self.available = False
            self.unavailable_reason = f"sound creation failed: {exc.__class__.__name__}: {exc}"

    def _bucket_for(self, speed_frac: float) -> int:
        speed_frac = max(0.0, min(1.0, speed_frac))
        return min(ENGINE_BUCKET_COUNT - 1, int(speed_frac * ENGINE_BUCKET_COUNT))

    def update(self, speed_frac: float, active: bool) -> None:
        if not self.available:
            return
        if not active:
            self.stop()
            return

        bucket = self._bucket_for(speed_frac)
        if bucket == self._bucket and self._started:
            return  # still in the same pitch bucket, already playing -- nothing to do

        self._bucket = bucket
        sound = self._sounds[bucket]
        next_channel = self.CHANNEL_B if self._active_channel == self.CHANNEL_A else self.CHANNEL_A
        try:
            if not self._started:
                # First frame of the race (or just after a restart/stop):
                # play immediately, no need to crossfade against silence.
                pygame.mixer.Channel(next_channel).play(sound, loops=-1)
            else:
                pygame.mixer.Channel(self._active_channel).fadeout(ENGINE_CROSSFADE_MS)
                pygame.mixer.Channel(next_channel).play(sound, loops=-1, fade_ms=ENGINE_CROSSFADE_MS)
            self._active_channel = next_channel
            self._started = True
        except pygame.error:
            self.available = False

    def stop(self) -> None:
        if not self.available or not self._started:
            return
        try:
            for ch in (self.CHANNEL_A, self.CHANNEL_B):
                pygame.mixer.Channel(ch).fadeout(ENGINE_CROSSFADE_MS)
        except pygame.error:
            pass
        self._started = False
        self._bucket = -1
        self._active_channel = None


class TireScreech:
    CHANNEL = 2

    def __init__(self, seed: int = 7):
        self.available = False
        self.unavailable_reason: str | None = None
        self._sound = None

        if np is None:
            self.unavailable_reason = "numpy not installed"
            return
        fmt, reason = _mixer_format()
        if fmt is None:
            self.unavailable_reason = reason
            return
        sample_rate, channels = fmt
        try:
            rng = np.random.default_rng(seed)
            wave = _tire_screech_wave(sample_rate, rng)
            self._sound = _to_sound(wave, channels)
            self._sound.set_volume(TIRE_SCREECH_VOLUME)
            self.available = True
        except (pygame.error, ValueError) as exc:
            self._sound = None
            self.available = False
            self.unavailable_reason = f"sound creation failed: {exc.__class__.__name__}: {exc}"

    def update(self, lateral_proxy: float, active: bool) -> None:
        if not self.available:
            return
        channel = pygame.mixer.Channel(self.CHANNEL)
        try:
            if active and abs(lateral_proxy) > TIRE_SCREECH_THRESHOLD:
                if not channel.get_busy():
                    channel.play(self._sound)
            elif channel.get_busy():
                channel.fadeout(TIRE_SCREECH_FADE_MS)
        except pygame.error:
            self.available = False

    def stop(self) -> None:
        if not self.available:
            return
        try:
            pygame.mixer.Channel(self.CHANNEL).fadeout(TIRE_SCREECH_FADE_MS)
        except pygame.error:
            pass
