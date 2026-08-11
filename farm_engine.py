"""Reusable automation engine for farming EXP.

This module is safe to import. It does not parse command-line arguments,
inspect the screen, or start the farming loop until ``FarmEngine.run`` is
called.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
import threading
import time
from typing import Callable, Optional

import cv2
import mss
import numpy as np
import pyautogui
import pygetwindow as gw


_DIR = os.path.dirname(os.path.abspath(__file__))

GAME_WINDOW_TITLE_KEYWORDS = [
    "SD Gundam G Generation ETERNAL",
    "BlueStacks",
    "NIKKE",
    "LDPlayer",
    "MuMu",
]

NEXT_BATTLE_IMAGE = os.path.join(_DIR, "assets", "next_alt.png")
NEXT_EXP_IMAGE = os.path.join(_DIR, "assets", "next.png")
RETRY_IMAGE = os.path.join(_DIR, "assets", "retry.png")


@dataclass(frozen=True)
class FarmConfig:
    """Inputs and tuning values used by the farming engine."""

    total_energy: int
    energy_per_try: int
    match_threshold: float = 0.82
    battle_wait_seconds: int = 60
    transition_wait_seconds: int = 3
    poll_wait_seconds: int = 2

    def __post_init__(self) -> None:
        if self.total_energy < 0:
            raise ValueError("total_energy must be zero or greater")
        if self.energy_per_try <= 0:
            raise ValueError("energy_per_try must be greater than zero")
        if not 0 < self.match_threshold <= 1:
            raise ValueError("match_threshold must be between zero and one")

    @property
    def target_retries(self) -> int:
        return self.total_energy // self.energy_per_try


@dataclass(frozen=True)
class FarmStatus:
    """Snapshot emitted by the engine while it runs."""

    state: str
    retry_count: int
    target_retries: int
    message: str = ""


@dataclass(frozen=True)
class GameWindow:
    left: int
    top: int
    width: int
    height: int
    title: str


class FarmEngine:
    """Find the game window and automate the EXP farming workflow."""

    scales = np.arange(0.5, 1.6, 0.05)

    def __init__(
        self,
        config: FarmConfig,
        on_status: Optional[Callable[[FarmStatus], None]] = None,
    ) -> None:
        self.config = config
        self.on_status = on_status
        self._stop_event = threading.Event()
        self.retry_count = 0

    def stop(self) -> None:
        """Request that the current run stop at the next safe opportunity."""

        self._stop_event.set()

    def _emit(self, state: str, message: str = "") -> None:
        if self.on_status:
            self.on_status(
                FarmStatus(
                    state=state,
                    retry_count=self.retry_count,
                    target_retries=self.config.target_retries,
                    message=message,
                )
            )

    def get_game_window(self) -> GameWindow:
        for window in gw.getAllWindows():
            title = window.title.lower()
            if any(keyword.lower() in title for keyword in GAME_WINDOW_TITLE_KEYWORDS):
                return GameWindow(
                    left=window.left,
                    top=window.top,
                    width=window.width,
                    height=window.height,
                    title=window.title,
                )
        raise RuntimeError("Game window not found")

    @staticmethod
    def grab_window(region: dict[str, int]) -> np.ndarray:
        with mss.mss() as sct:
            image = np.array(sct.grab(region))
        return cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)

    def find_button(self, template_path: str, region: dict[str, int]):
        if not os.path.exists(template_path):
            return None

        screenshot = self.grab_window(region)
        screenshot_gray = cv2.cvtColor(screenshot, cv2.COLOR_BGR2GRAY)
        template = cv2.imread(template_path, cv2.IMREAD_GRAYSCALE)
        if template is None:
            return None

        best_score = 0.0
        best_location = None

        for scale in self.scales:
            resized = cv2.resize(
                template, None, fx=scale, fy=scale, interpolation=cv2.INTER_LINEAR
            )
            height, width = resized.shape
            if height > screenshot_gray.shape[0] or width > screenshot_gray.shape[1]:
                continue

            result = cv2.matchTemplate(
                screenshot_gray, resized, cv2.TM_CCOEFF_NORMED
            )
            _, score, _, location = cv2.minMaxLoc(result)
            if score > best_score:
                best_score = score
                best_location = (location[0] + width // 2, location[1] + height // 2)

        if best_location is None or best_score < self.config.match_threshold:
            return None

        return region["left"] + best_location[0], region["top"] + best_location[1]

    def _wait(self, seconds: int) -> bool:
        return not self._stop_event.wait(seconds)

    def run(self) -> None:
        """Run until the configured number of retries completes or stopped."""

        self.retry_count = 0
        self._emit("starting", f"Starting auto-farmer. Target runs: {self.config.target_retries}")

        while self.retry_count < self.config.target_retries:
            if self._stop_event.is_set():
                self._emit("stopped", "Stopped by user")
                return

            try:
                self._emit("finding_window", "Finding game window")
                window = self.get_game_window()
            except RuntimeError as error:
                self._emit("waiting_for_window", str(error))
                if not self._wait(5):
                    self._emit("stopped", "Stopped by user")
                    return
                continue

            search_region = {
                "left": window.left + window.width // 2,
                "top": window.top + window.height // 2,
                "width": window.width // 2,
                "height": window.height // 2,
            }

            self._emit("finding_battle_next", "Finding battle report Next button")
            battle_next = self.find_button(NEXT_BATTLE_IMAGE, search_region)
            if battle_next:
                self._emit("clicking_battle_next", "Battle report Next detected")
                pyautogui.click(*battle_next)
                if not self._wait(self.config.transition_wait_seconds):
                    self._emit("stopped", "Stopped by user")
                    return

                self._emit("finding_exp_next", "Finding EXP screen Next button")
                exp_next = self.find_button(NEXT_EXP_IMAGE, search_region)
                if exp_next:
                    self._emit("clicking_exp_next", "EXP screen Next detected")
                    pyautogui.click(*exp_next)
                    if not self._wait(self.config.transition_wait_seconds):
                        self._emit("stopped", "Stopped by user")
                        return

                self._emit("finding_retry", "Finding Retry button")
                retry_button = self.find_button(RETRY_IMAGE, search_region)
                if retry_button:
                    pyautogui.click(*retry_button)
                    self.retry_count += 1
                    self._emit(
                        "retry_clicked",
                        f"Run {self.retry_count}/{self.config.target_retries} completed",
                    )
                    if not self._wait(self.config.battle_wait_seconds):
                        self._emit("stopped", "Stopped by user")
                        return

            if not self._wait(self.config.poll_wait_seconds):
                self._emit("stopped", "Stopped by user")
                return

        self._emit("completed", "Finished")
