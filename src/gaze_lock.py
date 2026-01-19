# gaze_lock.py
import time
import math
from collections import deque
from kalman_filter import Kalman2D

def dist(a,b):
    return math.hypot(a[0]-b[0], a[1]-b[1])

class GazeLockManager:
    def __init__(self,
                 snap_radius_px=140,
                 unlock_distance_px=240,
                 dwell_time=0.06,
                 velocity_threshold=180.0,
                 vel_window=6,
                 dead_zone_px=18,
                 sustained_away_time=0.20):
        self.snap_radius = snap_radius_px
        self.unlock_distance = unlock_distance_px
        self.dwell_time = dwell_time
        self.vel_thresh = velocity_threshold
        self.vel_window = vel_window
        self.dead_zone = dead_zone_px
        self.sustained_away_time = sustained_away_time

        self.targets = []
        self.locked_target = None
        self.lock_time = None

        self.gaze_history = deque(maxlen=vel_window)
        self.time_history = deque(maxlen=vel_window)

        self.candidate = None
        self.candidate_start = None
        self.away_since = None

        self.kf = Kalman2D(dt=1/30.0, process_var=0.5, meas_var=25.0)

    def update_targets(self, targets):
        self.targets = targets

    def estimate_velocity(self):
        if len(self.gaze_history) < 2:
            return 0.0
        dt = self.time_history[-1] - self.time_history[0]
        if dt <= 1e-6: return 0.0
        dx = self.gaze_history[-1][0] - self.gaze_history[0][0]
        dy = self.gaze_history[-1][1] - self.gaze_history[0][1]
        return math.hypot(dx,dy) / dt

    def push_gaze(self, gaze_px):
        now = time.time()
        self.gaze_history.append(gaze_px)
        self.time_history.append(now)

        # kalman update for internal smoothing
        self.kf.predict()
        self.kf.update(gaze_px)
        predicted = self.kf.predict()
        vel = self.estimate_velocity()

        if self.locked_target:
            tx = self.locked_target['center']
            d = dist(gaze_px, tx)

            if d <= self.dead_zone:
                self.away_since = None
                return {'state':'locked','target':self.locked_target,'cursor_pos':tx,'action':'none'}

            if d > self.unlock_distance and vel > self.vel_thresh:
                prev = self.locked_target
                self.locked_target = None
                self.away_since = None
                self.candidate = None
                return {'state':'free','target':None,'cursor_pos':gaze_px,'action':'unlock'}

            if d > self.unlock_distance:
                if self.away_since is None:
                    self.away_since = now
                elif now - self.away_since >= self.sustained_away_time:
                    prev = self.locked_target
                    self.locked_target = None
                    self.away_since = None
                    self.candidate = None
                    return {'state':'free','target':None,'cursor_pos':gaze_px,'action':'unlock_sustained'}
            else:
                self.away_since = None

            return {'state':'locked','target':self.locked_target,'cursor_pos':tx,'action':'none'}

        # find nearest
        nearest = None
        nearest_d = float('inf')
        for t in self.targets:
            d = dist(gaze_px, t['center'])
            if d < nearest_d:
                nearest = t; nearest_d = d

        if nearest is None or nearest_d > self.snap_radius:
            self.candidate = None
            self.candidate_start = None
            return {'state':'free','target':None,'cursor_pos':gaze_px,'action':'none'}

        if vel < (self.vel_thresh * 0.35):
            self.locked_target = nearest
            self.lock_time = now
            self.candidate = None
            self.candidate_start = None
            return {'state':'locked','target':self.locked_target,'cursor_pos':self.locked_target['center'],'action':'snap'}

        if self.candidate is None or self.candidate['id'] != nearest['id']:
            self.candidate = nearest
            self.candidate_start = now
            return {'state':'candidate','target':nearest,'cursor_pos':nearest['center'],'action':'candidate_started','time_left':self.dwell_time}

        if now - self.candidate_start >= self.dwell_time:
            self.locked_target = self.candidate
            self.lock_time = now
            self.candidate = None
            self.candidate_start = None
            return {'state':'locked','target':self.locked_target,'cursor_pos':self.locked_target['center'],'action':'snap'}

        return {'state':'candidate','target':nearest,'cursor_pos':nearest['center'],'action':'dwell','time_left':self.dwell_time - (now - self.candidate_start)}
