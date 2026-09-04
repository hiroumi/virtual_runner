"""Tests for gamepad.py: startup diagnostics, the Select/Back hold-to-
reset helper, and the 2026-09-04 Xbox-controller gameplay input (analog/
digital steering, accelerate/brake, menu navigation with debounce).

No real gamepad is available in this headless environment (or in CI), so
these either post synthetic CONTROLLERBUTTONDOWN/UP pygame events (the
same mechanism a real SDL_GameController-recognized pad would generate)
or drive the read_*/MenuStickNav functions with a small fake Controller
double implementing the same get_axis()/get_button()/attached()
interface as pygame._sdl2.controller.Controller. Real hardware
verification (does Windows' Xbox controller actually get recognized as
an SDL game controller, do the diagnostics print sensible values, does
input actually feel right) is out of reach here -- see docs/PHASE2_RACE_LOG.md.
"""
import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame

import gamepad
from gamepad import (
    GamepadResetHold,
    MenuStickNav,
    get_primary_controller,
    open_connected_controllers,
    read_accel,
    read_brake,
    read_steer,
)


class _FakeController:
    """Minimal stand-in for pygame._sdl2.controller.Controller -- just
    enough surface (get_axis/get_button/attached) for the read_*/
    MenuStickNav functions under test, none of which touch anything else
    on a real Controller object."""

    def __init__(self, axes=None, buttons=None, is_attached=True):
        self._axes = axes or {}
        self._buttons = set(buttons or ())
        self._is_attached = is_attached

    def get_axis(self, axis):
        return self._axes.get(axis, 0)

    def get_button(self, button):
        return button in self._buttons

    def attached(self):
        return self._is_attached


def _down(button=pygame.CONTROLLER_BUTTON_BACK):
    return pygame.event.Event(pygame.CONTROLLERBUTTONDOWN, button=button, instance_id=0)


def _up(button=pygame.CONTROLLER_BUTTON_BACK):
    return pygame.event.Event(pygame.CONTROLLERBUTTONUP, button=button, instance_id=0)


# -- startup diagnostics ----------------------------------------------------


def test_open_connected_controllers_is_safe_with_no_devices():
    # This environment (and typically CI) has zero real gamepads attached
    # -- must not raise, exactly like a Maker Faire unit that's briefly
    # unplugged shouldn't crash the game.
    pygame.init()
    open_connected_controllers()
    pygame.quit()


def test_open_connected_controllers_logs_the_detected_count(capsys):
    pygame.init()
    open_connected_controllers()
    out = capsys.readouterr().out
    assert "[gamepad]" in out
    assert "0 controller(s) detected" in out  # no real device in this environment
    pygame.quit()


# -- GamepadResetHold (unchanged from the Maker Faire Reset feature) --------


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


# -- read_steer / read_accel / read_brake (2026-09-04) ----------------------


def test_read_steer_with_no_controller_returns_zero():
    assert read_steer(None) == 0.0


def test_read_steer_stick_within_deadzone_returns_zero():
    # Deadzone default is 0.18 -- a small drift value must not steer.
    c = _FakeController(axes={pygame.CONTROLLER_AXIS_LEFTX: 3000})  # ~0.09
    assert read_steer(c) == 0.0


def test_read_steer_stick_past_deadzone_returns_nonzero_signed_value():
    c = _FakeController(axes={pygame.CONTROLLER_AXIS_LEFTX: -20000})  # well past deadzone, left
    value = read_steer(c)
    assert value < 0.0
    assert value >= -1.0

    c2 = _FakeController(axes={pygame.CONTROLLER_AXIS_LEFTX: 20000})
    value2 = read_steer(c2)
    assert value2 > 0.0
    assert value2 <= 1.0


def test_read_steer_extreme_axis_value_clamps_to_unit_range():
    # SDL's raw minimum (-32768) divided by _AXIS_MAX (32767) is just
    # past -1.0 -- must be clamped, not left slightly out of range.
    c = _FakeController(axes={pygame.CONTROLLER_AXIS_LEFTX: -32768})
    assert read_steer(c) == -1.0


def test_read_steer_dpad_left_and_right():
    left = _FakeController(buttons={pygame.CONTROLLER_BUTTON_DPAD_LEFT})
    assert read_steer(left) == -1.0
    right = _FakeController(buttons={pygame.CONTROLLER_BUTTON_DPAD_RIGHT})
    assert read_steer(right) == 1.0


def test_read_steer_combines_stick_and_dpad_but_stays_clamped():
    c = _FakeController(
        axes={pygame.CONTROLLER_AXIS_LEFTX: 32767},
        buttons={pygame.CONTROLLER_BUTTON_DPAD_RIGHT},
    )
    assert read_steer(c) == 1.0  # not > 1.0 even though both push the same way


def test_read_accel_and_brake_reflect_a_and_b_buttons():
    a_held = _FakeController(buttons={pygame.CONTROLLER_BUTTON_A})
    assert read_accel(a_held) is True
    assert read_brake(a_held) is False

    b_held = _FakeController(buttons={pygame.CONTROLLER_BUTTON_B})
    assert read_brake(b_held) is True
    assert read_accel(b_held) is False


def test_read_accel_and_brake_false_with_no_controller():
    assert read_accel(None) is False
    assert read_brake(None) is False


