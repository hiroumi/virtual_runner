"""Tests for the shared Select/Back gamepad hold-to-reset helper (see
input_reset.py). No real gamepad is available in this headless
environment (or in CI), so these post synthetic CONTROLLERBUTTONDOWN/UP
pygame events -- the same mechanism a real SDL_GameController-recognized
pad would generate -- rather than needing real hardware.
"""
import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame

from input_reset import GamepadResetHold, open_connected_controllers


def _down(button=pygame.CONTROLLER_BUTTON_BACK):
    return pygame.event.Event(pygame.CONTROLLERBUTTONDOWN, button=button, instance_id=0)


def _up(button=pygame.CONTROLLER_BUTTON_BACK):
    return pygame.event.Event(pygame.CONTROLLERBUTTONUP, button=button, instance_id=0)


def test_open_connected_controllers_is_safe_with_no_devices():
    # This environment (and typically CI) has zero real gamepads attached
    # -- must not raise, exactly like a Maker Faire unit that's briefly
    # unplugged shouldn't crash the game.
    pygame.init()
    open_connected_controllers()
    pygame.quit()


def test_fresh_hold_does_not_trigger_immediately():
    pygame.init()
    hold = GamepadResetHold(hold_ms=1000)
    hold.handle_event(_down())
    assert hold.triggered() is False
    pygame.quit()


def test_releasing_before_the_threshold_cancels_the_hold():
    pygame.init()
    hold = GamepadResetHold(hold_ms=1000)
    hold.handle_event(_down())
    hold.handle_event(_up())
    assert hold.triggered() is False
    pygame.quit()


def test_holding_past_the_threshold_triggers_exactly_once():
    pygame.init()
    hold = GamepadResetHold(hold_ms=1000)
    # Simulate "already held for 1.5s" without a real 1.5s wait.
    hold._started_ms = pygame.time.get_ticks() - 1500
    assert hold.triggered() is True
    assert hold.triggered() is False  # consumed -- doesn't refire every frame
    pygame.quit()


def test_a_different_button_is_ignored():
    pygame.init()
    hold = GamepadResetHold(hold_ms=1000)
    hold.handle_event(_down(button=pygame.CONTROLLER_BUTTON_A))
    hold._started_ms = None  # sanity: the A press must not have started a hold
    assert hold.triggered() is False
    pygame.quit()
