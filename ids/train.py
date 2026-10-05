#!/usr/bin/env python3
"""
Training Pipeline for CAN IDS Models

Trains either Isolation Forest or Random Forest models on CAN traffic data.

Usage:
    python -m ids.train --model isolation_forest
    python -m ids.train --model random_forest --data data/labeled_traffic.csv
    python -m ids.train --model isolation_forest --sim-hours 2.0
"""

import argparse
import json
import os
import random
import sys
import time
from pathlib import Path
from typing import List, Tuple

import numpy as np

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from ids.feature_extraction import extract_features, WINDOW_SECONDS, EXPECTED_RATE_HZ
from ids.preprocessing import CANPreprocessor, create_windows_from_frames
from ids.models import create_model


def simulate_normal_traffic(duration_seconds: float) -> List[Tuple[float, int, bytes]]:
    """
    Simulate normal CAN bus traffic for training.
    
    Each known ID fires at its expected rate with realistic jitter and payload variation.
    
    Args:
        duration_seconds: Duration to simulate
        
    Returns:
        List of (timestamp, arbitration_id, data) frames
    """
    print(f"Simulating {duration_seconds/3600:.2f} hours of normal traffic...")
    
    frames = []
    
    # Create baseline payload for each ID
    baseline_payload = {
        aid: bytes(random.randint(0, 255) for _ in range(8))
        for aid in EXPECTED_RATE_HZ
    }
    
    # Generate frames for each ID at expected rate
    for aid, rate in EXPECTED_RATE_HZ.items():
        period = 1.0 / rate
        t = random.uniform(0, period)
        base = baseline_payload[aid]
        
        while t < duration_seconds:
            # Add timing jitter (±15%)
            jitter = period * random.uniform(-0.15, 0.15)
            ts = max(0.0, t + jitter)
            
            # Add small payload noise around baseline
            data = bytes(
                min(255, max(0, b + random.randint(-2, 2)))
                for b in base
            )
            
            frames.append((ts, aid, data))
            t += period
    
    frames.sort(key=lambda f: f[0])
    print(f"Generated {len(frames)} frames over {duration_seconds:.1f}s")
    
    return frames


def simulate_attack_scenarios() -> dict:
    """
    Simulate various attack patterns for testing (not training).
    
    Returns:
        Dictionary mapping attack name to frame list
    """
    scenarios = {}
    
    # Flooding attack: one ID at very high rate
    flood_frames = [
        (t * 0.002, 0x100, bytes([ord('F')] * 8))
        for t in range(int(WINDOW_SECONDS / 0.002))
    ]
    scenarios["CAN_FLOOD_0x100"] = flood_frames
    
    # Unknown ID injection
    spoof_frames = [
        (t * 0.1, 0x999, bytes([0xDE, 0xAD, 0xBE, 0xEF, 0, 0, 0, 0]))
        for t in range(int(WINDOW_SECONDS / 0.1))
    ]
    scenarios["UNKNOWN_ID_0x999"] = spoof_frames
    
    # Payload anomaly: known ID with random payload
    weird_payload = [
        (t * 0.5, 0x011, bytes(random.randint(0, 255) for _ in range(8)))
        for t in range(int(WINDOW_SECONDS / 0.5))
    ]
    scenarios["PAYLOAD_ANOMALY_0x011"] = weird_payload
    
    return scenarios


