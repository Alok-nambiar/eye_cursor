import cv2
import pyautogui
from webcam_capture import open_webcam, get_frame, release_webcam
from eye_detection import detect_eyes
from cursor_control import move_cursor_based_on_eye

previous_pos = None

def smooth_pos(new_pos, previous_pos, alpha=0.2):
    if previous_pos is None:
        return new_pos
    x = int(alpha * new_pos[0] + (1 - alpha) * previous_pos[0])
    y = int(alpha * new_pos[1] + (1 - alpha) * previous_pos[1])
    return (x, y)

def main():
    global previous_pos  # to modify the outer variable

    try:
        cap = open_webcam()
    except Exception as e:
        print(e)
        return

    screen_width, screen_height = pyautogui.size()

    while True:
        frame = get_frame(cap)
        if frame is None:
            print("Failed to get frame from webcam")
            break

        frame = cv2.flip(frame, 1)  # Flip horizontally for mirror effect

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        eyes = detect_eyes(gray)

        for (x, y, w, h) in eyes:
            cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)

        if len(eyes) > 0:
            (x, y, w, h) = eyes[0]
            eye_center_x = x + w // 2
            eye_center_y = y + h // 2

            frame_height, frame_width = frame.shape[:2]
            screen_x = int((eye_center_x / frame_width) * screen_width)
            screen_y = int((eye_center_y / frame_height) * screen_height)

            smoothed_pos = smooth_pos((screen_x, screen_y), previous_pos)
            previous_pos = smoothed_pos

            pyautogui.moveTo(smoothed_pos[0], smoothed_pos[1])

        cv2.imshow("Eye Cursor - Press 'q' to quit", frame)

        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    release_webcam(cap)

if __name__ == "__main__":
    main()
