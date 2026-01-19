# main_with_ui.py — UI wrapper (PyQt5). Expects engine.run_engine() and engine.FRAME_CALLBACK
import sys
import os
import time
import threading
import json
import traceback

from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QThread
from PyQt5.QtGui import QImage, QPixmap, QFont
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QLabel, QPushButton, QSlider, QSpinBox,
    QCheckBox, QGroupBox, QVBoxLayout, QHBoxLayout, QFormLayout, QTextEdit, QMessageBox
)

# Import engine (module-level imports are safe; engine won't start until run_engine())
import main as engine  # expects run_engine(), FRAME_CALLBACK, cap, calib, etc.

UI_SETTINGS = getattr(engine, "_ui_settings_path", "ui_settings.json") if hasattr(engine, "_ui_settings_path") else "ui_settings.json"

class EngineWorker(QThread):
    frame_ready = pyqtSignal(object)
    started_signal = pyqtSignal()
    stopped_signal = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._running = False

    def run(self):
        try:
            self._running = True
            def _on_frame(frame):
                try:
                    self.frame_ready.emit(frame.copy())
                except Exception:
                    pass
            engine.FRAME_CALLBACK = _on_frame
            self.started_signal.emit()
            engine.run_engine()
        except Exception as e:
            print("EngineWorker exception:", e)
            traceback.print_exc()
        finally:
            try:
                engine.FRAME_CALLBACK = None
            except:
                pass
            self._running = False
            self.stopped_signal.emit()

    def stop(self):
        try:
            if self.isRunning():
                self.terminate()
        except Exception:
            pass
        try:
            engine.FRAME_CALLBACK = None
        except:
            pass

class EyeCursorUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Eye Cursor - Control Panel (UI Preview)")
        self.setMinimumSize(1200, 720)
        self.setFont(QFont("Segoe UI", 9))

        central = QWidget()
        self.setCentralWidget(central)
        main_h = QHBoxLayout(central)
        main_h.setContentsMargins(10, 10, 10, 10)
        main_h.setSpacing(10)

        main_h.addWidget(self._create_camera_section(), stretch=3)

        right_v = QVBoxLayout()
        right_v.setSpacing(10)
        main_h.addLayout(right_v, stretch=2)
        right_v.addWidget(self._create_calibration_section())
        right_v.addWidget(self._create_gesture_section())
        right_v.addWidget(self._create_settings_section())

        self._apply_styles()

        self.worker = None
        self._last_frame = None

        self.preview_timer = QTimer(self)
        self.preview_timer.timeout.connect(self._update_preview)
        self.preview_timer.start(33)  # ~30 FPS UI refresh (engine provides 960x540 frames)

        # create default UI settings file if not exists (dummy)
        if not os.path.exists(UI_SETTINGS):
            try:
                default = {
                    "enable_actions": False,
                    "smoothing_window": 6,
                    "smoothing_alpha": 0.93,
                    "eye_close_thr": 0.018,
                    "min_closed_ms": 220,
                    "snap_radius": 115,
                    "dwell_time": 0.06
                }
                with open(UI_SETTINGS, "w") as f:
                    json.dump(default, f)
            except:
                pass

    def _create_camera_section(self):
        group = QGroupBox("Camera Feed")
        layout = QVBoxLayout(group)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        self.camera_label = QLabel("Camera preview will appear here")
        self.camera_label.setAlignment(Qt.AlignCenter)
        self.camera_label.setFixedHeight(420)
        self.camera_label.setStyleSheet("""
            QLabel { background-color: #101010; color: #bbbbbb; border-radius: 8px; border: 1px solid #333333; }
        """)

        controls = QHBoxLayout()
        self.btn_start = QPushButton("Start Engine")
        self.btn_stop = QPushButton("Stop Engine")
        self.btn_stop.setEnabled(False)

        self.lbl_cam_info = QLabel("Camera: controlled by main.py (module-level)")
        self.lbl_cam_info.setStyleSheet("color: #aaaaaa;")

        controls.addWidget(self.btn_start)
        controls.addWidget(self.btn_stop)
        controls.addStretch()
        controls.addWidget(self.lbl_cam_info)

        self.lbl_status = QLabel("Status: Stopped")
        self.lbl_status.setStyleSheet("color: #aaaaaa;")

        layout.addWidget(self.camera_label)
        layout.addLayout(controls)
        layout.addWidget(self.lbl_status)

        self.btn_start.clicked.connect(self.start_engine)
        self.btn_stop.clicked.connect(self.stop_engine)

        return group

    def _create_calibration_section(self):
        group = QGroupBox("Calibration")
        layout = QVBoxLayout(group)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        instr = QLabel("Run calibration to map your gaze to screen. Uses engine's calibration.")
        instr.setWordWrap(True)

        self.btn_calibrate = QPushButton("Start Calibration")
        self.btn_calibrate.clicked.connect(self._start_calibration_thread)

        self.lbl_cal_status = QLabel("Calibration: Idle")
        self.lbl_cal_status.setStyleSheet("color: #aaaaaa;")

        layout.addWidget(instr)
        layout.addWidget(self.btn_calibrate)
        layout.addWidget(self.lbl_cal_status)

        return group

    def _create_gesture_section(self):
        group = QGroupBox("Gesture Control")
        layout = QVBoxLayout(group)
        info = QLabel("Gestures are handled by the engine. UI allows preview + calibration.")
        info.setWordWrap(True)
        layout.addWidget(info)
        return group

    def _create_settings_section(self):
        group = QGroupBox("Settings")
        layout = QVBoxLayout(group)
        form = QFormLayout()

        self.chk_enable_actions = QCheckBox("Enable actions (click/drag/scroll)")
        self.spin_smooth = QSpinBox()
        self.spin_smooth.setRange(1, 30)
        self.spin_smooth.setValue(6)
        self.slider_alpha = QSlider(Qt.Horizontal)
        self.slider_alpha.setRange(50, 99)
        self.slider_alpha.setValue(93)
        self.slider_eye_thr = QSlider(Qt.Horizontal)
        self.slider_eye_thr.setRange(1, 100)
        self.slider_eye_thr.setValue(int(0.018 * 1000))
        self.spin_min_closed = QSpinBox()
        self.spin_min_closed.setRange(50, 1000)
        self.spin_min_closed.setValue(220)

        form.addRow("Smoothing window:", self.spin_smooth)
        form.addRow("Smoothing alpha (x100):", self.slider_alpha)
        form.addRow("Eye close threshold (x1000):", self.slider_eye_thr)
        form.addRow("Min closed ms:", self.spin_min_closed)
        layout.addLayout(form)

        btn_apply = QPushButton("Apply Settings (Dummy)")
        btn_apply.clicked.connect(self._apply_settings)

        self.txt_notes = QTextEdit()
        self.txt_notes.setPlaceholderText("Debug log...")
        self.txt_notes.setFixedHeight(140)

        layout.addWidget(self.chk_enable_actions)
        layout.addWidget(btn_apply)
        layout.addWidget(self.txt_notes)

        return group

    def _apply_styles(self):
        self.setStyleSheet("""
            QMainWindow { background-color: #181818; }
            QGroupBox { border: 1px solid #333333; border-radius: 10px; margin-top: 8px; background-color: #202020; color: #ffffff; font-weight: 600; }
            QLabel { color: #e0e0e0; }
            QPushButton { background-color: #3a7bd5; color: #ffffff; border-radius: 6px; padding: 6px 12px; }
            QPushButton:hover { background-color: #346dbf; }
            QComboBox, QSpinBox, QTextEdit { background-color: #2a2a2a; color: #ffffff; border-radius: 4px; border: 1px solid #444444; }
            QSlider::groove:horizontal { height: 4px; background: #444444; border-radius: 2px; }
            QSlider::handle:horizontal { width: 14px; height: 14px; margin: -5px 0; border-radius: 7px; background: #3a7bd5; }
            QCheckBox { color: #e0e0e0; }
        """)

    # Engine control
    def start_engine(self):
        if self.worker and self.worker.isRunning():
            QMessageBox.information(self, "Engine", "Engine already running")
            return
        self._append_log("[UI] Starting engine...")
        self.worker = EngineWorker()
        self.worker.frame_ready.connect(self._on_frame_ready)
        self.worker.started_signal.connect(lambda: self._set_status("Running"))
        self.worker.stopped_signal.connect(lambda: self._set_status("Stopped"))
        self.worker.started_signal.connect(lambda: self._append_log("[UI] Engine started."))
        self.worker.stopped_signal.connect(lambda: self._append_log("[UI] Engine stopped."))
        self.worker.start()
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)

    def stop_engine(self):
        if self.worker:
            self._append_log("[UI] Stopping engine...")
            try:
                self.worker.stop()
            except Exception:
                pass
            self.worker = None
        try:
            if hasattr(engine, "cap") and engine.cap:
                try:
                    engine.cap.release()
                except:
                    pass
        except:
            pass
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self._set_status("Stopped")
        self._append_log("[UI] Stop requested.")

    # Preview handler
    def _on_frame_ready(self, frame):
        self._last_frame = frame

    def _update_preview(self):
        if self._last_frame is None:
            return
        try:
            frame = self._last_frame
            h, w = frame.shape[:2]
            bytes_per_line = 3 * w
            qimg = QImage(frame.data, w, h, bytes_per_line, QImage.Format_BGR888)
            pix = QPixmap.fromImage(qimg)
            self.camera_label.setPixmap(pix.scaled(self.camera_label.width(), self.camera_label.height(), Qt.KeepAspectRatio))
        except Exception:
            pass

    # Settings apply (dummy)
    def _apply_settings(self):
        s = {
            "enable_actions": bool(self.chk_enable_actions.isChecked()),
            "smoothing_window": int(self.spin_smooth.value()),
            "smoothing_alpha": float(self.slider_alpha.value()) / 100.0,
            "eye_close_thr": float(self.slider_eye_thr.value()) / 1000.0,
            "min_closed_ms": int(self.spin_min_closed.value())
        }
        try:
            with open(UI_SETTINGS, "w") as f:
                json.dump(s, f)
            self._append_log("[UI] Settings written to " + UI_SETTINGS + " (dummy)")
        except Exception as e:
            self._append_log("[UI] Failed to write settings: " + str(e))

    # Calibration
    def _start_calibration_thread(self):
        if not hasattr(engine, "calib") or not hasattr(engine, "cap"):
            QMessageBox.information(self, "Calibration", "Engine must be running for calibration.")
            return
        def _calib_runner():
            try:
                self._append_log("[UI] Calibration started (blocking)...")
                self.lbl_cal_status.setText("Calibration: Running")
                engine.calib.record_all(engine.get_norm_from_frame, engine.cap)
                self._append_log("[UI] Calibration finished.")
                self.lbl_cal_status.setText("Calibration: Completed")
            except Exception as e:
                self._append_log("[UI] Calibration failed: " + str(e))
                self.lbl_cal_status.setText("Calibration: Failed")
        t = threading.Thread(target=_calib_runner, daemon=True)
        t.start()

    # Logging & status
    def _append_log(self, text):
        ts = time.strftime("%H:%M:%S")
        try:
            self.txt_notes.append(f"[{ts}] {text}")
        except Exception:
            pass

    def _set_status(self, s):
        self.lbl_status.setText("Status: " + s)

    def closeEvent(self, event):
        try:
            self.stop_engine()
        except:
            pass
        event.accept()

def main():
    app = QApplication(sys.argv)
    win = EyeCursorUI()
    win.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
