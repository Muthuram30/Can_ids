#!/usr/bin/env python3
"""
Model Evaluation for CAN IDS

Evaluates trained models on test data and generates performance reports.

Usage:
    python -m ids.evaluate --model models/isolation_forest.joblib --type isolation_forest
    python -m ids.evaluate --model models/random_forest.joblib --type random_forest --test-data data/test.csv
"""

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Dict, Any

import numpy as np
from sklearn.metrics import classification_report, confusion_matrix, roc_auc_score

sys.path.insert(0, str(Path(__file__).parent.parent))

from ids.models import ModelFactory
from ids.preprocessing import CANPreprocessor


def evaluate_isolation_forest(
    model,
    preprocessor: CANPreprocessor,
    X_test: np.ndarray,
    y_test: np.ndarray
) -> Dict[str, Any]:
    """
    Evaluate Isolation Forest model.
    
    Args:
        model: Trained Isolation Forest model
        preprocessor: Fitted preprocessor
        X_test: Test features
        y_test: Test labels (0=normal, 1=attack)
        
    Returns:
        Evaluation metrics
    """
    print("Evaluating Isolation Forest...")
    
    X_test_scaled = preprocessor.transform(X_test)
    
    # Predictions
    start_time = time.time()
    predictions = []
    scores = []
    
    for i in range(len(X_test_scaled)):
        result = model.predict(X_test_scaled[i:i+1])
        predictions.append(1 if result.is_attack else 0)
        scores.append(result.anomaly_score)
    
    inference_time = time.time() - start_time
    
    predictions = np.array(predictions)
    scores = np.array(scores)
    
    # Calculate metrics
    true_positives = ((predictions == 1) & (y_test == 1)).sum()
    false_positives = ((predictions == 1) & (y_test == 0)).sum()
    true_negatives = ((predictions == 0) & (y_test == 0)).sum()
    false_negatives = ((predictions == 0) & (y_test == 1)).sum()
    
    accuracy = (true_positives + true_negatives) / len(y_test)
    precision = true_positives / (true_positives + false_positives) if (true_positives + false_positives) > 0 else 0
    recall = true_positives / (true_positives + false_negatives) if (true_positives + false_negatives) > 0 else 0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0
    
    fpr = false_positives / (false_positives + true_negatives) if (false_positives + true_negatives) > 0 else 0
    
    metrics = {
        'model_type': 'isolation_forest',
        'n_samples': len(X_test),
        'n_normal': (y_test == 0).sum(),
        'n_attack': (y_test == 1).sum(),
        'accuracy': float(accuracy),
        'precision': float(precision),
        'recall': float(recall),
        'f1_score': float(f1),
        'false_positive_rate': float(fpr),
        'true_positives': int(true_positives),
        'false_positives': int(false_positives),
        'true_negatives': int(true_negatives),
        'false_negatives': int(false_negatives),
        'avg_inference_time_ms': (inference_time / len(X_test)) * 1000,
        'score_mean': float(scores.mean()),
        'score_std': float(scores.std()),
        'confusion_matrix': [[int(true_negatives), int(false_positives)],
                           [int(false_negatives), int(true_positives)]]
    }
    
    return metrics


def evaluate_random_forest(
    model,
    preprocessor: CANPreprocessor,
    X_test: np.ndarray,
    y_test: np.ndarray,
    class_names: list = None
) -> Dict[str, Any]:
    """
    Evaluate Random Forest model.
    
    Args:
        model: Trained Random Forest model
        preprocessor: Fitted preprocessor
        X_test: Test features
        y_test: Test labels
        class_names: Optional class names
        
    Returns:
        Evaluation metrics
    """
    print("Evaluating Random Forest...")
    
    X_test_scaled = preprocessor.transform(X_test)
    
    # Predictions
    start_time = time.time()
    predictions = []
    confidences = []
    
    for i in range(len(X_test_scaled)):
        result = model.predict(X_test_scaled[i:i+1])
        # Map prediction back to numeric
        pred_value = 0 if result.prediction == "NORMAL" else 1
        predictions.append(pred_value)
        confidences.append(result.confidence)
    
    inference_time = time.time() - start_time
    
    predictions = np.array(predictions)
    confidences = np.array(confidences)
    
    # Calculate metrics
    accuracy = (predictions == y_test).mean()
    
    # Detailed report
    if class_names is None:
        class_names = ['NORMAL', 'ATTACK']
    
    report = classification_report(
        y_test, predictions,
        target_names=class_names,
        output_dict=True,
        zero_division=0
    )
    
    cm = confusion_matrix(y_test, predictions)
    
    metrics = {
        'model_type': 'random_forest',
        'n_samples': len(X_test),
        'n_classes': len(np.unique(y_test)),
        'accuracy': float(accuracy),
        'precision_macro': float(report['macro avg']['precision']),
        'recall_macro': float(report['macro avg']['recall']),
        'f1_macro': float(report['macro avg']['f1-score']),
        'precision_weighted': float(report['weighted avg']['precision']),
        'recall_weighted': float(report['weighted avg']['recall']),
        'f1_weighted': float(report['weighted avg']['f1-score']),
        'avg_inference_time_ms': (inference_time / len(X_test)) * 1000,
        'avg_confidence': float(confidences.mean()),
        'classification_report': report,
        'confusion_matrix': cm.tolist()
    }
    
    return metrics


