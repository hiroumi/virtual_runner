"""Shared "Reset" input plumbing: Backspace is immediate everywhere it's
handled (music.py, game.py -- no logic lives here for it, it's a single
keycode check at each call site). Gamepad Select/Back is different -- it
must be *held* for RESET_HOLD_MS before it fires, so a brief accidental
tap at a Maker Faire booth never resets someone's race -- that hold
tracking is common to both the SELECT MUSIC screen and the race itself,
so it lives here rather than being duplicated in music.py and game.py
(which otherwise have no reason to import each other).

Uses pygame's SDL_GameController-backed events (CONTROLLERBUTTONDOWN/UP,
button constants like CONTROLLER_BUTTON_BACK) rather than the raw
JOYBUTTONDOWN/joystick-index API, so "Select/Back" means the same
physical button across different controller models (Xbox/PS-style pads
are both in SDL's built-in controller database) instead of a hard-coded,
device-specific button index.
"""
from __future__ import annotations

import pygame

RESET_HOLD_MS = 1000  # how long Select/Back must be held to trigger a reset
GAMEPAD_RESET_BUTTON = pygame.CONTROLLER_BUTTON_BACK  # Select/Back on Xbox/PS-style pads

# Kept alive here (not just constructed and dropped) since letting a
# pygame.joystick.Joystick wrapper get garbage-collected is not guaranteed
# safe to do while its device is still meant to be delivering events.
_open_joysticks: list[pygame.joystick.JoystickType] = []


def open_connected_controllers() -> None:
    """Best-effort: open every already-connected joystick so SDL's game
    controller layer starts delivering CONTROLLERBUTTONDOWN/UP events for
    it (only for devices SDL's controller database recognizes -- an
    unsupported or absent gamepad just means those events never arrive,
    not a crash). Call once at startup; never raises."""
    try:
        pygame.joystick.init()
        for i in range(pygame.joystick.get_count()):
            _open_joysticks.append(pygame.joystick.Joystick(i))
    except pygame.error:
        pass


def open_controller_from_event(event: pygame.event.Event) -> None:
    """Same as open_connected_controllers, for a single CONTROLLERDEVICEADDED
    event -- handles a gamepad plugged in after the game has already
    started. Ignored (not an error) for any other event type."""
    if event.type != pygame.CONTROLLERDEVICEADDED:
        return
    try:
        _open_joysticks.append(pygame.joystick.Joystick(event.device_index))
    except pygame.error:
        pass


class GamepadResetHold:
    """Tracks how long GAMEPAD_RESET_BUTTON has been held. Feed it every
    CONTROLLERBUTTONDOWN/UP event via handle_event(); call triggered()
    once per frame regardless of whether an event arrived that frame --
    the hold must be detected purely from elapsed time, since holding a
    button generates no repeat events on its own."""

    def __init__(self, hold_ms: int = RESET_HOLD_MS):
        self.hold_ms = hold_ms
        self._started_ms: int | None = None

    def handle_event(self, event: pygame.event.Event) -> None:
        if getattr(event, "button", None) != GAMEPAD_RESET_BUTTON:
            return
        if event.type == pygame.CONTROLLERBUTTONDOWN:
            self._started_ms = pygame.time.get_ticks()
        elif event.type == pygame.CONTROLLERBUTTONUP:
            self._started_ms = None

    def triggered(self) -> bool:
        """True the first time the hold has lasted >= hold_ms; consumes
        the hold (resets to not-held) so it fires exactly once per
        press-and-hold, not on every subsequent frame the button stays
        down."""
        if self._started_ms is None:
            return False
        if pygame.time.get_ticks() - self._started_ms < self.hold_ms:
            return False
        self._started_ms = None
        return True