def test_read_accel_and_brake_via_dpad_up_down():
    # 2026-09-05: added as alternatives to A/B, not replacements.
    up = _FakeController(buttons={pygame.CONTROLLER_BUTTON_DPAD_UP})
    assert read_accel(up) is True
    assert read_brake(up) is False

    down = _FakeController(buttons={pygame.CONTROLLER_BUTTON_DPAD_DOWN})
    assert read_brake(down) is True
    assert read_accel(down) is False


def test_read_accel_and_brake_via_left_stick_up_down():
    # SDL's Y axis follows screen convention: up is negative.
    up = _FakeController(axes={pygame.CONTROLLER_AXIS_LEFTY: -20000})
    assert read_accel(up) is True
    assert read_brake(up) is False

    down = _FakeController(axes={pygame.CONTROLLER_AXIS_LEFTY: 20000})
    assert read_brake(down) is True
    assert read_accel(down) is False


def test_read_accel_and_brake_stick_within_deadzone_do_not_fire():
    drifting = _FakeController(axes={pygame.CONTROLLER_AXIS_LEFTY: 3000})  # well under the deadzone
    assert read_accel(drifting) is False
    assert read_brake(drifting) is False


# -- MenuStickNav (debounced menu navigation, 2026-09-04) --------------------


def test_menu_stick_nav_within_deadzone_returns_zero():
    pygame.init()
    nav = MenuStickNav(deadzone=0.5, repeat_ms=250)
    c = _FakeController(axes={pygame.CONTROLLER_AXIS_LEFTX: 5000})  # ~0.15, under 0.5
    assert nav.poll(c) == 0
    pygame.quit()


def test_menu_stick_nav_fresh_push_fires_immediately():
    pygame.init()
    nav = MenuStickNav(deadzone=0.5, repeat_ms=250)
    c = _FakeController(axes={pygame.CONTROLLER_AXIS_LEFTX: -30000})
    assert nav.poll(c) == -1
    pygame.quit()


def test_menu_stick_nav_held_push_does_not_refire_before_the_interval():
    pygame.init()
    nav = MenuStickNav(deadzone=0.5, repeat_ms=250)
    c = _FakeController(axes={pygame.CONTROLLER_AXIS_LEFTX: 30000})
    assert nav.poll(c) == 1
    assert nav.poll(c) == 0  # still held, interval hasn't passed
    pygame.quit()


def test_menu_stick_nav_held_push_refires_after_the_interval():
    pygame.init()
    nav = MenuStickNav(deadzone=0.5, repeat_ms=250)
    c = _FakeController(axes={pygame.CONTROLLER_AXIS_LEFTX: 30000})
    assert nav.poll(c) == 1
    nav._last_fire_ms = pygame.time.get_ticks() - 300  # simulate 300ms elapsed
    assert nav.poll(c) == 1
    pygame.quit()


def test_menu_stick_nav_returning_to_center_allows_an_immediate_refire():
    pygame.init()
    nav = MenuStickNav(deadzone=0.5, repeat_ms=250)
    left = _FakeController(axes={pygame.CONTROLLER_AXIS_LEFTX: -30000})
    centered = _FakeController(axes={pygame.CONTROLLER_AXIS_LEFTX: 0})
    assert nav.poll(left) == -1
    assert nav.poll(centered) == 0
    assert nav.poll(left) == -1  # fresh push again -- no need to wait out repeat_ms
    pygame.quit()


def test_menu_stick_nav_switching_direction_fires_immediately_too():
    pygame.init()
    nav = MenuStickNav(deadzone=0.5, repeat_ms=250)
    left = _FakeController(axes={pygame.CONTROLLER_AXIS_LEFTX: -30000})
    right = _FakeController(axes={pygame.CONTROLLER_AXIS_LEFTX: 30000})
    assert nav.poll(left) == -1
    assert nav.poll(right) == 1  # direction changed -- fires immediately, not delayed
    pygame.quit()


def test_menu_stick_nav_with_no_controller_returns_zero():
    pygame.init()
    nav = MenuStickNav()
    assert nav.poll(None) == 0
    pygame.quit()


# -- get_primary_controller (hot-plug/hot-unplug safety) --------------------


def test_get_primary_controller_returns_none_when_none_open(monkeypatch):
    monkeypatch.setattr(gamepad, "_open_controllers", [])
    assert get_primary_controller() is None


def test_get_primary_controller_returns_the_first_attached_one(monkeypatch):
    c1 = _FakeController(is_attached=True)
    c2 = _FakeController(is_attached=True)
    monkeypatch.setattr(gamepad, "_open_controllers", [c1, c2])
    assert get_primary_controller() is c1


def test_get_primary_controller_prunes_disconnected_controllers(monkeypatch):
    unplugged = _FakeController(is_attached=False)
    still_here = _FakeController(is_attached=True)
    monkeypatch.setattr(gamepad, "_open_controllers", [unplugged, still_here])
    assert get_primary_controller() is still_here
    # Pruned from the module-level list too, not just skipped this call.
    assert unplugged not in gamepad._open_controllers


def test_get_primary_controller_returns_none_if_all_are_unplugged(monkeypatch):
    monkeypatch.setattr(
        gamepad, "_open_controllers",
        [_FakeController(is_attached=False), _FakeController(is_attached=False)],
    )
    assert get_primary_controller() is None
