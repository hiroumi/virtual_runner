"""Synthesized sound effects: engine drone (RPM-driven, three switchable
presets) and tire screech (triggered by hard cornering). No audio files --
every waveform is generated once at startup with numpy and handed to
pygame.mixer via pygame.sndarray, matching this project's "everything is
generated, no external art/assets required for gameplay" approach (see
README's "no original Nintendo art" note; BGM is the one deliberate
exception, since it's user-supplied original music, not a placeholder).

Degrades silently and completely if numpy or pygame.mixer aren't usable
(no audio device, mixer failed to init, etc.) -- every public method
becomes a no-op rather than raising, exactly like music.py's tolerance
for a missing BGM file. Sound effects are optional polish; they must
never be able to crash the race.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import pygame

try:
    import numpy as np
except ImportError:  # pragma: no cover -- exercised only if numpy truly missing
    np = None

SAMPLE_DTYPE = "int16"

# -- Engine ------------------------------------------------------------------
# 2026-09-04 (fifth pass): once the mixer-trigger bug was fixed and the
# engine sound could finally be heard and judged properly (see git log /
# docs/PHASE2_RACE_LOG.md for the earlier passes), the feedback was that
# the *idle* tone read fine but the *driving* tone didn't read as a car
# engine at all. The previous design's root problem: speed_frac mapped
# straight to pitch (no RPM concept, no throttle lag) through a handful of
# pure sine harmonics (a smooth, organ-like timbre with no mechanical
# texture), with "louder/thicker" attempted purely via volume and tanh
# saturation rather than the waveform itself -- exactly the ingredients
# for "sounds like a buzzer/alarm," which is what got reported.
#
# Redesigned around three things the old version didn't have:
#   1. An internal RPM state (EngineSound.engine_rpm, 0..1) separate from
#      raw speed, smoothed with asymmetric rise/fall rates -- revs up
#      promptly on throttle, drifts back down more slowly on lift-off or
#      a collision, instead of snapping straight to whatever speed is.
#   2. A layered waveform per RPM bucket: a low, rounded "fundamental"
#      (triangle- or square-family, built from a *controlled* number of
#      harmonics -- see _harmonic_series_wave -- not a naive discontinuous
#      wave) that stays dominant even at redline, plus a brighter "growl"
#      layer at the *same* pitch (more harmonic content, not a second
#      note) whose mix share grows with RPM, plus a small constant noise
#      texture for mechanical grit. See EnginePreset / _engine_wave.
#   3. Three switchable presets (ENGINE_PRESETS) instead of one guessed
#      recipe -- tone is a real-hardware listening call this session can't
#      make, so game.py's `E` key cycles them live and sfx_test.py offers
#      an audition tool + WAV export for offline comparison.
ENGINE_BUCKET_COUNT = 16
ENGINE_LOOP_SECONDS = 0.22       # each bucket's pre-rendered loop length
ENGINE_CROSSFADE_MS = 90         # fade between old/new bucket on an RPM change
ENGINE_WOBBLE_HZ = 7.0           # slow tremolo for a rougher, less pure-tone feel
ENGINE_WOBBLE_DEPTH = 0.05

# RPM chases a speed-derived target rather than snapping to it -- rising
# quickly (throttle response should read as immediate: "アクセルを押すと
# 回転数が上がっていくことが明確に分かる") and falling more slowly (engine
# braking / coasting: "アクセルを離すと、少し遅れて回転数が下がる"). The
# same asymmetric chase also covers "衝突・急減速：回転数も遅れて下がる"
# for free, since a collision is just a sudden drop in the same target.
ENGINE_RPM_RISE_RATE = 3.5      # 1/s
ENGINE_RPM_FALL_RATE = 1.2      # 1/s

# The fundamental's mix share is never allowed below this, however large
# growl+noise get -- "最高速では高音だけにならず、低いエンジン成分も残る".
ENGINE_FUNDAMENTAL_FLOOR = 0.45


@dataclass(frozen=True)
class EnginePreset:
    """One synthesis recipe. fundamental_wave/growl_wave are keys into
    _harmonic_series_wave ('triangle' or 'square' for the fundamental;
    'sawtooth' or 'square' for the growl layer). growl_weight_idle/_max
    are that layer's share of the mix at RPM 0 and RPM 1 respectively,
    interpolated linearly by RPM in between. saturation_drive is kept
    gentle everywhere -- a peak-safety limiter, not the primary way this
    version makes the engine sound "thick" (that's the waveform layering
    itself, per the 2026-09-04 fifth-pass redesign above)."""

    name: str
    min_freq: float             # Hz at RPM 0 (idle)
    max_freq: float             # Hz at RPM 1 (redline)
    fundamental_wave: str
    fundamental_harmonics: int
    growl_wave: str
    growl_harmonics: int
    growl_weight_idle: float
    growl_weight_max: float
    noise_weight: float         # constant mechanical-grit mix share
    saturation_drive: float
    volume: float


ENGINE_PRESETS: dict[str, EnginePreset] = {
    "LOW RUMBLE": EnginePreset(
        name="LOW RUMBLE",
        min_freq=62.0, max_freq=125.0,
        fundamental_wave="triangle", fundamental_harmonics=7,
        growl_wave="sawtooth", growl_harmonics=6,
        growl_weight_idle=0.04, growl_weight_max=0.22,
        noise_weight=0.05,
        saturation_drive=1.15,
        volume=0.8,
    ),
    "ARCADE ENGINE": EnginePreset(
        name="ARCADE ENGINE",
        min_freq=68.0, max_freq=150.0,
        fundamental_wave="triangle", fundamental_harmonics=7,
        growl_wave="sawtooth", growl_harmonics=8,
        growl_weight_idle=0.06, growl_weight_max=0.40,
        noise_weight=0.07,
        saturation_drive=1.2,
        # 2026-09-04, sixth pass: confirmed as the closest-to-imagined
        # preset on real hardware ("最初が一番イメージにちかい" -- the
        # default, this one) and the buzzer-y quality was gone, but it
        # still read as louder than the BGM. Waveform/drive are untouched
        # (the tone itself was praised) -- only the output gain moved,
        # 0.8 -> 0.6 (simulated effective RMS ~0.47-0.49 -> ~0.35-0.37).
        # 2026-09-04, seventh pass: "still fine to be even smaller" --
        # dropped again, 0.6 -> 0.4 (effective RMS ~0.35-0.37 ->
        # ~0.24-0.25), clearly under BGM_VOLUME=0.65 (music.py) rather
        # than merely below it. See docs/PHASE2_RACE_LOG.md.
        volume=0.4,
    ),
    "CHIP ENGINE": EnginePreset(
        name="CHIP ENGINE",
        min_freq=70.0, max_freq=165.0,
        fundamental_wave="square", fundamental_harmonics=4,
        growl_wave="square", growl_harmonics=7,
        growl_weight_idle=0.08, growl_weight_max=0.38,
        noise_weight=0.05,
        saturation_drive=1.15,
        volume=0.75,
    ),
}
ENGINE_PRESET_ORDER = ["LOW RUMBLE", "ARCADE ENGINE", "CHIP ENGINE"]
ENGINE_DEFAULT_PRESET = "ARCADE ENGINE"

# Representative speed_frac values for the SFX TEST tool / debug WAV
# export (sfx_test.py) -- an ordinary dict so insertion order (idle, low,
# medium, high) is preserved for anything that iterates it.
SPEED_LEVELS: dict[str, float] = {
    "idle": 0.0,
    "low": 0.28,
    "medium": 0.58,
    "high": 0.95,
}

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
# 2026-09-04 (second pass, see the engine's history above): raised to
# 1.0/2.4 after "still barely audible" feedback -- which, like the
# engine's second pass, turned out to be chasing a real trigger bug (the
# SFX weren't playing at all on that machine yet), not an actual loudness
# ceiling. Rolled back to the first pass's 0.8/1.6 once the real bug was
# fixed and the SFX turned out to be too loud/harsh at the maxed-out
# settings ("ちょっとうるさい"). Simulated RMS 0.319, peak 0.9. Left
# untouched by the fifth-pass engine redesign -- only the engine's
# waveform/character was reported as wrong; tire screech is explicitly
# out of scope for that change.
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
    without pushing the peak past it or hard-clipping into crackle. Used
    as a gentle peak-safety net on the engine (low drive, see
    EnginePreset.saturation_drive) and as the tire screech's primary
    loudness tool (higher drive, see TIRE_SCREECH_SATURATION_DRIVE)."""
    return np.tanh(x * drive) / math.tanh(drive)


