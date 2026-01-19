# gaze_tracker.py
import numpy as np
import cv2

# iris landmark groups (MediaPipe indices)
LEFT_IRIS_IDX = [468, 469, 470, 471, 472]
RIGHT_IRIS_IDX = [473, 474, 475, 476, 477]

# rough eye socket reference landmarks (face mesh)
LEFT_EYE_SOCKET = [33, 133]   # approximate outer eye / inner eye anchor indices
RIGHT_EYE_SOCKET = [362, 263]

def iris_center_px(landmarks, frame):
    h, w = frame.shape[:2]
    # average left & right iris centers (in normalized coords from MediaPipe)
    lx = np.mean([landmarks.landmark[i].x for i in LEFT_IRIS_IDX])
    ly = np.mean([landmarks.landmark[i].y for i in LEFT_IRIS_IDX])
    rx = np.mean([landmarks.landmark[i].x for i in RIGHT_IRIS_IDX])
    ry = np.mean([landmarks.landmark[i].y for i in RIGHT_IRIS_IDX])
    return (int(lx * w), int(ly * h)), (int(rx * w), int(ry * h))

def combined_iris_norm(landmarks):
    # return normalized average iris center [0..1]
    lx = np.mean([landmarks.landmark[i].x for i in LEFT_IRIS_IDX])
    ly = np.mean([landmarks.landmark[i].y for i in LEFT_IRIS_IDX])
    rx = np.mean([landmarks.landmark[i].x for i in RIGHT_IRIS_IDX])
    ry = np.mean([landmarks.landmark[i].y for i in RIGHT_IRIS_IDX])
    return ((lx + rx) / 2.0, (ly + ry) / 2.0)

def iris_pixels(landmarks, frame):
    return iris_center_px(landmarks, frame)

def draw_iris_points(frame, landmarks, radius=2, color=(0,255,0)):
    h, w = frame.shape[:2]
    for i in LEFT_IRIS_IDX + RIGHT_IRIS_IDX:
        x = int(landmarks.landmark[i].x * w)
        y = int(landmarks.landmark[i].y * h)
        cv2.circle(frame, (x,y), radius, color, -1)

# Optional: simple head compensation helper (estimates scale)
def interocular_distance_norm(landmarks):
    # use two fixed outer eye points (normalized)
    p1 = landmarks.landmark[33]   # left outer
    p2 = landmarks.landmark[263]  # right outer
    dx = p1.x - p2.x
    dy = p1.y - p2.y
    return np.hypot(dx, dy)
