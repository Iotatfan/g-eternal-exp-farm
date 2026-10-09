"""CustomTkinter desktop interface for the EXP farmer."""

from __future__ import annotations

from datetime import datetime
import json
import logging
import os
import queue
import threading
import tempfile
import tkinter.messagebox as messagebox

import customtkinter as ctk

from farm_engine import FarmConfig, FarmEngine, FarmStatus, list_game_windows
import pygetwindow as gw


LOGGER = logging.getLogger(__name__)
SETTINGS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "settings.json")


def load_settings(path: str) -> dict:
    try:
        with open(path, encoding="utf-8-sig") as source:
            settings = json.load(source)
        if not isinstance(settings, dict):
            return {}
        values = [settings.get("total_energy", ""), settings.get("energy_per_try", "")]
        if any(type(value) not in (str, int) for value in values):
            return {}
        total, per_try = map(int, values)
        FarmConfig(total, per_try)
        title = settings.get("window_title", "")
        return {"total_energy": str(total), "energy_per_try": str(per_try),
                "window_title": title if isinstance(title, str) else ""}
    except (OSError, ValueError, TypeError):
        return {}


def save_settings(path: str, settings: dict) -> None:
    """Atomically replace settings, leaving the previous file intact on failure."""
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=os.path.dirname(path),
                                         delete=False) as target:
            temporary = target.name
            json.dump(settings, target, indent=2)
            target.write("\n")
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.remove(temporary)


class FarmApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title("G Eternal EXP Farm")
        self.geometry("780x700")
        self.minsize(700, 620)

        self._events: queue.Queue[tuple[int, FarmStatus]] = queue.Queue()
        self._engine: FarmEngine | None = None
        self._worker: threading.Thread | None = None
        self._run_id = 0
        self._running = False
        self._closing = False
        self._windows = {}
        self._config_widgets = []
        self._log_lines = 0
        self._preferred_title = ""

        self.total_energy = ctk.StringVar()
        self.energy_per_try = ctk.StringVar()
        self.run_count = ctk.StringVar(value="0 / 0 runs")
        self.status_text = ctk.StringVar(value="Ready")
        self.window_choice = ctk.StringVar(value="Select a game window")

        self._load_settings()
        self._build_ui()
        self._refresh_windows()
        self._refresh_calculation()
        self.after(100, self._process_events)
        self.protocol("WM_DELETE_WINDOW", self._close)

    def _load_settings(self) -> None:
        """Load the last-used input values, if a settings file exists."""

        settings = load_settings(SETTINGS_PATH)
        self.total_energy.set(settings.get("total_energy", ""))
        self.energy_per_try.set(settings.get("energy_per_try", ""))
        self._preferred_title = settings.get("window_title", "")

    def _save_settings(self) -> None:
        """Persist the last-entered values for the next GUI launch."""

        try:
            config = FarmConfig(int(self.total_energy.get()), int(self.energy_per_try.get()))
        except (TypeError, ValueError):
            return
        selected = self._windows.get(self.window_choice.get())
        settings = {"total_energy": str(config.total_energy), "energy_per_try": str(config.energy_per_try),
                    "window_title": selected.title if selected else self._preferred_title}
        try:
            save_settings(SETTINGS_PATH, settings)
        except OSError as error:
            LOGGER.warning("Could not save settings: %s", error)

    def _build_ui(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)

        ctk.CTkLabel(
            self, text="G Eternal EXP Farm", font=ctk.CTkFont(size=24, weight="bold")
        ).grid(row=0, column=0, padx=24, pady=(22, 4), sticky="w")
        ctk.CTkLabel(
            self, text="Enter energy remaining after the manual start. Select the game window."
        ).grid(row=1, column=0, padx=24, pady=(0, 18), sticky="w")

        settings = ctk.CTkFrame(self)
        settings.grid(row=2, column=0, padx=24, pady=0, sticky="ew")
        settings.grid_columnconfigure((0, 1), weight=1)

        self._config_widgets.append(self._add_input(settings, 0, "Remaining energy", self.total_energy))
        self._config_widgets.append(self._add_input(settings, 1, "Energy per try", self.energy_per_try))
        self.window_menu = ctk.CTkOptionMenu(settings, variable=self.window_choice,
                                            values=["Select a game window"])
        self.window_menu.grid(row=1, column=0, padx=14, pady=4, sticky="ew")
        self.refresh_button = ctk.CTkButton(settings, text="Refresh windows", command=self._refresh_windows)
        self.refresh_button.grid(row=1, column=1, padx=14, pady=4, sticky="ew")
        self._config_widgets.extend([self.window_menu, self.refresh_button])
        ctk.CTkLabel(settings, textvariable=self.run_count).grid(
            row=2, column=0, columnspan=2, padx=14, pady=(4, 8), sticky="w"
        )
        self.progress = ctk.CTkProgressBar(settings)
        self.progress.grid(row=3, column=0, columnspan=2, padx=14, pady=(0, 14), sticky="ew")
        self.progress.set(0)
        self.total_energy.trace_add("write", lambda *_: self._refresh_calculation())
        self.energy_per_try.trace_add("write", lambda *_: self._refresh_calculation())

        log_frame = ctk.CTkFrame(self)
        log_frame.grid(row=3, column=0, padx=24, pady=18, sticky="nsew")
        log_frame.grid_rowconfigure(1, weight=1)
        log_frame.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(log_frame, text="Activity log", anchor="w").grid(
            row=0, column=0, padx=14, pady=(10, 4), sticky="ew"
        )
        self.log_box = ctk.CTkTextbox(log_frame, state="disabled")
        self.log_box.grid(row=1, column=0, padx=10, pady=(0, 10), sticky="nsew")

        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=4, column=0, padx=24, pady=(0, 20), sticky="ew")
        footer.grid_columnconfigure((0, 1, 2), weight=1)
        ctk.CTkLabel(footer, textvariable=self.status_text, anchor="w", wraplength=640).grid(
            row=0, column=0, columnspan=3, pady=(0, 10), sticky="ew"
        )
        self.start_button = ctk.CTkButton(footer, text="Start", command=self._start)
        self.start_button.grid(row=1, column=0, padx=(0, 8), sticky="ew")
        self.pause_button = ctk.CTkButton(
            footer, text="Pause", command=self._toggle_pause, state="disabled"
        )
        self.pause_button.grid(row=1, column=1, padx=8, sticky="ew")
        self.stop_button = ctk.CTkButton(
            footer, text="Stop", command=self._stop, state="disabled", fg_color="#9b2c2c"
        )
        self.stop_button.grid(row=1, column=2, padx=(8, 0), sticky="ew")

    @staticmethod
    def _add_input(parent, column: int, label: str, variable: ctk.StringVar):
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.grid(row=0, column=column, padx=14, pady=14, sticky="ew")
        frame.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(frame, text=label, anchor="w").grid(row=0, column=0, sticky="ew")
        entry = ctk.CTkEntry(frame, textvariable=variable)
        entry.grid(
            row=1, column=0, pady=(5, 0), sticky="ew"
        )
        return entry

    def _refresh_windows(self) -> None:
        if self._running or self._closing:
            return
        previous = self.window_choice.get()
        try:
            self._windows = {f"{w.title} [{w.handle}]": w for w in list_game_windows()
                             if w.handle != self.winfo_id() and w.title != self.title()}
        except Exception as error:
            self.status_text.set(f"Could not list windows: {error}")
            self._windows = {}
        self.window_menu.configure(values=["Select a game window", *self._windows])
        preferred = [label for label, w in self._windows.items() if w.title == self._preferred_title]
        self.window_choice.set(previous if previous in self._windows else
                               preferred[0] if len(preferred) == 1 else "Select a game window")

    @staticmethod
    def _focus_target(handle: int) -> None:
        try:
            window = next((w for w in gw.getAllWindows() if w._hWnd == handle), None)
            if window is not None and not window.isMinimized:
                window.activate()
        except Exception as error:
            LOGGER.warning("Could not focus selected window: %s", error)

    def _refresh_calculation(self) -> None:
        if self._running:
            return
        try:
            total = int(self.total_energy.get())
            per_try = int(self.energy_per_try.get())
            if total < 0 or per_try <= 0:
                raise ValueError
            self.run_count.set(f"Target: {total // per_try} additional battles")
        except ValueError:
            self.run_count.set("Enter valid energy values")

    def _start(self) -> None:
        if self._closing or (self._worker and self._worker.is_alive()):
            return
        try:
            selected = self._windows.get(self.window_choice.get())
            if selected is None or selected.handle not in {w.handle for w in list_game_windows()}:
                raise ValueError("Select a current game window; refresh the list if necessary")
            config = FarmConfig(int(self.total_energy.get()), int(self.energy_per_try.get()),
                                window_handle=selected.handle)
        except (TypeError, ValueError) as error:
            messagebox.showerror("Invalid configuration", str(error))
            return

        asset_errors = FarmEngine.validate_assets()
        if asset_errors:
            messagebox.showerror("Missing automation assets", "\n".join(asset_errors))
            return

        self._save_settings()
        self._run_id += 1
        run_id = self._run_id
        self._engine = FarmEngine(config, on_status=lambda status: self._events.put((run_id, status)))
        self._worker = threading.Thread(target=self._run_engine, args=(self._engine, run_id), daemon=True)
        self.progress.set(0)
        self.run_count.set(f"Started: 0 | Completed: 0 / {config.target_retries}")
        self._set_running(True)
        self._focus_target(selected.handle)
        self._worker.start()

    def _run_engine(self, engine: FarmEngine, run_id: int) -> None:
        try:
            engine.run()
        except Exception:  # Surface worker failures in the GUI log.
            LOGGER.exception("Farm worker failed")
            # Engine emits its error snapshot, preserving counts; do not duplicate it.

    def _toggle_pause(self) -> None:
        if not self._engine:
            return
        if not self._engine.is_paused:
            self._engine.pause()
            self.pause_button.configure(text="Resume")
        else:
            self._focus_target(self._engine.config.window_handle)
            self._engine.resume()
            self.pause_button.configure(text="Pause")

    def _stop(self) -> None:
        if self._engine:
            self._engine.stop()
            self.status_text.set("Stopping...")

    def _process_events(self) -> None:
        if self._closing:
            return
        try:
            while True:
                run_id, status = self._events.get_nowait()
                if run_id != self._run_id:
                    continue
                self.status_text.set(status.message or status.state.replace("_", " ").title())
                self.run_count.set(f"Started: {status.started_count} | Completed: {status.completed_count} / {status.target_retries}")
                self.progress.set(status.completed_count / status.target_retries if status.target_retries else
                                  1 if status.state == "completed" else 0)
                self._append_log(status.message or status.state)
        except queue.Empty:
            pass
        if self._running and self._worker and not self._worker.is_alive():
            self._set_running(False)
        elif self._running and self._engine:
            self.pause_button.configure(text="Resume" if self._engine.is_paused else "Pause")
        self.after(100, self._process_events)

    def _append_log(self, message: str) -> None:
        self.log_box.configure(state="normal")
        lines = message.splitlines() or [""]
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_box.insert("end", "".join(f"[{timestamp}] {line}\n" for line in lines))
        self._log_lines += len(lines)
        if self._log_lines > 1000:
            self.log_box.delete("1.0", f"{self._log_lines - 1000 + 1}.0")
            self._log_lines = 1000
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _set_running(self, running: bool) -> None:
        self._running = running
        state = "disabled" if running else "normal"
        self.start_button.configure(state=state)
        self.pause_button.configure(state="normal" if running else "disabled", text="Pause")
        self.stop_button.configure(state="normal" if running else "disabled")
        for widget in self._config_widgets:
            widget.configure(state=state)

    def _close(self) -> None:
        if self._closing:
            return
        self._closing = True
        self._save_settings()
        if self._engine:
            self._engine.stop()
        self.status_text.set("Stopping before closing...")
        self._finish_close()

    def _finish_close(self) -> None:
        if self._worker and self._worker.is_alive():
            self.after(50, self._finish_close)
        else:
            self.destroy()


def launch() -> None:
    """Launch the desktop application."""

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )
    ctk.set_appearance_mode("System")
    ctk.set_default_color_theme("blue")
    app = FarmApp()
    app.mainloop()


if __name__ == "__main__":
    launch()