def train_isolation_forest(
    normal_hours: float = 2.0,
    output_dir: str = "models",
    contamination: float = 0.02,
    n_estimators: int = 200
):
    """Train Isolation Forest on simulated normal traffic."""
    
    print("\n" + "="*70)
    print("TRAINING ISOLATION FOREST")
    print("="*70)
    
    # Generate normal training data
    train_duration = normal_hours * 3600
    train_frames = simulate_normal_traffic(train_duration)
    
    # Create windows
    train_windows = create_windows_from_frames(train_frames, WINDOW_SECONDS)
    print(f"Created {len(train_windows)} training windows")
    
    # Extract features
    X_train = np.array([extract_features(w) for w in train_windows])
    print(f"Feature matrix shape: {X_train.shape}")
    
    # Create preprocessor
    print("\nFitting preprocessor...")
    preprocessor = CANPreprocessor()
    X_train_scaled = preprocessor.fit_transform(X_train)
    
    # Create and train model
    print("\nTraining Isolation Forest...")
    model = create_model(
        'isolation_forest',
        contamination=contamination,
        n_estimators=n_estimators,
        random_state=7
    )
    
    # Generate validation data
    val_frames = simulate_normal_traffic(120)  # 2 minutes
    val_windows = create_windows_from_frames(val_frames, WINDOW_SECONDS)
    X_val = np.array([extract_features(w) for w in val_windows])
    X_val_scaled = preprocessor.transform(X_val)
    
    metrics = model.train(X_train_scaled, X_val=X_val_scaled)
    
    # Test on attack scenarios
    print("\n" + "-"*70)
    print("SANITY CHECK: Testing on simulated attacks")
    print("-"*70)
    
    attack_scenarios = simulate_attack_scenarios()
    for attack_name, attack_frames in attack_scenarios.items():
        features = extract_features(attack_frames)
        X_attack = preprocessor.transform([features])
        result = model.predict(X_attack)
        
        status = "✓ ANOMALY" if result.is_attack else "✗ normal"
        print(f"{attack_name:30s} score={result.anomaly_score:+.3f}  -> {status}")
    
    # Save model and preprocessor
    os.makedirs(output_dir, exist_ok=True)
    model_path = os.path.join(output_dir, "isolation_forest.joblib")
    preprocessor_path = os.path.join(output_dir, "preprocessor.joblib")
    
    model.save(model_path)
    preprocessor.save(preprocessor_path)
    
    # Save metadata
    metadata = {
        'model_type': 'isolation_forest',
        'training_date': time.strftime('%Y-%m-%d %H:%M:%S'),
        'normal_hours': normal_hours,
        'n_windows': len(train_windows),
        'n_features': X_train.shape[1],
        'window_seconds': WINDOW_SECONDS,
        'contamination': contamination,
        'n_estimators': n_estimators,
        'metrics': metrics,
        'model_path': model_path,
        'preprocessor_path': preprocessor_path,
    }
    
    metadata_path = os.path.join(output_dir, "isolation_forest_metadata.json")
    with open(metadata_path, 'w') as f:
        json.dump(metadata, f, indent=2)
    
    print(f"\n✓ Model saved to: {model_path}")
    print(f"✓ Preprocessor saved to: {preprocessor_path}")
    print(f"✓ Metadata saved to: {metadata_path}")
    
    return model, preprocessor, metrics


