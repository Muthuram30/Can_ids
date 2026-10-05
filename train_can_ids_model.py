#!/usr/bin/env python3
"""
train_can_ids_model.py -- trains the Isolation Forest used by app.py's ML toggle.

Run this once (and again any time you change can_features.py or the CAN ID map):
    pip install scikit-learn numpy joblib --break-system-packages
    python3 train_can_ids_model.py

It simulates normal bus traffic matching EXPECTED_RATE_HZ in can_features.py (each
known ID arriving periodically with small jitter, small payload noise), slices it
into WINDOW_SECONDS windows, extracts the shared feature vector for each window, and
fits an Isolation Forest on those "normal" windows only (unsupervised -- it never
sees attack traffic). It also simulates a handful of attack-like windows at the end
purely to print a sanity check: those should score as anomalies without having been
trained on.

Writes can_ids_model.joblib (StandardScaler + IsolationForest + feature order) next
to this script. app.py loads that file; if it's missing, the ML toggle reports
"model not available" rather than crashing.
"""
import json
import os
import random

import joblib
import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

from can_features import EXPECTED_RATE_HZ, FEATURE_NAMES, WINDOW_SECONDS, extract_features

random.seed(7)
HERE = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.path.join(HERE, "can_ids_model.joblib")

SIM_HOURS = 2.0          # simulated normal traffic to train on
N_ANOMALY_CHECKS = 6      # just for the printed sanity check at the end


def simulate_normal(duration_s):
    """One synthetic frame stream: each known ID fires at its expected rate with
    +/-15% timing jitter and a small amount of payload noise around a per-ID baseline."""
    frames = []
    baseline_payload = {aid: bytes(random.randint(0, 255) for _ in range(8)) for aid in EXPECTED_RATE_HZ}
    for aid, rate in EXPECTED_RATE_HZ.items():
        period = 1.0 / rate
        t = random.uniform(0, period)
        base = baseline_payload[aid]
        while t < duration_s:
            jitter = period * random.uniform(-0.15, 0.15)
            ts = max(0.0, t + jitter)
            data = bytes(min(255, max(0, b + random.randint(-2, 2))) for b in base)
            frames.append((ts, aid, data))
            t += period
    frames.sort(key=lambda f: f[0])
    return frames


def windows_from_frames(frames, duration_s, window_seconds=WINDOW_SECONDS):
    out = []
    w0 = 0.0
    i = 0
    n = len(frames)
    while w0 < duration_s:
        w1 = w0 + window_seconds
        chunk = []
        while i < n and frames[i][0] < w1:
            if frames[i][0] >= w0:
                chunk.append(frames[i])
            i += 1
        out.append(chunk)
        w0 = w1
    return out


def simulate_attack_windows():
    """A few clearly-anomalous windows, used only to print a sanity check after
    training -- NOT part of the training data."""
    cases = {}

    # Flooding: one known ID firing far faster than expected.
    flood = [(t * 0.002, 0x100, bytes([ord('F')] * 8)) for t in range(int(WINDOW_SECONDS / 0.002))]
    cases["flooding (0x100 at ~500Hz)"] = flood

    # Unknown/spoofed ID injected at a plausible rate.
    spoof = [(t * 0.1, 0x999, bytes([0xDE, 0xAD, 0xBE, 0xEF, 0, 0, 0, 0])) for t in range(int(WINDOW_SECONDS / 0.1))]
    cases["unknown ID 0x999 injected"] = spoof

    # Payload anomaly: known heartbeat ID at the right rate but wildly varying payload.
    weird_payload = [(t * 0.5, 0x011, bytes(random.randint(0, 255) for _ in range(8)))
                      for t in range(int(WINDOW_SECONDS / 0.5))]
    cases["0x011 heartbeat with random payload"] = weird_payload

    return cases


def main():
    print(f"Simulating {SIM_HOURS}h of normal traffic...")
    frames = simulate_normal(SIM_HOURS * 3600)
    windows = windows_from_frames(frames, SIM_HOURS * 3600)
    X = np.array([extract_features(w) for w in windows])
    print(f"{len(windows)} training windows, feature shape {X.shape}")

    scaler = StandardScaler()
    Xs = scaler.fit_transform(X)

    model = IsolationForest(n_estimators=200, contamination=0.02, random_state=7)
    model.fit(Xs)

    joblib.dump({"scaler": scaler, "model": model, "feature_names": FEATURE_NAMES,
                 "window_seconds": WINDOW_SECONDS}, MODEL_PATH)
    print(f"Saved model to {MODEL_PATH}")

    print("\nSanity check (scores on NORMAL validation windows, should be mostly > 0):")
    val_frames = simulate_normal(120)
    val_windows = windows_from_frames(val_frames, 120)
    Xv = scaler.transform(np.array([extract_features(w) for w in val_windows]))
    scores = model.decision_function(Xv)
    print(f"  mean={scores.mean():.3f} min={scores.min():.3f} max={scores.max():.3f} "
          f"(flagged anomalous: {(model.predict(Xv) == -1).sum()}/{len(Xv)})")

    print("\nSanity check (scores on simulated ATTACK windows, should mostly be < 0):")
    for name, w in simulate_attack_windows().items():
        xf = scaler.transform([extract_features(w)])
        score = model.decision_function(xf)[0]
        label = "ANOMALY" if model.predict(xf)[0] == -1 else "normal"
        print(f"  {name:38s} score={score:+.3f}  -> {label}")


if __name__ == "__main__":
    main()
