"""Xbox/PS-style gamepad support: device detection + startup diagnostics,
SDL GameController-mapped input (menu navigation, steering/accel/brake,
Reset), hot-plug handling, and graceful degradation with no gamepad
connected (or an unrecognized one -- keyboard always keeps working).

2026-09-04: previously the only gamepad code in this project was the
Reset hold (GamepadResetHold, unchanged below) -- Xbox controllers were
detected at the OS level (Windows' joy.cpl showed buttons/axes moving)
but had no effect in the game at all, because nothing else ever read
gamepad input. This module adds that: real-time steering/accelerate/
brake for the race and D-pad/stick/button navigation for SELECT MUSIC.

Uses pygame's SDL_GameController layer (pygame._sdl2.controller, plus
the CONTROLLER_* event/constant namespace already used by
GamepadResetHold) rather than raw joystick axis/button indices, so "A",
"Start", "D-pad left", "left stick X" etc. mean the same physical
control across different controller models (recognized via SDL's
built-in controller mapping database) instead of a hard-coded,
device-specific index -- this is what lets Windows' native Xbox
controller support work here with no extra key-mapping software.
"""
from __future__ import annotations

import pygame
import pygame._sdl2.controller as sdl2_controller

RESET_HOLD_MS = 1000  # how long Select/Back must be held to trigger a reset
GAMEPAD_RESET_BUTTON = pygame.CONTROLLER_BUTTON_BACK  # Select/Back on Xbox/PS-style pads

# SDL's raw stick axis range is -32768..32767 (Controller.get_axis()
# returns this integer range directly, unlike pygame.joystick.Joystick's
# already-normalized float). 32767 (not 32768) keeps the normalized
# result symmetric around 0.
_AXIS_MAX = 32767.0

# Center-position drift on an analog stick (a worn/cheap pad rarely reads
# exactly 0 at rest) must never read as steering input -- anything with
# |value| under this is treated as exactly centered. 0.15-0.20 is a
# typical range for this; picked the middle of that as a starting point,
# tunable per the spec ("初期値は0.15~0.20程度").
STEER_DEADZONE = 0.18

# Menu navigation reads the stick as a discrete "which way was it
# pushed" rather than a proportional value, so it needs a much coarser
# deadzone than steering does (a firm, deliberate push, not "roughly off
# center") plus its own debounce -- see MenuStickNav.
MENU_STICK_DEADZONE = 0.5
MENU_STICK_REPEAT_MS = 250  # how often a held stick deflection re-fires

# Kept alive here (not just constructed and dropped) since letting a
# pygame.joystick.Joystick/Controller wrapper get garbage-collected is
# not guaranteed safe to do while its device is still meant to be
# delivering events/state.
_open_joysticks: list[pygame.joystick.JoystickType] = []
_open_controllers: list[sdl2_controller.Controller] = []
_controller_module_ready = False


def _log_joystick_diagnostics(index: int, js: pygame.joystick.JoystickType) -> None:
    """Startup diagnostics requested for the Xbox-controller investigation:
    name, GUID, axis/button/hat counts, and whether SDL's game controller
    layer recognizes this device (if not, only raw joystick events would
    be available for it -- this project doesn't use those, so such a
    device would be gamepad-silent in-game even though Windows sees it)."""
    try:
        name = js.get_name()
    except pygame.error:
        name = "<unknown>"
    try:
        guid = js.get_guid()
    except pygame.error:
        guid = "<unknown>"
    try:
        num_axes = js.get_numaxes()
    except pygame.error:
        num_axes = -1
    try:
        num_buttons = js.get_numbuttons()
    except pygame.error:
        num_buttons = -1
    try:
        num_hats = js.get_numhats()
    except pygame.error:
        num_hats = -1
    is_game_controller = False
    if _controller_module_ready:
        try:
            is_game_controller = bool(sdl2_controller.is_controller(index))
        except (pygame.error, sdl2_controller.error):
            pass
    print(
        f"[gamepad] #{index}: name={name!r} guid={guid} axes={num_axes} "
        f"buttons={num_buttons} hats={num_hats} sdl_game_controller={is_game_controller}"
    )


def _try_open_controller(index: int) -> None:
    """Best-effort: if SDL's game controller layer recognizes the device
    at this joystick index, open it and keep it -- devices it doesn't
    recognize simply never get one (no error; they just can't drive
    in-game input through this module, matching the diagnostic line's
    sdl_game_controller=False)."""
    if not _controller_module_ready:
        return
    try:
        if sdl2_controller.is_controller(index):
            _open_controllers.append(sdl2_controller.Controller(index))
    except (pygame.error, sdl2_controller.error):
        pass