def _to_sound(mono: "np.ndarray", channels: int) -> pygame.mixer.Sound:
    clipped = np.clip(mono, -1.0, 1.0)
    ints = (clipped * 32767.0).astype(np.int16)
    arr = ints if channels == 1 else np.column_stack([ints, ints])
    return pygame.sndarray.make_sound(np.ascontiguousarray(arr))


def _harmonic_series_wave(waveform: str, freq: float, t: "np.ndarray", harmonics: int) -> "np.ndarray":
    """A band-limited (truncated Fourier series) approximation of a
    classic analog waveform, built from an exact, controlled number of
    sine harmonics -- not a naive discontinuous square/sawtooth, whose
    brightness would depend on however many harmonics fit under the
    sample rate rather than being a tunable knob. More `harmonics` reads
    as brighter/buzzier; fewer reads as rounder/simpler (used for the
    CHIP ENGINE preset's more "stepped" chiptune character).

    Normalized to unit peak before returning -- truncating a Fourier
    series causes Gibbs-phenomenon overshoot near the waveform's edges,
    so the raw sum doesn't peak at exactly 1.0 on its own."""
    wave = np.zeros_like(t)
    if waveform == "triangle":
        # Odd harmonics only, amplitude ~1/k^2 with alternating sign --
        # the classic triangle-wave series: rounded, warm, "thick"
        # without being buzzy.
        k = 1
        sign = 1.0
        for _ in range(max(1, harmonics)):
            wave += sign * (1.0 / (k * k)) * np.sin(2 * math.pi * freq * k * t)
            sign = -sign
            k += 2
    elif waveform == "sawtooth":
        # All harmonics, amplitude ~1/k -- brighter/richer, used as the
        # "growl" layer's extra harmonic energy at the same pitch.
        for k in range(1, max(1, harmonics) + 1):
            sign = 1.0 if k % 2 else -1.0
            wave += sign * (1.0 / k) * np.sin(2 * math.pi * freq * k * t)
    elif waveform == "square":
        # Odd harmonics, amplitude ~1/k -- hollow, "chip"-like character.
        k = 1
        for _ in range(max(1, harmonics)):
            wave += (1.0 / k) * np.sin(2 * math.pi * freq * k * t)
            k += 2
    else:
        raise ValueError(f"unknown waveform {waveform!r}")
    peak = np.max(np.abs(wave))
    if peak > 1e-9:
        wave = wave / peak
    return wave


