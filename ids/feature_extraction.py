"""
Feature Extraction for CAN Bus Anomaly Detection

Extracts meaningful features from CAN traffic windows for ML-based intrusion detection.
Features combine ID-frequency/flooding detection, unknown/unauthorized IDs, and 
payload byte-pattern anomalies.

This module is shared between training (offline) and inference (live) to ensure
consistency in feature vector generation.
"""

import math
from typing import List, Tuple, Dict, Optional

# Default sliding window size (seconds)
WINDOW_SECONDS = 2.0

# Known CAN IDs and their expected message rates (Hz) on a healthy bus
# Derived from project CAN ID map and ECU firmware behavior
EXPECTED_RATE_HZ = {
    0x010: 2.0,   # Pi heartbeat (every 0.5s)
    0x011: 2.0,   # Motor ECU heartbeat
    0x013: 2.0,   # Sensor ECU heartbeat
    0x014: 2.0,   # Security ECU heartbeat
    0x100: 5.0,   # Motor command (keepalive resend every 0.2s while held)
    0x101: 5.0,   # Motor status
    0x120: 10.0,  # ToF distance sensor
    0x121: 10.0,  # Ultrasonic distance sensor
    0x122: 10.0,  # Obstacle status
    0x140: 1.0,   # Lock command (occasional)
    0x141: 1.0,   # Lock status
}

KNOWN_IDS = set(EXPECTED_RATE_HZ.keys())

# Feature vector components (order must remain consistent)
FEATURE_NAMES = [
    "frames_per_sec",          # Overall bus load
    "unique_id_count",         # Distinct arbitration IDs seen in window
    "unknown_id_ratio",        # Fraction of frames with unknown IDs
    "max_rate_deviation",      # Worst |observed - expected| / expected over known IDs
    "mean_iat",                # Mean inter-arrival time between consecutive frames
    "std_iat",                 # Std dev of inter-arrival time (bursts/flooding)
    "mean_payload_byte_std",   # Mean payload variability across IDs
    "max_payload_byte_std",    # Worst single-ID payload variability
]


def extract_features(
    frames: List[Tuple[float, int, bytes]], 
    window_seconds: float = WINDOW_SECONDS
) -> List[float]:
    """
    Extract feature vector from a CAN traffic window.
    
    Args:
        frames: List of (timestamp, arbitration_id, data_bytes) tuples
                data_bytes should be bytes-like of 0-8 bytes
                All frames should be within one window period
        window_seconds: Size of the sliding window in seconds
        
    Returns:
        List of float features in FEATURE_NAMES order
        Returns zero vector for empty windows (model handles sparse data)
    """
    n = len(frames)
    
    # Handle empty window gracefully
    if n == 0:
        return [0.0] * len(FEATURE_NAMES)
    
    # Sort by timestamp for inter-arrival time calculation
    frames = sorted(frames, key=lambda f: f[0])
    
    # Feature 1: Overall message rate
    frames_per_sec = n / window_seconds
    
    # Group frames by arbitration ID
    ids_seen: Dict[int, List[Tuple[float, bytes]]] = {}
    for ts, aid, data in frames:
        if aid not in ids_seen:
            ids_seen[aid] = []
        ids_seen[aid].append((ts, data))
    
    # Feature 2: ID diversity
    unique_id_count = len(ids_seen)
    
    # Feature 3: Unknown/unauthorized ID ratio
    unknown_frames = sum(len(v) for k, v in ids_seen.items() if k not in KNOWN_IDS)
    unknown_id_ratio = unknown_frames / n
    
    # Feature 4: Maximum rate deviation from expected behavior
    max_rate_deviation = 0.0
    for aid, expected_rate in EXPECTED_RATE_HZ.items():
        observed_count = len(ids_seen.get(aid, []))
        observed_rate = observed_count / window_seconds
        if expected_rate > 0:
            deviation = abs(observed_rate - expected_rate) / expected_rate
            max_rate_deviation = max(max_rate_deviation, deviation)
    
    # Features 5-6: Inter-arrival time statistics (temporal patterns)
    if n >= 2:
        iats = [frames[i][0] - frames[i - 1][0] for i in range(1, n)]
        mean_iat = sum(iats) / len(iats)
        variance = sum((x - mean_iat) ** 2 for x in iats) / len(iats)
        std_iat = math.sqrt(variance)
    else:
        mean_iat = window_seconds
        std_iat = 0.0
    
    # Features 7-8: Payload byte variability (data anomalies)
    byte_stds = []
    for aid, entries in ids_seen.items():
        if len(entries) < 2:
            continue
        
        # Find maximum payload length for this ID
        max_len = max(len(d) for _, d in entries)
        
        # Calculate std dev for each payload byte position
        for pos in range(max_len):
            vals = [d[pos] for _, d in entries if pos < len(d)]
            if len(vals) < 2:
                continue
            
            mean_val = sum(vals) / len(vals)
            variance = sum((x - mean_val) ** 2 for x in vals) / len(vals)
            byte_stds.append(math.sqrt(variance))
    
    mean_payload_byte_std = sum(byte_stds) / len(byte_stds) if byte_stds else 0.0
    max_payload_byte_std = max(byte_stds) if byte_stds else 0.0
    
    return [
        frames_per_sec,
        float(unique_id_count),
        unknown_id_ratio,
        max_rate_deviation,
        mean_iat,
        std_iat,
        mean_payload_byte_std,
        max_payload_byte_std,
    ]


def get_feature_names() -> List[str]:
    """Return ordered list of feature names."""
    return FEATURE_NAMES.copy()


def get_expected_rates() -> Dict[int, float]:
    """Return dictionary of expected CAN ID rates."""
    return EXPECTED_RATE_HZ.copy()


def get_known_ids() -> set:
    """Return set of known/authorized CAN IDs."""
    return KNOWN_IDS.copy()


def update_expected_rates(rates: Dict[int, float]) -> None:
    """
    Update expected CAN message rates (use carefully - affects detection).
    
    Args:
        rates: Dictionary mapping CAN ID to expected rate in Hz
    """
    global EXPECTED_RATE_HZ, KNOWN_IDS
    EXPECTED_RATE_HZ.update(rates)
    KNOWN_IDS = set(EXPECTED_RATE_HZ.keys())
