"""
can_features.py -- shared feature extraction for the CAN IDS ML layer.

Imported by BOTH train_can_ids_model.py (offline) and app.py (live inference), so the
feature vector the model is trained on is exactly the vector it's scored on later.
Changing the feature set means re-running the trainer.

A "window" is a short slice of CAN traffic (WINDOW_SECONDS long). Features are
computed over all frames seen in that window and combine the three signal types
requested: ID-frequency/flooding, unknown/unauthorized IDs, and payload
byte-pattern anomalies -- as one feature vector per window, not three scores.
"""
import math

WINDOW_SECONDS = 2.0

# Known IDs and the rate (Hz) each is expected to arrive at on a healthy bus.
# Pulled from the project's CAN ID map / app.py. Used both to flag unknown IDs
# and to score "this known ID is arriving way faster/slower than normal".
EXPECTED_RATE_HZ = {
    0x010: 2.0,   # Pi heartbeat (every 0.5s)
    0x011: 2.0,   # Motor heartbeat
    0x013: 2.0,   # Sensor heartbeat
    0x014: 2.0,   # Security heartbeat
    0x100: 5.0,   # Motor command (keepalive resend every 0.2s while held)
    0x101: 5.0,   # Motor status
    0x120: 10.0,  # ToF distance
    0x121: 10.0,  # Ultrasonic distance
    0x122: 10.0,  # Obstacle status
    0x140: 1.0,   # Lock command (occasional)
    0x141: 1.0,   # Lock status
}
KNOWN_IDS = set(EXPECTED_RATE_HZ)

FEATURE_NAMES = [
    "frames_per_sec",          # overall bus load
    "unique_id_count",         # distinct arbitration IDs seen in the window
    "unknown_id_ratio",        # fraction of frames whose ID is not in KNOWN_IDS
    "max_rate_deviation",      # worst-case |observed - expected| / expected over known IDs
    "mean_iat",                # mean inter-arrival time between consecutive frames (any ID)
    "std_iat",                 # std dev of inter-arrival time (bursts/flooding show up here)
    "mean_payload_byte_std",   # mean, across IDs, of the std-dev of payload bytes seen for that ID
    "max_payload_byte_std",    # worst single-ID payload variability in the window
]


def extract_features(frames, window_seconds=WINDOW_SECONDS):
    """frames: list of (timestamp, arbitration_id, data_bytes) tuples, data_bytes a
    bytes-like of 0-8 bytes, covering one window. Returns a list[float] in FEATURE_NAMES
    order. Always returns a full vector, even for an empty/sparse window, so live
    inference never has to special-case "not enough data" -- an empty window just reads
    as zero load, which the model has also seen in training."""
    n = len(frames)
    if n == 0:
        return [0.0] * len(FEATURE_NAMES)

    frames = sorted(frames, key=lambda f: f[0])
    frames_per_sec = n / window_seconds

    ids_seen = {}
    for ts, aid, data in frames:
        ids_seen.setdefault(aid, []).append((ts, data))
    unique_id_count = len(ids_seen)

    unknown_frames = sum(len(v) for k, v in ids_seen.items() if k not in KNOWN_IDS)
    unknown_id_ratio = unknown_frames / n

    max_rate_deviation = 0.0
    for aid, expected in EXPECTED_RATE_HZ.items():
        observed = len(ids_seen.get(aid, [])) / window_seconds
        dev = abs(observed - expected) / expected
        max_rate_deviation = max(max_rate_deviation, dev)

    if n >= 2:
        iats = [frames[i][0] - frames[i - 1][0] for i in range(1, n)]
        mean_iat = sum(iats) / len(iats)
        var = sum((x - mean_iat) ** 2 for x in iats) / len(iats)
        std_iat = math.sqrt(var)
    else:
        mean_iat = window_seconds
        std_iat = 0.0

    byte_stds = []
    for aid, entries in ids_seen.items():
        if len(entries) < 2:
            continue
        max_len = max(len(d) for _, d in entries)
        for pos in range(max_len):
            vals = [d[pos] for _, d in entries if pos < len(d)]
            if len(vals) < 2:
                continue
            m = sum(vals) / len(vals)
            v = sum((x - m) ** 2 for x in vals) / len(vals)
            byte_stds.append(math.sqrt(v))
    mean_payload_byte_std = sum(byte_stds) / len(byte_stds) if byte_stds else 0.0
    max_payload_byte_std = max(byte_stds) if byte_stds else 0.0

    return [
        frames_per_sec, float(unique_id_count), unknown_id_ratio, max_rate_deviation,
        mean_iat, std_iat, mean_payload_byte_std, max_payload_byte_std,
    ]
