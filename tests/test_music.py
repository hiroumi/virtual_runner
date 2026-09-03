"""Tests for the pre-race "SELECT MUSIC" screen and its MusicPlayer."""
import os
import sys
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pygame
import pytest

from config import default_config
from music import BGM_DIR, MusicPlayer, MusicSelectScreen, TRACKS, _fit_text
from stereo_renderer import StereoRenderer

BGM_ASSETS_PRESENT = BGM_DIR.is_dir() and any(BGM_DIR.glob("*.mp3"))


def test_tracks_are_in_the_requested_order():
    assert [name for name, _ in TRACKS] == [
        "PIXEL BREEZE",
        "CRIMSON HIGHWAY",
        "BEYOND THE RED HORIZON",
    ]


def test_starts_selected_on_the_first_track():
    m = MusicPlayer()
    assert m.index == 0
    assert m.current_name == "PIXEL BREEZE"


def test_next_cycles_through_all_three_in_order_then_wraps():
    m = MusicPlayer()
    names = [m.current_name]
    for _ in range(4):
        m.next()
        names.append(m.current_name)
    assert names == [
        "PIXEL BREEZE", "CRIMSON HIGHWAY", "BEYOND THE RED HORIZON",
        "PIXEL BREEZE", "CRIMSON HIGHWAY",
    ]


def test_next_from_the_last_track_wraps_to_the_first():
    m = MusicPlayer()
    m.select(len(m.tracks) - 1)
    m.next()
    assert m.index == 0


def test_prev_from_the_first_track_wraps_to_the_last():
    m = MusicPlayer()
    m.select(0)
    m.prev()
    assert m.index == len(m.tracks) - 1


def test_missing_track_file_does_not_raise_and_records_last_error():
    pygame.init()
    m = MusicPlayer(tracks=[("MISSING", "does_not_exist_xyz.mp3")])
    ok = m.play_selected(loop=False)
    assert ok is False
    assert m.last_error is not None
    assert "does_not_exist_xyz.mp3" in m.last_error
    pygame.quit()


def test_missing_track_error_message_is_short_for_a_typical_filename():
    # music.py keeps last_error short (filename + short reason, not the
    # raw exception/path) so it's readable centered on the ~280px
    # calibrated viewport for any realistically-named BGM file.
    pygame.init()
    m = MusicPlayer(tracks=[("MISSING", "does_not_exist_xyz.mp3")])
    m.play_selected(loop=False)
    font = pygame.font.SysFont("consolas,couriernew,monospace", 11)
    assert font.size(m.last_error)[0] < 280
    pygame.quit()


def test_fit_text_truncates_an_overlong_message_to_fit_the_viewport():
    # Regression backstop: even if a BGM file were named something
    # unusually long, MusicSelectScreen._draw's use of _fit_text must
    # never let the centered error line overflow both edges and become
    # unreadable (this was observed happening before _fit_text existed).
    pygame.init()
    font = pygame.font.SysFont("consolas,couriernew,monospace", 11)
    long_text = "a_very_long_filename_that_does_not_exist_at_all_and_keeps_going.mp3: file not found"
    assert font.size(long_text)[0] > 280  # sanity: this really would have overflowed
    fitted = _fit_text(font, long_text, 280)
    assert font.size(fitted)[0] <= 280
    assert fitted.endswith("…")
    pygame.quit()


def test_switching_after_a_missing_track_clears_the_previous_error():
    pygame.init()
    m = MusicPlayer(tracks=[("MISSING", "nope.mp3"), ("PIXEL BREEZE", "Pixel_Breeze.mp3")])
    m.play_selected(loop=False)
    assert m.last_error is not None
    m.next()
    ok = m.play_selected(loop=False)
    if BGM_ASSETS_PRESENT:
        assert ok is True
        assert m.last_error is None
    pygame.quit()


@pytest.mark.skipif(not BGM_ASSETS_PRESENT, reason="bgm/ assets not present")
def test_real_tracks_all_load_and_play():
    pygame.init()
    m = MusicPlayer()
    for i in range(len(m.tracks)):
        m.select(i)
        ok = m.play_selected(loop=False, fade_ms=0)
        assert ok is True, m.last_error
        assert m.last_error is None
    pygame.mixer.music.stop()
    pygame.quit()


def _make_screen():
    pygame.init()
    cfg = default_config()
    screen = pygame.display.set_mode((cfg.output_width, cfg.output_height))
    renderer = StereoRenderer(screen, cfg)
    music = MusicPlayer()
    return MusicSelectScreen(renderer, music), music


def test_select_screen_test_frames_mode_previews_and_returns_without_blocking():
    screen, music = _make_screen()
    idx = screen.run(test_frames=3)
    assert idx == 0
    assert music.current_name == "PIXEL BREEZE"
    pygame.quit()


def test_select_screen_draws_without_crashing_for_every_track(monkeypatch):
    screen, music = _make_screen()
    for i in range(len(music.tracks)):
        music.select(i)
        screen._draw_frame()
    pygame.quit()


def _scripted_keydowns(keys):
    events = iter(pygame.event.Event(pygame.KEYDOWN, key=k, mod=0) for k in keys)

    def fake_get():
        try:
            return [next(events)]
        except StopIteration:
            return []

    return fake_get


def test_right_right_enter_selects_the_third_track(monkeypatch):
    screen, music = _make_screen()
    monkeypatch.setattr(
        pygame.event, "get", _scripted_keydowns([pygame.K_RIGHT, pygame.K_RIGHT, pygame.K_RETURN])
    )
    result = screen.run(test_frames=None)
    assert result == 2
    assert music.current_name == "BEYOND THE RED HORIZON"
    pygame.quit()


def test_left_from_the_first_track_wraps_to_the_last_via_the_event_loop(monkeypatch):
    screen, music = _make_screen()
    monkeypatch.setattr(pygame.event, "get", _scripted_keydowns([pygame.K_LEFT, pygame.K_SPACE]))
    result = screen.run(test_frames=None)
    assert result == 2
    assert music.current_name == "BEYOND THE RED HORIZON"
    pygame.quit()


def test_escape_quits_without_selecting(monkeypatch):
    screen, music = _make_screen()
    monkeypatch.setattr(pygame.event, "get", _scripted_keydowns([pygame.K_ESCAPE]))
    result = screen.run(test_frames=None)
    assert result is None
    pygame.quit()