def print_metrics(metrics: Dict[str, Any]):
    """Print evaluation metrics in readable format."""
    
    print("\n" + "="*70)
    print(f"EVALUATION RESULTS - {metrics['model_type'].upper()}")
    print("="*70)
    
    print(f"\nDataset:")
    print(f"  Samples: {metrics['n_samples']}")
    if 'n_normal' in metrics:
        print(f"  Normal: {metrics['n_normal']}")
        print(f"  Attack: {metrics['n_attack']}")
    
    print(f"\nPerformance:")
    print(f"  Accuracy:  {metrics['accuracy']:.4f}")
    print(f"  Precision: {metrics.get('precision', metrics.get('precision_weighted', 0)):.4f}")
    print(f"  Recall:    {metrics.get('recall', metrics.get('recall_weighted', 0)):.4f}")
    print(f"  F1 Score:  {metrics.get('f1_score', metrics.get('f1_weighted', 0)):.4f}")
    
    if 'false_positive_rate' in metrics:
        print(f"  FPR:       {metrics['false_positive_rate']:.4f}")
    
    print(f"\nConfusion Matrix:")
    cm = metrics['confusion_matrix']
    print(f"  TN: {cm[0][0]:5d}  FP: {cm[0][1]:5d}")
    print(f"  FN: {cm[1][0]:5d}  TP: {cm[1][1]:5d}")
    
    print(f"\nInference:")
    print(f"  Avg time: {metrics['avg_inference_time_ms']:.2f} ms/sample")
    
    print("\n" + "="*70)


def main():
    parser = argparse.ArgumentParser(description="Evaluate CAN IDS models")
    parser.add_argument(
        '--model',
        type=str,
        required=True,
        help='Path to trained model file'
    )
    parser.add_argument(
        '--preprocessor',
        type=str,
        help='Path to preprocessor file (auto-detected if omitted)'
    )
    parser.add_argument(
        '--type',
        type=str,
        required=True,
        choices=['isolation_forest', 'random_forest'],
        help='Model type'
    )
    parser.add_argument(
        '--test-data',
        type=str,
        help='Path to test data (numpy or CSV)'
    )
    parser.add_argument(
        '--output',
        type=str,
        help='Output file for metrics (JSON)'
    )
    
    args = parser.parse_args()
    
    # Load model
    print(f"Loading model from {args.model}...")
    model = ModelFactory.load_model(args.model, args.type)
    
    # Load preprocessor
    if args.preprocessor:
        preprocessor_path = args.preprocessor
    else:
        # Auto-detect
        model_dir = Path(args.model).parent
        if args.type == 'isolation_forest':
            preprocessor_path = model_dir / "preprocessor.joblib"
        else:
            preprocessor_path = model_dir / "rf_preprocessor.joblib"
    
    print(f"Loading preprocessor from {preprocessor_path}...")
    preprocessor = CANPreprocessor.load(str(preprocessor_path))
    
    # Load test data
    # For this implementation, using placeholder
    print("WARNING: Test data loading not fully implemented")
    print("Using synthetic test data for demonstration...")
    
    # TODO: Implement actual test data loading
    # For now, generate synthetic test data
    X_test = np.random.randn(100, 8)
    y_test = np.array([0] * 80 + [1] * 20)
    
    # Evaluate
    if args.type == 'isolation_forest':
        metrics = evaluate_isolation_forest(model, preprocessor, X_test, y_test)
    else:
        metrics = evaluate_random_forest(model, preprocessor, X_test, y_test)
    
    # Print results
    print_metrics(metrics)
    
    # Save if requested
    if args.output:
        with open(args.output, 'w') as f:
            json.dump(metrics, f, indent=2)
        print(f"\nMetrics saved to {args.output}")


if __name__ == '__main__':
    main()
