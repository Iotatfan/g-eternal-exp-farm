"""Window-bound EXP farming with confirmed screen transitions."""
from __future__ import annotations
from dataclasses import dataclass
import logging
import math
import os
import threading
import time
from typing import Callable
import cv2
import mss
import numpy as np
import pyautogui
import pygetwindow as gw

LOGGER = logging.getLogger(__name__)
_DIR = os.path.dirname(os.path.abspath(__file__))
GAME_WINDOW_TITLE_KEYWORDS = ['SD Gundam G Generation ETERNAL', 'BlueStacks', 'LDPlayer', 'MuMu']
NEXT_BATTLE_IMAGE = os.path.join(_DIR, 'assets', 'next_alt.png')
NEXT_EXP_IMAGE = os.path.join(_DIR, 'assets', 'next.png')
RETRY_IMAGE = os.path.join(_DIR, 'assets', 'retry.png')
REQUIRED_ASSETS = {'battle report Next': NEXT_BATTLE_IMAGE, 'EXP screen Next': NEXT_EXP_IMAGE, 'Retry': RETRY_IMAGE}

@dataclass(frozen=True)
class FarmConfig:
    total_energy: int
    energy_per_try: int
    match_threshold: float = 0.82
    battle_wait_seconds: float = 60  # Compatibility only; battles are now observed.
    transition_wait_seconds: float = 3  # Compatibility only; transitions are now observed.
    poll_wait_seconds: float = 2
    window_handle: int | None = None
    transition_timeout_seconds: float = 30
    battle_timeout_seconds: float = 600

    def __post_init__(self) -> None:
        if type(self.total_energy) is not int or self.total_energy < 0:
            raise ValueError('total_energy must be an integer zero or greater')
        if type(self.energy_per_try) is not int or self.energy_per_try <= 0:
            raise ValueError('energy_per_try must be an integer greater than zero')
        if not math.isfinite(self.match_threshold) or not 0 < self.match_threshold <= 1:
            raise ValueError('match_threshold must be between zero and one')
        for name in ('battle_wait_seconds', 'transition_wait_seconds', 'poll_wait_seconds',
                     'transition_timeout_seconds', 'battle_timeout_seconds'):
            value = getattr(self, name)
            if not math.isfinite(value) or value < 0:
                raise ValueError(f'{name} must be finite and nonnegative')
        if self.window_handle is not None and (type(self.window_handle) is not int or self.window_handle <= 0):
            raise ValueError('window_handle must be a positive integer')

    @property
    def target_retries(self) -> int:
        return self.total_energy // self.energy_per_try

@dataclass(frozen=True)
class FarmStatus:
    state: str
    retry_count: int  # Compatibility alias for confirmed completed battles.
    target_retries: int
    message: str = ''
    started_count: int = 0
    completed_count: int = 0
    suspension_reason: str = ''

class FarmValidationError(ValueError):
    """Invalid assets or target window selection."""

@dataclass(frozen=True)
class GameWindow:
    left: int
    top: int
    width: int
    height: int
    title: str
    handle: int = 0

def list_game_windows() -> list[GameWindow]:
    """List titled windows; the caller must explicitly select one."""
    return [GameWindow(w.left, w.top, w.width, w.height, w.title, w._hWnd)
            for w in gw.getAllWindows() if w.title.strip() and w.width > 1 and w.height > 1]

def select_game_window(title: str | None = None) -> GameWindow:
    candidates = [w for w in list_game_windows()
                  if (title.casefold() in w.title.casefold() if title else
                      any(k.casefold() in w.title.casefold() for k in GAME_WINDOW_TITLE_KEYWORDS))]
    if len(candidates) != 1:
        names = ', '.join(w.title for w in candidates) or 'none'
        raise FarmValidationError(f'Select exactly one game window using --window-title (matches: {names})')
    return candidates[0]

