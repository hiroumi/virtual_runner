"""BGM selection and playback: the pre-race "SELECT MUSIC" screen, and the
MusicPlayer wrapper both it and the race itself use.

pygame.mixer.music is a single global streaming channel (SDL_mixer's own
design -- there's exactly one "current track", not a per-Sound object per
track), so all loading/switching/looping logic lives in MusicPlayer
instead of being duplicated between the select screen and Game. Every
mixer call is wrapped in a broad try/except: a missing or unreadable BGM
file must never crash the game, only leave last_error set and playback
silent (see MusicPlayer.play_selected).
"""
from __future__ import annotations

from pathlib import Path

import pygame

BGM_DIR = Path(__file__).resolve().parent / "bgm"

# (display name, filename in BGM_DIR), in the order they cycle through.
TRACKS: list[tuple[str, str]] = [
    ("PIXEL BREEZE", "Pixel_Breeze.mp3"),
    ("CRIMSON HIGHWAY", "Crimson_Highway.mp3"),
    ("BEYOND THE RED HORIZON", "Beyond_the_red_horizon.mp3"),
]

PREVIEW_FADE_MS = 250  # short fade-in when switching preview tracks
LOOP_FADE_MS = 400     # short fade-in when the race's looped playback begins
BGM_VOLUME = 0.65      # 60-70% of full scale, per spec -- pygame.mixer.music
                        # has no default other than 1.0 (full), so this must
                        # be set explicitly on every load/play (see below)

BLACK = (0, 0, 0)
TITLE_COLOR = (255, 90, 90)
TRACK_COLOR = (255, 210, 110)
HINT_COLOR = (190, 190, 190)
ERROR_COLOR = (255, 120, 120)

TRIANGLE_SIZE = 10   # half-height of each selector triangle, px
TRIANGLE_GAP = 16    # px between a triangle and the track name


def _font(size: int) -> pygame.font.Font:
    return pygame.font.SysFont("consolas,couriernew,monospace", size)


def _fit_text(font: pygame.font.Font, text: str, max_width: int) -> str:
    """Truncates text with a trailing ellipsis so it renders no wider than
    max_width. Used for the error line: MusicPlayer.last_error is already
    kept short for the common case (see its own comment), but a long BGM
    filename could still overflow the ~280px calibrated viewport when
    centered -- this is the defensive backstop for that."""
    while font.size(text)[0] > max_width and len(text) > 1:
        text = text[:-2] + "…"
    return text


class MusicPlayer:
    """Wraps pygame.mixer.music with track selection, safe load/play, and
    the "stop current, play new from the start" switching behavior the
    select screen needs. A single instance is shared by the select screen
    and (once a track is chosen) by Game, since pygame.mixer.music itself
    is process-global -- this class just gives that global state a
    trackable index and the fallback-on-error behavior the spec requires."""

    def __init__(self, tracks: list[tuple[str, str]] = TRACKS, bgm_dir: Path = BGM_DIR):
        self.tracks = tracks
        self.bgm_dir = bgm_dir
        self.index = 0
        self.last_error: str | None = None

    @property
    def current_name(self) -> str:
        return self.tracks[self.index][0]

    def _path_for(self, index: int) -> Path:
        return self.bgm_dir / self.tracks[index][1]

    def select(self, index: int) -> None:
        self.index = index % len(self.tracks)

    def next(self) -> None:
        self.select(self.index + 1)

    def prev(self) -> None:
        self.select(self.index - 1)

    def play_selected(self, loop: bool, fade_ms: int = 0) -> bool:
        """(Re)loads and plays the currently-selected track from the
        beginning -- loading a new track already stops whatever mixer.music
        was doing, so no separate stop() call is needed first. Returns
        True on success; on any failure (missing file, unreadable/corrupt
        data, mixer not initialized, ...) records a human-readable
        last_error and returns False without raising, so callers can carry
        on with no BGM instead of crashing."""
        path = self._path_for(self.index)
        self.last_error = None
        try:
            pygame.mixer.music.load(str(path))
            # Set before play(): with fade_ms>0 this is the volume the
            # fade-in ramps *to*, not an instant jump that would cut the
            # fade short.
            pygame.mixer.music.set_volume(BGM_VOLUME)
            pygame.mixer.music.play(loops=(-1 if loop else 0), fade_ms=fade_ms)
            return True
        except (pygame.error, OSError) as exc:
            # Kept short on purpose: the calibrated viewports are only
            # ~280px wide, and the select screen centers this text -- the
            # full exception (often a long Windows/WSL path) would run off
            # both edges and become unreadable rather than informative.
            reason = "file not found" if not path.exists() else exc.__class__.__name__
            self.last_error = f"{path.name}: {reason}"
            return False

    def switch_to_selected_preview(self) -> bool:
        """Stop whatever's playing and preview the newly selected track
        from the beginning, looped (so it keeps playing while the player
        is still deciding) with a short fade-in."""
        return self.play_selected(loop=True, fade_ms=PREVIEW_FADE_MS)

    def start_looping(self) -> bool:
        """Called once the player confirms their selection: (re)start the
        same track from the beginning, looping, for the race itself."""
        return self.play_selected(loop=True, fade_ms=LOOP_FADE_MS)


