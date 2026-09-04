"""SFX audition tool: compare the engine's three synthesis presets (see
sfx.ENGINE_PRESETS) at four representative speeds, and the tire screech's
three synthesis presets (see sfx.TIRE_SCREECH_PRESETS), since their tonal
character is a real-hardware listening call automated tests can't make.
Not part of the race itself.

Two ways to use it:

  python main.py --sfx-test
      Interactive screen: A/B/C picks an engine preset, 1-4 picks a speed
      level (EngineSound's real update()/RPM-smoothing path runs every
      frame, so switching speed level demonstrates the actual rev-up/
      rev-down behavior, not just a static tone). X/Y/Z picks a tire
      screech preset; Space plays it on demand.

  python sfx_test.py --export-wav <dir>
      Writes one short WAV per engine preset x speed-level combination
      (12 files, debug_engine_*.wav) plus one per tire screech preset
      (3 files, debug_tire_*.wav) to <dir> for offline listening --
      debug output only, never committed (see .gitignore's debug_wav/
      entry). Needs no display or live mixer; pure offline synthesis.
"""
from __future__ import annotations

import argparse
import wave as wave_module
from pathlib import Path

import pygame

import sfx
from sfx import (
    ENGINE_PRESET_ORDER,
    ENGINE_PRESETS,
    SPEED_LEVELS,
    TIRE_SCREECH_PRESET_ORDER,
    TIRE_SCREECH_PRESETS,
)

try:
    import numpy as np
except ImportError:  # pragma: no cover -- exercised only if numpy truly missing
    np = None

WINDOW_SIZE = (640, 320)
BG = (10, 0, 0)
TITLE_COLOR = (255, 120, 120)
HINT_COLOR = (190, 190, 190)

DEBUG_WAV_SAMPLE_RATE = 44100
DEBUG_WAV_DURATION_S = 1.6


def _font(size: int) -> pygame.font.Font:
    return pygame.font.SysFont("consolas,couriernew,monospace", size)


def export_debug_wavs(output_dir: Path, sample_rate: int = DEBUG_WAV_SAMPLE_RATE) -> list[Path]:
    """Writes <output_dir>/debug_engine_<preset>_<speed>.wav for every
    engine preset x speed-level combination (e.g. debug_engine_arcade_
    engine_medium.wav), plus <output_dir>/debug_tire_<preset>.wav for
    every tire screech preset (e.g. debug_tire_grip_slide.wav). Pure
    offline numpy synthesis -- no live pygame.mixer needed. Debug-only
    output: deliberately never written into a committed location by
    anything else in this project (see .gitignore's debug_wav/ entry)."""
    if np is None:
        raise RuntimeError("numpy is required to export debug WAVs")
    output_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for preset_name in ENGINE_PRESET_ORDER:
        preset = ENGINE_PRESETS[preset_name]
        slug = preset_name.lower().replace(" ", "_")
        for speed_name, speed_frac in SPEED_LEVELS.items():
            samples = sfx.render_engine_preview(preset, speed_frac, sample_rate, DEBUG_WAV_DURATION_S)
            path = output_dir / f"debug_engine_{slug}_{speed_name}.wav"
            _write_wav(path, samples, sample_rate)
            written.append(path)
    for preset_name in TIRE_SCREECH_PRESET_ORDER:
        preset = TIRE_SCREECH_PRESETS[preset_name]
        slug = preset_name.lower().replace(" ", "_")
        samples = sfx.render_tire_screech_preview(preset, sample_rate, DEBUG_WAV_DURATION_S)
        path = output_dir / f"debug_tire_{slug}.wav"
        _write_wav(path, samples, sample_rate)
        written.append(path)
    return written


