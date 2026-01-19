# clickable_finder.py
import time
import math
import cv2
import numpy as np
import pyautogui

try:
    import win32gui
    import win32con
except Exception:
    win32gui = None
    win32con = None

def rect_center(rect):
    x1,y1,x2,y2 = rect
    return ((x1+x2)//2, (y1+y2)//2)

def screenshot_bgr():
    img = pyautogui.screenshot()
    return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)

def visual_clickable_detector(screenshot_bgr, min_area=700):
    h,w = screenshot_bgr.shape[:2]
    gray = cv2.cvtColor(screenshot_bgr, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (5,5), 0)
    thresh = cv2.adaptiveThreshold(blur,255,cv2.ADAPTIVE_THRESH_GAUSSIAN_C,cv2.THRESH_BINARY_INV,11,2)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT,(9,5))
    closed = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel, iterations=2)
    contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    results = []
    for cnt in contours:
        area = cv2.contourArea(cnt)
        if area < min_area:
            continue
        x,y,ww,hh = cv2.boundingRect(cnt)
        if ww < 28 or hh < 14:
            continue
        bbox = (x,y,x+ww,y+hh)
        cx,cy = rect_center(bbox)
        score = area / float(ww*hh + 1e-9)
        results.append({'id':f'vis_{len(results)}_{int(time.time()*1000)}','bbox':bbox,'center':(cx,cy),'score':score,'source':'vis'})
    results = sorted(results, key=lambda t: -((t['bbox'][2]-t['bbox'][0])*(t['bbox'][3]-t['bbox'][1])))
    return results

def enumerate_native_clickables():
    if win32gui is None:
        return []
    items = []
    def cb(hwnd, lParam):
        try:
            if not win32gui.IsWindowVisible(hwnd):
                return True
            rect = win32gui.GetWindowRect(hwnd)
            if not rect:
                return True
            x1,y1,x2,y2 = rect
            w = x2-x1; h = y2-y1
            if w < 24 or h < 10:
                return True
            try:
                cls = win32gui.GetClassName(hwnd)
            except:
                cls = ''
            clickable_classes = ('Button','SysLink','Edit','Chrome_WidgetWin_1','DirectUIHWND')
            if any(c.lower() in cls.lower() for c in clickable_classes) or (h>20 and w>40):
                cx,cy = rect_center(rect)
                items.append({'id':f'win_{hwnd}','bbox':rect,'center':(cx,cy),'score':1.0,'source':'win'})
        except:
            pass
        return True
    try:
        win32gui.EnumWindows(cb, None)
    except:
        pass
    return items

def collect_clickable_targets(use_native=True, use_visual=True):
    targets = []
    if use_native:
        try:
            targets.extend(enumerate_native_clickables())
        except:
            pass
    if use_visual:
        try:
            scr = screenshot_bgr()
            targets.extend(visual_clickable_detector(scr))
        except:
            pass
    # dedupe & prefer native
    merged = []
    centers = []
    for t in targets:
        c = t['center']
        dup = False
        for i,pc in enumerate(centers):
            if math.hypot(c[0]-pc[0], c[1]-pc[1]) < 28:
                dup = True
                if merged[i]['source']=='vis' and t['source']=='win':
                    merged[i] = t
                break
        if not dup:
            merged.append(t)
            centers.append(c)
    return merged