def train_random_forest(
    data_path: str,
    output_dir: str = "models",
    n_estimators: int = 100,
    max_depth: int = 10,
    val_split: float = 0.2
):
    """
    Train Random Forest on labeled data.
    
    Args:
        data_path: Path to labeled dataset (CSV or numpy)
        output_dir: Directory to save trained model
        n_estimators: Number of trees
        max_depth: Maximum tree depth
        val_split: Validation split fraction
    """
    
    print("\n" + "="*70)
    print("TRAINING RANDOM FOREST")
    print("="*70)
    
    # TODO: Implement data loading from CSV/numpy
    # For now, use simulated data as placeholder
    print(f"WARNING: Random Forest training requires labeled data.")
    print(f"Expected format: CSV with features + label column")
    print(f"Using simulated data for demonstration...")
    
    # Simulate mixed normal + attack data
    normal_frames = simulate_normal_traffic(3600)
    normal_windows = create_windows_from_frames(normal_frames, WINDOW_SECONDS)
    X_normal = np.array([extract_features(w) for w in normal_windows])
    y_normal = np.zeros(len(X_normal))
    
    # Generate some "attack" windows (simplified)
    attack_scenarios = simulate_attack_scenarios()
    X_attack_list = []
    for attack_frames in attack_scenarios.values():
        features = extract_features(attack_frames)
        X_attack_list.append(features)
    
    X_attack = np.array(X_attack_list * 20)  # Duplicate for balance
    y_attack = np.ones(len(X_attack))
    
    # Combine
    X = np.vstack([X_normal, X_attack])
    y = np.concatenate([y_normal, y_attack])
    
    # Shuffle
    indices = np.random.permutation(len(X))
    X, y = X[indices], y[indices]
    
    # Split
    split_idx = int(len(X) * (1 - val_split))
    X_train, X_val = X[:split_idx], X[split_idx:]
    y_train, y_val = y[:split_idx], y[split_idx:]
    
    print(f"Training samples: {len(X_train)} ({(y_train==0).sum()} normal, {(y_train==1).sum()} attack)")
    print(f"Validation samples: {len(X_val)} ({(y_val==0).sum()} normal, {(y_val==1).sum()} attack)")
    
    # Preprocess
    preprocessor = CANPreprocessor()
    X_train_scaled = preprocessor.fit_transform(X_train)
    X_val_scaled = preprocessor.transform(X_val)
    
    # Train
    model = create_model(
        'random_forest',
        n_estimators=n_estimators,
        max_depth=max_depth,
        random_state=42
    )
    
    metrics = model.train(
        X_train_scaled, y_train,
        X_val_scaled, y_val,
        class_names=['NORMAL', 'ATTACK']
    )
    
    # Save
    os.makedirs(output_dir, exist_ok=True)
    model_path = os.path.join(output_dir, "random_forest.joblib")
    preprocessor_path = os.path.join(output_dir, "rf_preprocessor.joblib")
    
    model.save(model_path)
    preprocessor.save(preprocessor_path)
    
    metadata = {
        'model_type': 'random_forest',
        'training_date': time.strftime('%Y-%m-%d %H:%M:%S'),
        'n_train': len(X_train),
        'n_val': len(X_val),
        'n_features': X_train.shape[1],
        'metrics': metrics,
        'model_path': model_path,
        'preprocessor_path': preprocessor_path,
    }
    
    metadata_path = os.path.join(output_dir, "random_forest_metadata.json")
    with open(metadata_path, 'w') as f:
        json.dump(metadata, f, indent=2)
    
    print(f"\n✓ Model saved to: {model_path}")
    print(f"✓ Preprocessor saved to: {preprocessor_path}")
    print(f"✓ Metadata saved to: {metadata_path}")
    
    return model, preprocessor, metrics


def main():
    parser = argparse.ArgumentParser(description="Train CAN IDS models")
    parser.add_argument(
        '--model',
        type=str,
        required=True,
        choices=['isolation_forest', 'random_forest'],
        help='Model type to train'
    )
    parser.add_argument(
        '--output-dir',
        type=str,
        default='models',
        help='Output directory for trained models'
    )
    
    # Isolation Forest options
    parser.add_argument(
        '--sim-hours',
        type=float,
        default=2.0,
        help='Hours of normal traffic to simulate (Isolation Forest)'
    )
    parser.add_argument(
        '--contamination',
        type=float,
        default=0.02,
        help='Expected contamination ratio (Isolation Forest)'
    )
    parser.add_argument(
        '--n-estimators',
        type=int,
        default=200,
        help='Number of trees'
    )
    
    # Random Forest options
    parser.add_argument(
        '--data',
        type=str,
        help='Path to labeled dataset (Random Forest)'
    )
    parser.add_argument(
        '--max-depth',
        type=int,
        default=10,
        help='Maximum tree depth (Random Forest)'
    )
    parser.add_argument(
        '--val-split',
        type=float,
        default=0.2,
        help='Validation split fraction (Random Forest)'
    )
    
    args = parser.parse_args()
    
    if args.model == 'isolation_forest':
        train_isolation_forest(
            normal_hours=args.sim_hours,
            output_dir=args.output_dir,
            contamination=args.contamination,
            n_estimators=args.n_estimators
        )
    elif args.model == 'random_forest':
        train_random_forest(
            data_path=args.data,
            output_dir=args.output_dir,
            n_estimators=args.n_estimators,
            max_depth=args.max_depth,
            val_split=args.val_split
        )
    
    print("\n" + "="*70)
    print("TRAINING COMPLETE")
    print("="*70)


if __name__ == '__main__':
    main()
