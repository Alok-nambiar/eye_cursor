# cursor_control.py
import pyautogui

screen_width, screen_height = pyautogui.size()

def move_cursor_based_on_eye(frame, eye):
    """
    Moves the mouse cursor based on the position of a detected eye in the frame.

    Parameters:
    - frame: The current video frame (needed to get frame size).
    - eye: Tuple (x, y, w, h) bounding box of the detected eye.
    """
    x, y, w, h = eye
    eye_center_x = x + w // 2
    eye_center_y = y + h // 2

    frame_height, frame_width = frame.shape[:2]

    screen_x = int((eye_center_x / frame_width) * screen_width)
    screen_y = int((eye_center_y / frame_height) * screen_height)

    pyautogui.moveTo(screen_x, screen_y)
