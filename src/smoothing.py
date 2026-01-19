from collections import deque

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

        sx = int(self.exp_alpha * avg_x + (1 - self.exp_alpha) * self.prev[0])
        sy = int(self.exp_alpha * avg_y + (1 - self.exp_alpha) * self.prev[1])

        self.prev = (sx, sy)
        return (sx, sy)