def _engine_noise(n: int, rng: "np.random.Generator") -> "np.ndarray":
    """A small mechanical-grit texture -- distinct from the tire
    screech's sharp, high-passed noise (see _tire_screech_wave): plain
    broadband noise smoothed with a short moving average to roll off the
    harshest highs into more of a soft rumble/hiss, since this is meant
    to sit quietly *under* the tonal layers, not stand out on its own.
    Normalized to unit peak."""
    raw = rng.uniform(-1.0, 1.0, n)
    kernel = np.ones(5) / 5.0
    padded = np.pad(raw, (2, 2), mode="wrap")  # wrap, not zero-pad, so the
    smoothed = np.convolve(padded, kernel, mode="valid")  # loop has no seam
    peak = np.max(np.abs(smoothed))
    return smoothed / peak if peak > 1e-9 else smoothed


def _engine_wave(
    target_freq: float,
    sample_rate: int,
    rpm_frac: float,
    preset: EnginePreset,
    seed: int = 0,
) -> tuple["np.ndarray", float]:
    """One RPM bucket's loop for `preset`: a low fundamental (dominant,
    never below ENGINE_FUNDAMENTAL_FLOOR of the mix), a brighter growl
    layer at the *same* pitch (more harmonic content standing in for
    rising engine load, not a second note) whose mix share grows with
    rpm_frac, and a small constant noise texture. Snapped to an exact
    whole number of cycles so the loop has no seam/click."""
    n = max(1, int(round(ENGINE_LOOP_SECONDS * sample_rate)))
    cycles = max(1, int(round(target_freq * n / sample_rate)))
    freq = cycles * sample_rate / n
    t = np.arange(n) / sample_rate

    fundamental = _harmonic_series_wave(preset.fundamental_wave, freq, t, preset.fundamental_harmonics)
    growl = _harmonic_series_wave(preset.growl_wave, freq, t, preset.growl_harmonics)
    noise = _engine_noise(n, np.random.default_rng(seed))

    growl_amt = preset.growl_weight_idle + (preset.growl_weight_max - preset.growl_weight_idle) * rpm_frac
    noise_amt = preset.noise_weight
    fundamental_amt = max(ENGINE_FUNDAMENTAL_FLOOR, 1.0 - growl_amt - noise_amt)
    # The floor above can push the three weights' sum over 1 -- renormalize
    # so output level stays consistent across buckets/presets regardless
    # of how often the floor actually kicks in.
    total = fundamental_amt + growl_amt + noise_amt
    fundamental_amt, growl_amt, noise_amt = (w / total for w in (fundamental_amt, growl_amt, noise_amt))

    wave = fundamental_amt * fundamental + growl_amt * growl + noise_amt * noise
    wave = _soft_clip(wave, preset.saturation_drive)
    wobble = 1.0 + ENGINE_WOBBLE_DEPTH * np.sin(2 * math.pi * ENGINE_WOBBLE_HZ * t)
    wave *= wobble
    return wave * 0.95, freq


