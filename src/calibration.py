# calibration.py — Freeze-proof, 13-point, fullscreen, safe for low FPS
import cv2
import time
import statistics
import json
import os

CALIB_POINTS_REL_13 = [
    ("TL", (0.05, 0.05)),
    ("TC", (0.50, 0.05)),
    ("TR", (0.95, 0.05)),
    ("QL", (0.25, 0.25)),
    ("QC", (0.50, 0.25)),
    ("QR", (0.75, 0.25)),
    ("CL", (0.05, 0.50)),
    ("CC", (0.50, 0.50)),
    ("CR", (0.95, 0.50)),
    ("BL", (0.05, 0.95)),
    ("BC", (0.50, 0.95)),
    ("BR", (0.95, 0.95)),
    ("C2", (0.75, 0.75)),
]

DEFAULT_SAVE_PATH = "calibration_data.json"

class Calibration:
    def __init__(self, points_def=CALIB_POINTS_REL_13):
        self.points_def = points_def
        self.points = {}
        self.dx_min = 0.0
        self.dx_max = 1.0
        self.dy_min = 0.0
        self.dy_max = 1.0
        self.window_name = "Calibration"
        self.save_path = DEFAULT_SAVE_PATH

    def _px(self, frame, rel):
        h, w = frame.shape[:2]
        return int(rel[0] * w), int(rel[1] * h)

    def _draw(self, frame, target, progress, msg):
        x, y = target
        h, w = frame.shape[:2]

        overlay = frame.copy()
        cv2.rectangle(overlay, (0,0), (w,h), (0,0,0), -1)
        cv2.addWeighted(overlay, 0.45, frame, 0.55, 0, frame)

        radius = 18 + int(progress * 32)
        cv2.circle(frame, (x, y), radius, (0,160,255), -1)
        cv2.circle(frame, (x, y), 4, (255,255,255), -1)

        cv2.putText(frame, msg, (20,36),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (240,240,240), 2)

        bar_w = int(w * 0.55)
        bar_x = (w - bar_w) // 2
        bar_y = h - 50
        cv2.rectangle(frame, (bar_x, bar_y),
                      (bar_x + bar_w, bar_y + 18), (80,80,80), -1)
        fill = int(progress * bar_w)
        cv2.rectangle(frame, (bar_x, bar_y),
                      (bar_x + fill, bar_y + 18), (0,210,0), -1)
        cv2.rectangle(frame, (bar_x, bar_y),
                      (bar_x + bar_w, bar_y + 18), (200,200,200), 1)
        return frame

    def _collect(self, norm_func, cap, rel, min_samples=8, max_samples=20, max_time=2.5):
        """Never freezes. Collects until samples OR timeout."""
        samples = []
        start = time.time()

        while True:
            ret, frame = cap.read()
            if not ret:
                continue
            frame = cv2.flip(frame, 1)

            tx, ty = self._px(frame, rel)

            now = time.time()
            elapsed = now - start

            # get gaze sample
            v = None
            try:
                v = norm_func()
            except:
                v = None

            if v is not None:
                samples.append((v[0], v[1]))

            # draw prog
            prog = min(1.0, max(len(samples)/max_samples, elapsed/max_time))
            fr = self._draw(frame, (tx,ty), prog, f"{len(samples)} samples...")

            cv2.imshow(self.window_name, fr)
            if cv2.waitKey(1) & 0xFF == ord('q'):
                pass  # ignore q

            # stopping rules
            if len(samples) >= max_samples:
                break
            if elapsed >= max_time and len(samples) >= min_samples:
                break

        return samples

    def record_all(self, norm_func, cap):
        cv2.namedWindow(self.window_name, cv2.WINDOW_NORMAL)
        try:
            cv2.setWindowProperty(self.window_name, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
        except:
            cv2.resizeWindow(self.window_name, 1920,1080)

        print("\n=== Starting 13-point calibration ===")

        self.points = {}
        for name, rel in self.points_def:
            print(f"Point: {name}")

            # warmup
            for _ in range(4): cap.read()

            # collect (freeze-proof)
            s = self._collect(norm_func, cap, rel)

            if len(s) < 4:
                print(f"SKIP {name} (not enough)")
                continue

            xs = [p[0] for p in s]
            ys = [p[1] for p in s]
            self.points[name] = (statistics.median(xs), statistics.median(ys))

        # compute extents
        xs = [v[0] for v in self.points.values()]
        ys = [v[1] for v in self.points.values()]
        self.dx_min = min(xs)
        self.dx_max = max(xs)
        self.dy_min = min(ys)
        self.dy_max = max(ys)

        self.save()
        cv2.destroyWindow(self.window_name)
        print("Calibration complete.")

    def map_norm_to_screen(self, nx, ny, sw, sh, m=12):
        denom_x = max(self.dx_max - self.dx_min, 1e-6)
        denom_y = max(self.dy_max - self.dy_min, 1e-6)
        rx = (nx - self.dx_min) / denom_x
        ry = (ny - self.dy_min) / denom_y
        rx = min(max(rx,0),1)
        ry = min(max(ry,0),1)
        sx = int(rx * sw)
        sy = int(ry * sh)
        return max(m, min(sw - m, sx)), max(m, min(sh - m, sy))

    def save(self):
        data = {
            "points": {k: [float(v[0]), float(v[1])] for k,v in self.points.items()},
            "dx_min": float(self.dx_min),
            "dx_max": float(self.dx_max),
            "dy_min": float(self.dy_min),
            "dy_max": float(self.dy_max),
            "t": time.time()
        }
        with open(DEFAULT_SAVE_PATH, "w") as f:
            json.dump(data, f, indent=2)
        print("Saved calibration.json successfully.")

    def load(self):
        with open(DEFAULT_SAVE_PATH, "r") as f:
            data = json.load(f)
        self.points = {k: (float(v[0]), float(v[1])) for k,v in data["points"].items()}
        self.dx_min = data["dx_min"]
        self.dx_max = data["dx_max"]
        self.dy_min = data["dy_min"]
        self.dy_max = data["dy_max"]
        print("Loaded calibration.json successfully.")
