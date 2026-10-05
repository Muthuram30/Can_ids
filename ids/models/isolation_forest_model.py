"""
Isolation Forest Model for CAN Anomaly Detection

Unsupervised anomaly detection using sklearn's IsolationForest.
Trained on normal traffic only - does not require labeled attack data.
"""

import time
import joblib
import numpy as np
from sklearn.ensemble import IsolationForest
from typing import Optional, Dict, Any

from .base_model import BaseCANModel, ModelResult


class IsolationForestModel(BaseCANModel):
    """
    Isolation Forest for unsupervised CAN anomaly detection.
    
    Key characteristics:
    - Trained only on normal traffic (unsupervised)
    - Returns anomaly score (negative = anomalous, positive = normal)
    - Suitable for detecting novel/unknown attacks
    - Fast inference suitable for Raspberry Pi
    """
    
    def __init__(
        self,
        contamination: float = 0.02,
        n_estimators: int = 200,
        random_state: int = 7,
        **kwargs
    ):
        """
        Initialize Isolation Forest model.
        
        Args:
            contamination: Expected proportion of anomalies (0.0-0.5)
            n_estimators: Number of trees in the forest
            random_state: Random seed for reproducibility
            **kwargs: Additional sklearn IsolationForest parameters
        """
        super().__init__("IsolationForest")
        
        self.contamination = contamination
        self.n_estimators = n_estimators
        self.random_state = random_state
        
        self.model = IsolationForest(
            n_estimators=n_estimators,
            contamination=contamination,
            random_state=random_state,
            **kwargs
        )
        
        self.threshold = 0.0  # Default: negative scores are anomalies
    
    def train(
        self,
        X_train: np.ndarray,
        y_train: Optional[np.ndarray] = None,
        X_val: Optional[np.ndarray] = None,
        y_val: Optional[np.ndarray] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Train Isolation Forest on normal traffic.
        
        Args:
            X_train: Training features (normal traffic only recommended)
            y_train: Not used (unsupervised), but accepted for interface consistency
            X_val: Optional validation data for performance measurement
            y_val: Optional validation labels for performance measurement
            **kwargs: Additional parameters (threshold override, etc.)
            
        Returns:
            Training metrics and metadata
        """
        print(f"Training {self.model_name} on {X_train.shape[0]} samples...")
        
        start_time = time.time()
        self.model.fit(X_train)
        training_time = time.time() - start_time
        
        self.is_trained = True
        
        # Calculate training statistics
        train_scores = self.model.decision_function(X_train)
        train_predictions = self.model.predict(X_train)
        
        metrics = {
            'training_time_sec': training_time,
            'n_samples': X_train.shape[0],
            'n_features': X_train.shape[1],
            'contamination': self.contamination,
            'n_estimators': self.n_estimators,
            'train_score_mean': float(train_scores.mean()),
            'train_score_std': float(train_scores.std()),
            'train_score_min': float(train_scores.min()),
            'train_score_max': float(train_scores.max()),
            'train_anomaly_count': int((train_predictions == -1).sum()),
            'train_anomaly_ratio': float((train_predictions == -1).mean()),
        }
        
        # Validation metrics if provided
        if X_val is not None:
            val_scores = self.model.decision_function(X_val)
            val_predictions = self.model.predict(X_val)
            
            metrics.update({
                'val_score_mean': float(val_scores.mean()),
                'val_score_std': float(val_scores.std()),
                'val_anomaly_count': int((val_predictions == -1).sum()),
                'val_anomaly_ratio': float((val_predictions == -1).mean()),
            })
            
            # If validation labels provided, compute accuracy metrics
            if y_val is not None:
                # Assume y_val: 0=normal, 1=attack
                val_is_attack = (val_predictions == -1)
                val_true_attack = (y_val == 1)
                
                true_positives = ((val_is_attack) & (val_true_attack)).sum()
                false_positives = ((val_is_attack) & (~val_true_attack)).sum()
                true_negatives = ((~val_is_attack) & (~val_true_attack)).sum()
                false_negatives = ((~val_is_attack) & (val_true_attack)).sum()
                
                precision = true_positives / (true_positives + false_positives) if (true_positives + false_positives) > 0 else 0
                recall = true_positives / (true_positives + false_negatives) if (true_positives + false_negatives) > 0 else 0
                f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0
                
                metrics.update({
                    'val_precision': float(precision),
                    'val_recall': float(recall),
                    'val_f1': float(f1),
                    'val_true_positives': int(true_positives),
                    'val_false_positives': int(false_positives),
                    'val_true_negatives': int(true_negatives),
                    'val_false_negatives': int(false_negatives),
                })
        
        # Allow threshold override
        if 'threshold' in kwargs:
            self.threshold = kwargs['threshold']
            metrics['custom_threshold'] = self.threshold
        
        self.training_metadata = metrics
        
        print(f"Training complete in {training_time:.2f}s")
        print(f"  Training score: mean={metrics['train_score_mean']:.3f}, "
              f"std={metrics['train_score_std']:.3f}")
        print(f"  Anomalies flagged in training: {metrics['train_anomaly_ratio']:.1%}")
        
        return metrics
    
    def predict(self, X: np.ndarray) -> ModelResult:
        """
        Predict whether input is normal or anomalous.
        
        Args:
            X: Features, shape (n_features,) or (n_samples, n_features)
            
        Returns:
            ModelResult with anomaly score and detection flag
        """
        self.validate_input(X)
        
        # Handle single sample
        single_sample = (X.ndim == 1)
        if single_sample:
            X = X.reshape(1, -1)
        
        start_time = time.time()
        
        # Get anomaly score (positive=normal, negative=anomalous)
        scores = self.model.decision_function(X)
        predictions = self.model.predict(X)
        
        latency_ms = (time.time() - start_time) * 1000
        
        # Return first result if single sample
        if single_sample:
            score = float(scores[0])
            is_anomaly = (predictions[0] == -1)
            
            return ModelResult(
                model_name=self.model_name,
                is_attack=is_anomaly,
                anomaly_score=score,
                latency_ms=latency_ms
            )
        else:
            # Batch prediction - return results for first sample only
            # (in practice, live inference typically uses single samples)
            score = float(scores[0])
            is_anomaly = (predictions[0] == -1)
            
            return ModelResult(
                model_name=self.model_name,
                is_attack=is_anomaly,
                anomaly_score=score,
                latency_ms=latency_ms
            )
    
    def save(self, filepath: str) -> None:
        """
        Save model to disk.
        
        Args:
            filepath: Path to save model (typically .joblib extension)
        """
        if not self.is_trained:
            raise RuntimeError("Cannot save untrained model")
        
        model_data = {
            'model': self.model,
            'model_name': self.model_name,
            'is_trained': self.is_trained,
            'feature_names': self.feature_names,
            'contamination': self.contamination,
            'n_estimators': self.n_estimators,
            'threshold': self.threshold,
            'training_metadata': self.training_metadata,
        }
        
        joblib.dump(model_data, filepath)
        print(f"Model saved to {filepath}")
    
    @classmethod
    def load(cls, filepath: str) -> 'IsolationForestModel':
        """
        Load model from disk.
        
        Args:
            filepath: Path to saved model file
            
        Returns:
            Loaded IsolationForestModel instance
        """
        model_data = joblib.load(filepath)
        
        instance = cls(
            contamination=model_data['contamination'],
            n_estimators=model_data['n_estimators']
        )
        
        instance.model = model_data['model']
        instance.is_trained = model_data['is_trained']
        instance.feature_names = model_data.get('feature_names')
        instance.threshold = model_data.get('threshold', 0.0)
        instance.training_metadata = model_data.get('training_metadata', {})
        
        print(f"Model loaded from {filepath}")
        return instance
    
    def get_feature_importance(self) -> Optional[Dict[str, float]]:
        """
        Isolation Forest doesn't provide direct feature importance.
        Could implement permutation importance if needed.
        """
        return None