def _write_wav(path: Path, samples: "np.ndarray", sample_rate: int) -> None:
    ints = (np.clip(samples, -1.0, 1.0) * 32767.0).astype(np.int16)
    with wave_module.open(str(path), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(sample_rate)
        f.writeframes(ints.tobytes())


class SfxTestScreen:
    """Interactive comparison screen. The engine's real update()/RPM path
    runs continuously (not just a one-shot static tone), so switching
    speed level also demonstrates the RPM rise/fall behavior live. Tire
    screech has no RPM/speed axis of its own (see sfx.py) -- Space plays
    the selected preset's clip on demand instead."""

    ENGINE_PRESET_KEYS = {pygame.K_a: "LOW RUMBLE", pygame.K_b: "ARCADE ENGINE", pygame.K_c: "CHIP ENGINE"}
    SPEED_KEYS = {pygame.K_1: "idle", pygame.K_2: "low", pygame.K_3: "medium", pygame.K_4: "high"}
    TIRE_PRESET_KEYS = {pygame.K_x: "CLASSIC SQUEAL", pygame.K_y: "GRIP SLIDE", pygame.K_z: "ARCADE CHIRP"}

    def __init__(self):
        self.engine = sfx.EngineSound()
        self.tire = sfx.TireScreech()
        self.speed_name = "idle"
        self.clock = pygame.time.Clock()
        self.font_title = _font(18)
        self.font_hint = _font(14)

    def run(self, test_frames: int | None = None) -> None:
        screen = pygame.display.set_mode(WINDOW_SIZE)
        running = True
        frame = 0
        try:
            while running:
                dt = self.clock.tick(60) / 1000.0
                dt = min(dt, 0.05)
                for event in pygame.event.get():
                    if event.type == pygame.QUIT:
                        running = False
                    elif event.type == pygame.KEYDOWN:
                        if event.key == pygame.K_ESCAPE:
                            running = False
                        elif event.key in self.ENGINE_PRESET_KEYS:
                            self.engine.set_preset(self.ENGINE_PRESET_KEYS[event.key])
                        elif event.key in self.SPEED_KEYS:
                            self.speed_name = self.SPEED_KEYS[event.key]
                        elif event.key in self.TIRE_PRESET_KEYS:
                            self.tire.set_preset(self.TIRE_PRESET_KEYS[event.key])
                        elif event.key == pygame.K_SPACE:
                            self.tire.play_now()
                speed_frac = SPEED_LEVELS[self.speed_name]
                self.engine.update(speed_frac, active=True, dt=dt)
                self._draw(screen)
                pygame.display.flip()
                frame += 1
                if test_frames is not None and frame >= test_frames:
                    running = False
        finally:
            self.engine.stop()
            self.tire.stop()

    def _draw(self, screen: pygame.Surface) -> None:
        screen.fill(BG)
        title_lines = [
            f"ENGINE: {self.engine.preset_name}",
            f"  SPEED: {self.speed_name}   rpm={self.engine.engine_rpm:.2f}"
            f"   available={self.engine.available}",
            f"TIRE SCREECH: {self.tire.preset_name}   available={self.tire.available}",
        ]
        y = 20
        for line in title_lines:
            screen.blit(self.font_title.render(line, True, TITLE_COLOR), (20, y))
            y += 26
        hint_lines = [
            "",
            "A  LOW RUMBLE       (engine)",
            "B  ARCADE ENGINE    (engine)",
            "C  CHIP ENGINE      (engine)",
            "1-4  idle / low / medium / high speed  (engine)",
            "",
            "X  CLASSIC SQUEAL   (tire screech)",
            "Y  GRIP SLIDE       (tire screech)",
            "Z  ARCADE CHIRP     (tire screech)",
            "SPACE  play tire screech now",
            "",
            "ESC quit",
        ]
        for line in hint_lines:
            screen.blit(self.font_hint.render(line, True, HINT_COLOR), (20, y))
            y += 18


def run(test_frames: int | None = None) -> None:
    pygame.mixer.pre_init(frequency=DEBUG_WAV_SAMPLE_RATE, size=-16, channels=2, buffer=512)
    pygame.init()
    if not pygame.mixer.get_init():
        try:
            pygame.mixer.init(frequency=DEBUG_WAV_SAMPLE_RATE, size=-16, channels=2, buffer=512)
        except pygame.error:
            pass
    pygame.display.set_caption("Engine SFX Test")
    SfxTestScreen().run(test_frames=test_frames)
    pygame.quit()


def main() -> None:
    parser = argparse.ArgumentParser(description="Engine SFX audition tool")
    parser.add_argument(
        "--export-wav",
        metavar="DIR",
        help="Write debug_engine_*.wav preview files to DIR and exit (not committed to git).",
    )
    parser.add_argument(
        "--test-frames",
        type=int,
        default=None,
        help="Interactive screen only: render N frames and exit automatically (smoke test / CI).",
    )
    args = parser.parse_args()

    if args.export_wav:
        written = export_debug_wavs(Path(args.export_wav))
        for path in written:
            print(path)
        return

    run(test_frames=args.test_frames)


if __name__ == "__main__":
    main()