class MusicSelectScreen:
    """The "SELECT MUSIC" screen shown before the race: title, a
    left-triangle / track-name / right-triangle row, and (if the current
    track failed to load) a short error line -- all drawn through the same
    StereoRenderer.draw_flat the HUD uses, so it's zero-parallax and never
    touches the calibrated viewport/eye-gap settings in cfg."""

    def __init__(self, renderer, music: MusicPlayer):
        self.renderer = renderer
        self.music = music
        self.font_title = _font(20)
        self.font_track = _font(16)
        self.font_hint = _font(12)
        self.font_error = _font(11)
        self.clock = pygame.time.Clock()

    def run(self, test_frames: int | None = None) -> int | None:
        """Returns the confirmed track index, or None if the player quit
        without confirming (window close / Esc)."""
        self.music.select(0)
        self.music.switch_to_selected_preview()

        if test_frames is not None:
            # Headless smoke test: no real input is available, and
            # --test-frames' budget is meant for the race itself (see
            # game.run()) -- render a couple of frames here just to prove
            # this screen doesn't crash, then auto-confirm.
            for _ in range(min(test_frames, 3)):
                self._draw_frame()
            return self.music.index

        while True:
            self.clock.tick(60)
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    return None
                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        return None
                    elif event.key in (pygame.K_LEFT, pygame.K_a):
                        self.music.prev()
                        self.music.switch_to_selected_preview()
                    elif event.key in (pygame.K_RIGHT, pygame.K_d):
                        self.music.next()
                        self.music.switch_to_selected_preview()
                    elif event.key in (pygame.K_RETURN, pygame.K_SPACE):
                        return self.music.index
            self._draw_frame()

    def _draw_frame(self) -> None:
        self.renderer.begin_frame(BLACK)
        self.renderer.draw_flat(self._draw)
        self.renderer.present()
        pygame.display.flip()

    def _draw(self, surf: pygame.Surface, ox: float) -> None:
        w, h = surf.get_size()
        cx = w / 2 + ox

        title_surf = self.font_title.render("SELECT MUSIC", True, TITLE_COLOR)
        surf.blit(title_surf, title_surf.get_rect(center=(cx, h / 2 - 26)))

        name_surf = self.font_track.render(self.music.current_name, True, TRACK_COLOR)
        row_w = TRIANGLE_SIZE * 2 + TRIANGLE_GAP * 2 + name_surf.get_width()
        row_left = cx - row_w / 2
        cy = h / 2 + 6

        left_tri_x = row_left + TRIANGLE_SIZE
        pygame.draw.polygon(
            surf, TRACK_COLOR,
            [(left_tri_x, cy - TRIANGLE_SIZE), (left_tri_x, cy + TRIANGLE_SIZE), (row_left, cy)],
        )
        name_x = row_left + TRIANGLE_SIZE + TRIANGLE_GAP
        surf.blit(name_surf, (name_x, cy - name_surf.get_height() / 2))
        right_tri_x = name_x + name_surf.get_width() + TRIANGLE_GAP
        pygame.draw.polygon(
            surf, TRACK_COLOR,
            [(right_tri_x, cy - TRIANGLE_SIZE), (right_tri_x, cy + TRIANGLE_SIZE),
             (right_tri_x + TRIANGLE_SIZE, cy)],
        )

        if self.music.last_error:
            text = _fit_text(self.font_error, self.music.last_error, w - 12)
            err_surf = self.font_error.render(text, True, ERROR_COLOR)
            surf.blit(err_surf, err_surf.get_rect(center=(cx, h / 2 + 34)))

        hint_surf = self.font_hint.render("<- ->  CHANGE   ENTER  START", True, HINT_COLOR)
        surf.blit(hint_surf, hint_surf.get_rect(center=(cx, h - 18)))
