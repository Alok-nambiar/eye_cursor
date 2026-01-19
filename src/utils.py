# utils.py
from collections import deque
import math

class SmoothFilter:
    def __init__(self, ma_window=5, exp_alpha=0.8):
        """
        Combines a moving average over last ma_window points and exponential smoothing.
        exp_alpha closer to 1 -> faster response
        """
        self.ma_window = ma_window
        self.exp_alpha = exp_alpha
        self.buffer_x = deque(maxlen=ma_window)
        self.buffer_y = deque(maxlen=ma_window)
        self.prev = None

    def update(self, x, y):
        self.buffer_x.append(x)
        self.buffer_y.append(y)
        avg_x = sum(self.buffer_x) / len(self.buffer_x)
        avg_y = sum(self.buffer_y) / len(self.buffer_y)
        if self.prev is None:
            self.prev = (avg_x, avg_y)
            return (avg_x, avg_y)
        sx = self.exp_alpha * avg_x + (1 - self.exp_alpha) * self.prev[0]
        sy = self.exp_alpha * avg_y + (1 - self.exp_alpha) * self.prev[1]
        self.prev = (sx, sy)
        return (sx, sy)

def dist(p1, p2):
    return math.hypot(p1[0] - p2[0], p1[1] - p2[1])

def clamp_step(prev_x, prev_y, target_x, target_y, max_step):
    """
    Limits how far the cursor can move in a single frame (prevents huge jumps).
    """
    dx = target_x - prev_x
    dy = target_y - prev_y
    d = math.hypot(dx, dy)
    if d <= max_step or d == 0:
        return target_x, target_y
    scale = max_step / d
    return int(prev_x + dx * scale), int(prev_y + dy * scale)
