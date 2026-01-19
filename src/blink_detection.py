# blink_detection.py — Stable, low-latency per-eye blink detector
import time
import math

# MediaPipe landmarks (after frame is flipped with cv2.flip(frame, 1)):
# NOTE:
#   - These are IMAGE eyes, not user eyes.
#   - image-left eye  -> user's RIGHT eye
#   - image-right eye -> user's LEFT eye
LEFT_UPPER = [386, 385, 384]     # image-LEFT  (user RIGHT)
LEFT_LOWER = [373, 374, 380]
RIGHT_UPPER = [159, 158, 157]    # image-RIGHT (user LEFT)
RIGHT_LOWER = [145, 144, 153]


def mean_point(lm, idxs, w, h):
    xs = [(lm.landmark[i].x * w) for i in idxs]
    ys = [(lm.landmark[i].y * h) for i in idxs]
    return sum(xs) / len(xs), sum(ys) / len(ys)


def dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


class BlinkDetector:
    """
    Stable, low-latency per-eye blink detection.

    Exposed to main.py as:
        blink = BlinkDetector(eye_close_thr=0.018, min_closed_ms=220)

    It returns a dict:
        {
          "left_closed": bool,   # USER LEFT eye (for drag / scroll)
          "right_closed": bool,  # USER RIGHT eye
          "both_closed": bool,

          "left_blink": bool,    # user LEFT wink (eye-only)
          "right_blink": bool,   # user RIGHT wink (eye-only)
          "both_blink": bool     # both eyes blink together
        }

    Design:
    - Hysteresis thresholds to avoid flicker:
        close_thr -> eye considered closed
        open_thr  -> eye considered open again
    - Timing windows (in seconds):
        blink_min..blink_max  -> both-eye blink
        wink_min..wink_max    -> one-eye wink
    - Natural tiny blinks are ignored (no click).
    """

    def __init__(
        self,
        eye_close_thr=0.018,    # used as closing threshold
        min_closed_ms=220,      # base value for timing windows (ms)

        # internal tuning (can stay default)
        open_thr_offset=0.003,
        blink_min=None, blink_max=None,
        wink_min=None, wink_max=None
    ):
        # thresholds
        self.close_thr = eye_close_thr
        self.open_thr = eye_close_thr + open_thr_offset

        base = min_closed_ms / 1000.0  # convert to seconds

        # Wider / more forgiving windows derived from base
        # Typical blink is roughly 0.15–0.40s, but we allow more.
        if blink_min is not None:
            self.blink_min = blink_min
        else:
            self.blink_min = base * 0.4     # e.g. 0.088s if base=0.22

        if blink_max is not None:
            self.blink_max = blink_max
        else:
            self.blink_max = base * 3.0     # e.g. ~0.66s

        if wink_min is not None:
            self.wink_min = wink_min
        else:
            self.wink_min = base * 0.5      # e.g. ~0.11s

        if wink_max is not None:
            self.wink_max = wink_max
        else:
            self.wink_max = base * 3.5      # e.g. ~0.77s

        # RAW (image) closed states
        self.l_closed_raw = False
        self.r_closed_raw = False

        # USER states for previous frame
        self.prev_L = False   # user LEFT closed
        self.prev_R = False   # user RIGHT closed
        self.prev_B = False   # both closed

        # timing
        self.tL = 0.0
        self.tR = 0.0
        self.tB = 0.0

        # during a both-eyes closure, we suppress wink classification
        self.both_dominant = False

    def _ratios(self, lm, shape):
        h, w, _ = shape

        # IMAGE-LEFT (user RIGHT)
        upL = mean_point(lm, LEFT_UPPER, w, h)
        loL = mean_point(lm, LEFT_LOWER, w, h)
        rawL = dist(upL, loL) / h

        # IMAGE-RIGHT (user LEFT)
        upR = mean_point(lm, RIGHT_UPPER, w, h)
        loR = mean_point(lm, RIGHT_LOWER, w, h)
        rawR = dist(upR, loR) / h

        return rawL, rawR

    def update(self, lm, shape):
        now = time.time()

        # 1) raw eyelid distances
        rawL, rawR = self._ratios(lm, shape)

        # 2) hysteresis on RAW image eyes
        if not self.l_closed_raw:
            self.l_closed_raw = rawL < self.close_thr
        else:
            self.l_closed_raw = rawL < self.open_thr

        if not self.r_closed_raw:
            self.r_closed_raw = rawR < self.close_thr
        else:
            self.r_closed_raw = rawR < self.open_thr

        # 3) flip correction → USER eyes
        # IMAGE-left eye  => user's RIGHT eye
        # IMAGE-right eye => user's LEFT eye
        user_left_closed = self.r_closed_raw   # USER LEFT
        user_right_closed = self.l_closed_raw  # USER RIGHT
        both_closed = user_left_closed and user_right_closed

        L = user_left_closed
        R = user_right_closed
        B = both_closed

        left_blink = False
        right_blink = False
        both_blink = False

        # ---------------------------
        # BOTH-EYE BLINK STATE
        # ---------------------------
        if B and not self.prev_B:
            # both just closed
            self.tB = now
            self.both_dominant = True   # any winks during this window are ignored

        if (not B) and self.prev_B:
            # both just opened
            dB = now - self.tB
            if self.blink_min <= dB <= self.blink_max:
                both_blink = True
            self.both_dominant = False

        # ---------------------------
        # LEFT (USER) EYE STATE
        # ---------------------------
        if L and not self.prev_L:
            self.tL = now

        if (not L) and self.prev_L:
            dL = now - self.tL
            # Only treat as left wink if we were NOT in a both-eyes dominant blink
            if (not self.both_dominant) and (self.wink_min <= dL <= self.wink_max):
                left_blink = True

        # ---------------------------
        # RIGHT (USER) EYE STATE
        # ---------------------------
        if R and not self.prev_R:
            self.tR = now

        if (not R) and self.prev_R:
            dR = now - self.tR
            if (not self.both_dominant) and (self.wink_min <= dR <= self.wink_max):
                right_blink = True

        # update previous states
        self.prev_L = L
        self.prev_R = R
        self.prev_B = B

        # if we detected BOTH blink, we don't want separate winks at the same moment
        if both_blink:
            left_blink = False
            right_blink = False

        return {
            "left_closed": L,       # USER LEFT eye
            "right_closed": R,      # USER RIGHT eye
            "both_closed": B,
            "left_blink": left_blink,
            "right_blink": right_blink,
            "both_blink": both_blink
        }
