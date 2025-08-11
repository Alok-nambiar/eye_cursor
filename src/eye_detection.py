# eye_detection.py
import cv2

# Load the cascade once at module load time (better performance)
eye_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_eye.xml')

def detect_eyes(gray_frame):
    """
    Detect eyes in a grayscale image frame.
    Returns a list of bounding boxes (x, y, w, h).
    """
    eyes = eye_cascade.detectMultiScale(gray_frame, scaleFactor=1.1, minNeighbors=5)
    return eyes
