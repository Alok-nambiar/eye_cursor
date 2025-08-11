# webcam_capture.py
import cv2

def open_webcam(index=0):
    cap = cv2.VideoCapture(index)
    if not cap.isOpened():
        raise Exception("Cannot open webcam")
    return cap

def get_frame(cap):
    ret, frame = cap.read()
    if not ret:
        return None
    return frame

def release_webcam(cap):
    cap.release()
    cv2.destroyAllWindows()
