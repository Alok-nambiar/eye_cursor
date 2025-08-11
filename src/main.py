# main.py
import cv2
from webcam_capture import open_webcam, get_frame, release_webcam
from eye_detection import detect_eyes

def main():
    try:
        cap = open_webcam()
    except Exception as e:
        print(e)
        return

    while True:
        frame = get_frame(cap)
        if frame is None:
            print("Failed to get frame from webcam")
            break

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        eyes = detect_eyes(gray)

        for (x, y, w, h) in eyes:
            cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)

        cv2.imshow("Eye Cursor - Press 'q' to quit", frame)

        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    release_webcam(cap)

if __name__ == "__main__":
    main()