def open_connected_controllers() -> None:
    """Opens every already-connected joystick (so SDL starts delivering
    events/state for it) and logs the diagnostics requested for the Xbox-
    controller investigation. Call once at startup; never raises -- no
    gamepad, or an unrecognized one, must never stop the game from
    running keyboard-only."""
    global _controller_module_ready
    try:
        pygame.joystick.init()
    except pygame.error:
        print("[gamepad] pygame.joystick.init() failed -- gamepad input unavailable")
        return

    try:
        sdl2_controller.init()
        _controller_module_ready = True
    except (pygame.error, sdl2_controller.error):
        _controller_module_ready = False

    count = pygame.joystick.get_count()
    print(f"[gamepad] {count} controller(s) detected")
    for i in range(count):
        try:
            js = pygame.joystick.Joystick(i)
        except pygame.error:
            continue
        _open_joysticks.append(js)
        _log_joystick_diagnostics(i, js)
        _try_open_controller(i)


def open_controller_from_event(event: pygame.event.Event) -> None:
    """Same as open_connected_controllers, for a single CONTROLLERDEVICEADDED
    event -- handles a gamepad plugged in after the game has already
    started ("実行中のコントローラー抜き差し"). Ignored (not an error) for
    any other event type."""
    if event.type != pygame.CONTROLLERDEVICEADDED:
        return
    index = event.device_index
    try:
        js = pygame.joystick.Joystick(index)
    except pygame.error:
        return
    _open_joysticks.append(js)
    _log_joystick_diagnostics(index, js)
    _try_open_controller(index)


def get_primary_controller() -> "sdl2_controller.Controller | None":
    """The first still-connected opened controller, or None if none are
    connected (or none are recognized as an SDL game controller) -- the
    single controller this project's input reading/menu navigation
    drives from. Lazily prunes disconnected entries every call, so a
    mid-race unplug just degrades back to keyboard-only input instead of
    raising or needing an explicit CONTROLLERDEVICEREMOVED handler."""
    global _open_controllers
    _open_controllers = [c for c in _open_controllers if _controller_attached(c)]
    return _open_controllers[0] if _open_controllers else None


def _controller_attached(controller: "sdl2_controller.Controller") -> bool:
    try:
        return bool(controller.attached())
    except (pygame.error, sdl2_controller.error):
        return False


def _axis(controller, axis: int) -> float:
    """Normalized -1..1, or 0.0 if there's no controller or the read
    fails for any reason (e.g. it was unplugged this exact frame)."""
    if controller is None:
        return 0.0
    try:
        raw = controller.get_axis(axis)
    except (pygame.error, sdl2_controller.error):
        return 0.0
    return max(-1.0, min(1.0, raw / _AXIS_MAX))


def _button(controller, button: int) -> bool:
    if controller is None:
        return False
    try:
        return bool(controller.get_button(button))
    except (pygame.error, sdl2_controller.error):
        return False


def read_steer(controller, deadzone: float = STEER_DEADZONE) -> float:
    """-1..1 for the race's analog steering: the left stick's X axis
    (deadzone-clamped so resting near center never reads as input),
    combined with the D-pad left/right as a full-deflection digital
    alternative -- either one alone drives the car, and pressing both
    just adds (clamped back to +-1). Returns 0.0 with no controller."""
    stick = _axis(controller, pygame.CONTROLLER_AXIS_LEFTX)
    if abs(stick) < deadzone:
        stick = 0.0
    dpad = 0.0
    if _button(controller, pygame.CONTROLLER_BUTTON_DPAD_LEFT):
        dpad -= 1.0
    if _button(controller, pygame.CONTROLLER_BUTTON_DPAD_RIGHT):
        dpad += 1.0
    return max(-1.0, min(1.0, stick + dpad))


def read_accel(controller) -> bool:
    """A button held, for the race's accelerate."""
    return _button(controller, pygame.CONTROLLER_BUTTON_A)


def read_brake(controller) -> bool:
    """B button held, for the race's brake."""
    return _button(controller, pygame.CONTROLLER_BUTTON_B)


class MenuStickNav:
    """Left-stick left/right for SELECT MUSIC's track navigation,
    debounced so holding the stick over doesn't spam-switch tracks every
    frame ("曲が高速で連続切り替えされないよう"): a fresh push (crossing
    into a direction from center or the other side) fires immediately,
    and a sustained deflection re-fires only every `repeat_ms` after
    that -- the D-pad needs none of this since CONTROLLERBUTTONDOWN
    already only fires once per physical press."""

    def __init__(self, deadzone: float = MENU_STICK_DEADZONE, repeat_ms: int = MENU_STICK_REPEAT_MS):
        self.deadzone = deadzone
        self.repeat_ms = repeat_ms
        self._last_direction = 0  # -1, 0, or +1
        self._last_fire_ms: int | None = None

    def poll(self, controller) -> int:
        """Call once per menu frame. Returns -1 (switch to previous
        track), +1 (switch to next), or 0 (nothing to do this frame)."""
        value = _axis(controller, pygame.CONTROLLER_AXIS_LEFTX)
        if value < -self.deadzone:
            direction = -1
        elif value > self.deadzone:
            direction = 1
        else:
            self._last_direction = 0
            return 0

        now = pygame.time.get_ticks()
        if direction != self._last_direction:
            self._last_direction = direction
            self._last_fire_ms = now
            return direction
        if self._last_fire_ms is not None and now - self._last_fire_ms >= self.repeat_ms:
            self._last_fire_ms = now
            return direction
        return 0


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