def render_engine_preview(
    preset: EnginePreset, speed_frac: float, sample_rate: int, duration_s: float = 1.6, seed: int = 0,
) -> "np.ndarray":
    """Renders `duration_s` seconds of `preset` at a fixed (not
    RPM-smoothed) speed_frac, for offline audition/export -- see
    sfx_test.py. Reuses _engine_wave's already loop-safe short buffer and
    tiles it, since that buffer is already snapped to a whole number of
    cycles and needs no re-deriving for a longer duration."""
    frac = max(0.0, min(1.0, speed_frac))
    target = preset.min_freq + (preset.max_freq - preset.min_freq) * frac
    wave, _freq = _engine_wave(target, sample_rate, frac, preset, seed=seed)
    total_samples = max(1, int(duration_s * sample_rate))
    repeats = max(1, -(-total_samples // len(wave)))  # ceil division
    tiled = np.tile(wave, repeats)
    return tiled[:total_samples]


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
    """Owns two alternating mixer channels so an RPM-bucket change can
    crossfade instead of hard-cutting -- see ENGINE_CROSSFADE_MS. All
    three presets (ENGINE_PRESETS) are pre-rendered up front so
    set_preset() can switch instantly with no synthesis stutter -- see
    game.py's `E` key and sfx_test.py's audition tool."""

    CHANNEL_A = 0
    CHANNEL_B = 1

    def __init__(self, preset: str = ENGINE_DEFAULT_PRESET):
        self.available = False
        self.unavailable_reason: str | None = None
        self._sounds_by_preset: dict[str, list[pygame.mixer.Sound]] = {}
        self.preset_name = preset
        self.engine_rpm = 0.0
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
            for name, p in ENGINE_PRESETS.items():
                sounds = []
                for i in range(ENGINE_BUCKET_COUNT):
                    frac = i / max(1, ENGINE_BUCKET_COUNT - 1)
                    target = p.min_freq + (p.max_freq - p.min_freq) * frac
                    wave, _actual_freq = _engine_wave(target, sample_rate, frac, p, seed=i)
                    sound = _to_sound(wave, channels)
                    sound.set_volume(p.volume)
                    sounds.append(sound)
                self._sounds_by_preset[name] = sounds
            self.available = True
        except (pygame.error, ValueError) as exc:
            self._sounds_by_preset = {}
            self.available = False
            self.unavailable_reason = f"sound creation failed: {exc.__class__.__name__}: {exc}"

    def set_preset(self, name: str) -> None:
        """Switches synthesis recipe. If the engine is currently playing,
        immediately re-triggers the current RPM bucket using the new
        preset's sound (crossfaded) rather than waiting for the RPM to
        cross into a different bucket on its own -- a preset switch should
        be heard right away, not eventually."""
        if name not in self._sounds_by_preset or name == self.preset_name:
            return
        self.preset_name = name
        if self._started:
            self._bucket = -1  # forces update()'s "bucket changed" branch next call

    def _bucket_for(self, rpm: float) -> int:
        rpm = max(0.0, min(1.0, rpm))
        return min(ENGINE_BUCKET_COUNT - 1, int(rpm * ENGINE_BUCKET_COUNT))

    def update(self, speed_frac: float, active: bool, dt: float) -> None:
        if not self.available:
            return
        if not active:
            self.stop()
            return

        target_rpm = max(0.0, min(1.0, speed_frac))
        rate = ENGINE_RPM_RISE_RATE if target_rpm > self.engine_rpm else ENGINE_RPM_FALL_RATE
        self.engine_rpm += (target_rpm - self.engine_rpm) * min(1.0, rate * dt)

        bucket = self._bucket_for(self.engine_rpm)
        if bucket == self._bucket and self._started:
            return  # still in the same RPM bucket, already playing -- nothing to do

        self._bucket = bucket
        sound = self._sounds_by_preset[self.preset_name][bucket]
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
        self.engine_rpm = 0.0


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
