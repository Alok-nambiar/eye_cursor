# kalman_filter.py
import numpy as np

class Kalman2D:
    """
    A compact 2D constant-velocity Kalman filter for smoothing + predicting gaze points.
    State: [x, y, vx, vy]
    """
    def __init__(self, dt=1/30.0, process_var=1.0, meas_var=50.0):
        self.dt = dt
        # state vector
        self.x = np.zeros((4,1))  # x, y, vx, vy
        # state transition
        self.F = np.array([[1,0,dt,0],
                           [0,1,0,dt],
                           [0,0,1,0],
                           [0,0,0,1]], dtype=float)
        # measurement matrix (we measure x,y)
        self.H = np.array([[1,0,0,0],[0,1,0,0]], dtype=float)
        # covariance matrices
        q = process_var
        self.Q = q * np.eye(4)
        r = meas_var
        self.R = r * np.eye(2)
        self.P = np.eye(4) * 1000.0

    def predict(self):
        self.x = self.F @ self.x
        self.P = self.F @ self.P @ self.F.T + self.Q
        return float(self.x[0,0]), float(self.x[1,0])

    def update(self, meas):
        z = np.array([[meas[0]],[meas[1]]])
        S = self.H @ self.P @ self.H.T + self.R
        K = self.P @ self.H.T @ np.linalg.inv(S)
        y = z - (self.H @ self.x)
        self.x = self.x + (K @ y)
        I = np.eye(4)
        self.P = (I - K @ self.H) @ self.P
        return float(self.x[0,0]), float(self.x[1,0])
