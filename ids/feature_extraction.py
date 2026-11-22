"""Experimental offline API backed by the shared live feature algorithm.

The offline bundle/policy formats remain separate from app.py. Rate overrides
belong to offline configuration and never change the live map.
"""
from can_features import (
    EXPECTED_RATE_HZ as LIVE_EXPECTED_RATE_HZ,
    FEATURE_NAMES as LIVE_FEATURE_NAMES,
    WINDOW_SECONDS,
    extract_features as shared_extract_features,
)

EXPECTED_RATE_HZ = LIVE_EXPECTED_RATE_HZ.copy()
FEATURE_NAMES = LIVE_FEATURE_NAMES.copy()
KNOWN_IDS = set(EXPECTED_RATE_HZ)


def extract_features(frames, window_seconds=WINDOW_SECONDS):
    return shared_extract_features(frames, window_seconds, expected_rates=EXPECTED_RATE_HZ)


def get_feature_names():
    return FEATURE_NAMES.copy()


def get_expected_rates():
    return EXPECTED_RATE_HZ.copy()


def get_known_ids():
    return KNOWN_IDS.copy()


def update_expected_rates(rates):
    EXPECTED_RATE_HZ.update(rates)
    KNOWN_IDS.clear()
    KNOWN_IDS.update(EXPECTED_RATE_HZ)