class FarmEngine:
    scales = np.arange(0.5, 1.6, 0.05)

    def __init__(self, config: FarmConfig, on_status: Callable[[FarmStatus], None] | None = None) -> None:
        self.config = config
        self.on_status = on_status
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._control_lock = threading.RLock()
        self._generation = 0
        self._recovery_generation = 0
        self._paused_since: float | None = None
        self._paused_seconds = 0.0
        self.suspension_reason = ''
        self.started_count = 0
        self.retry_count = 0
        self._templates: dict[str, list[np.ndarray]] = {}
        self._window_handle = config.window_handle

    @property
    def is_paused(self) -> bool:
        return self._pause_event.is_set()

    @staticmethod
    def validate_assets() -> list[str]:
        errors = []
        for label, path in REQUIRED_ASSETS.items():
            if not os.path.isfile(path):
                errors.append(f'{label} asset is missing: {path}')
            elif cv2.imread(path, cv2.IMREAD_GRAYSCALE) is None:
                errors.append(f'{label} asset cannot be read: {path}')
        return errors

    def validate_startup(self) -> None:
        errors = self.validate_assets()
        if errors:
            raise FarmValidationError('\n'.join(errors))
        if self.config.target_retries and self._window_handle is None:
            self._window_handle = select_game_window().handle

    def stop(self) -> None:
        with self._control_lock:
            self._stop_event.set()
            self._generation += 1

    def pause(self) -> None:
        with self._control_lock:
            if not self.is_paused:
                self._paused_since = time.monotonic()
                self._pause_event.set()
                self._generation += 1
                self._emit('paused', 'Paused')

    def _suspend(self, reason: str) -> None:
        with self._control_lock:
            if self._stop_event.is_set():
                return
            self.pause()
            self.suspension_reason = reason
            self._emit('suspended', reason + '; correct the condition, then Resume')

    def resume(self) -> None:
        with self._control_lock:
            if not self.is_paused:
                return
            self._paused_seconds += time.monotonic() - self._paused_since
            self._paused_since = None
            if self.suspension_reason:
                self._recovery_generation += 1
            self.suspension_reason = ''
            self._generation += 1
            self._pause_event.clear()
            self._emit('resumed', 'Resumed; checking the current screen')

    def _active_time(self) -> float:
        with self._control_lock:
            now = self._paused_since if self.is_paused else time.monotonic()
            return now - self._paused_seconds

    def status(self, state: str, message: str = '') -> FarmStatus:
        return FarmStatus(state, self.retry_count, self.config.target_retries, message,
                          self.started_count, self.retry_count, self.suspension_reason)

    def _emit(self, state: str, message: str = '') -> None:
        if message:
            LOGGER.log(logging.ERROR if state == 'error' else logging.INFO, message)
        if self.on_status:
            self.on_status(self.status(state, message))

    def get_game_window(self) -> GameWindow:
        try:
            return self._read_game_window()
        except gw.PyGetWindowException as error:
            raise RuntimeError(f'Selected window became unavailable: {error}') from error

    def _read_game_window(self) -> GameWindow:
        window = next((w for w in gw.getAllWindows() if w._hWnd == self._window_handle), None)
        if window is None:
            raise RuntimeError('Selected window disappeared')
        if window.isMinimized or window.width <= 1 or window.height <= 1:
            raise RuntimeError('Selected window is minimized or has invalid bounds')
        active = gw.getActiveWindow()
        if active is None or active._hWnd != self._window_handle:
            raise RuntimeError('Selected window lost focus')
        return GameWindow(window.left, window.top, window.width, window.height, window.title, window._hWnd)

    @staticmethod
    def _region(window: GameWindow) -> dict[str, int]:
        return {'left': window.left + window.width // 2, 'top': window.top + window.height // 2,
                'width': window.width // 2, 'height': window.height // 2}

    @staticmethod
    def grab_window(region: dict[str, int]) -> np.ndarray:
        with mss.mss() as sct:
            image = np.array(sct.grab(region))
        return cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)

    def find_button(self, template_path: str, region: dict[str, int]) -> tuple[int, int] | None:
        if template_path not in self._templates:
            template = cv2.imread(template_path, cv2.IMREAD_GRAYSCALE)
            if template is None:
                raise FarmValidationError(f'Template cannot be read: {template_path}')
            self._templates[template_path] = [cv2.resize(template, None, fx=s, fy=s,
                                                        interpolation=cv2.INTER_LINEAR) for s in self.scales]
        screenshot = cv2.cvtColor(self.grab_window(region), cv2.COLOR_BGR2GRAY)
        best_score, best_location = 0.0, None
        for resized in self._templates[template_path]:
            if self._stop_event.is_set() or self.is_paused:
                return None
            height, width = resized.shape
            if height > screenshot.shape[0] or width > screenshot.shape[1]:
                continue
            _, score, _, location = cv2.minMaxLoc(cv2.matchTemplate(screenshot, resized, cv2.TM_CCOEFF_NORMED))
            if score > best_score:
                best_score = score
                best_location = (region['left'] + location[0] + width // 2,
                                 region['top'] + location[1] + height // 2)
        return best_location if best_score >= self.config.match_threshold else None

    def _checkpoint(self) -> bool:
        while self.is_paused and not self._stop_event.is_set():
            self._stop_event.wait(0.05)
        return not self._stop_event.is_set()

    def _wait(self, seconds: float) -> bool:
        deadline = self._active_time() + seconds
        while self._checkpoint():
            remaining = deadline - self._active_time()
            if remaining <= 0:
                return True
            self._stop_event.wait(min(0.05, remaining))
        return False

    def _click(self, location: tuple[int, int], window: GameWindow, generation: int) -> bool:
        with self._control_lock:
            if self._stop_event.is_set() or self.is_paused or generation != self._generation:
                return False
            if self.get_game_window() != window:
                return False  # Moved/resized while matching; capture again.
            pyautogui.click(*location)
            return True

    def run(self) -> None:
        """Run once, counting only additional battles confirmed by their reports."""
        try:
            self.validate_startup()
            self._emit('starting', f'Target: {self.config.target_retries} additional battles')
            if not self.config.target_retries:
                self._emit('completed', 'Finished; no additional battles requested')
                return
            self._run_workflow()
        except Exception as error:
            self._emit('error', str(error))
            raise

    def _run_workflow(self) -> None:
        state = 'battle_report'
        stage_started = self._active_time()
        recovery = self._recovery_generation
        self._emit(state, 'Waiting for initial battle report')
        while self._checkpoint():
            if recovery != self._recovery_generation:
                recovery = self._recovery_generation
                stage_started = self._active_time()
            generation = self._generation
            try:
                window = self.get_game_window()
                path = {'battle_report': NEXT_BATTLE_IMAGE, 'exp': NEXT_EXP_IMAGE,
                        'retry': RETRY_IMAGE, 'retry_departure': RETRY_IMAGE}[state]
                location = self.find_button(path, self._region(window))
                # Control changes invalidate even absent-button observations.
                if self._stop_event.is_set() or self.is_paused or generation != self._generation:
                    continue
                if self.get_game_window() != window:
                    continue
                next_state = None
                if state == 'retry_departure' and location is None:
                    self.started_count += 1
                    next_state = 'battle_report'
                    self._emit('battle_started', f'Additional battle {self.started_count} started')
                elif location is not None:
                    if state == 'battle_report':
                        if self.started_count > self.retry_count:
                            self.retry_count += 1
                            self._emit('battle_completed', f'Completed {self.retry_count}/{self.config.target_retries} additional battles')
                        if self._click(location, window, generation):
                            next_state = 'exp'
                    elif state == 'exp' and self._click(location, window, generation):
                        next_state = 'retry'
                    elif state == 'retry':
                        if self.retry_count == self.config.target_retries:
                            self._emit('completed', 'Finished; final results processed')
                            return
                        if self._click(location, window, generation):
                            next_state = 'retry_departure'
                if next_state:
                    state = next_state
                    stage_started = self._active_time()
                    self._emit(state, {'battle_report': 'Waiting for battle report', 'exp': 'Waiting for EXP Next',
                                       'retry': 'Waiting for Retry', 'retry_departure': 'Confirming Retry disappeared'}[state])
                elif self._active_time() - stage_started >= (
                        self.config.battle_timeout_seconds if state == 'battle_report' else self.config.transition_timeout_seconds):
                    self._suspend(f"Timed out waiting for {state.replace('_', ' ')}; no click will be repeated automatically")
            except (RuntimeError, mss.exception.ScreenShotError) as error:
                self._suspend(str(error))
            if not self._wait(max(0.01, self.config.poll_wait_seconds)):
                break
        self._emit('stopped', 'Stopped by user')
