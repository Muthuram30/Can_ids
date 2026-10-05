"""
Random Forest Model for CAN Intrusion Detection

Supervised classification using sklearn's RandomForestClassifier.
Requires labeled training data (normal + attack samples).
"""

import time
import joblib
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import classification_report, confusion_matrix, accuracy_score
from typing import Optional, Dict, Any, List

from .base_model import BaseCANModel, ModelResult


class RandomForestModel(BaseCANModel):
    """
    Random Forest for supervised CAN intrusion detection.
    
    Key characteristics:
    - Requires labeled training data (normal + attacks)
    - Classifies attack types (CAN_ATTACK, NETWORK_ATTACK, USB_ATTACK, etc.)
    - Provides confidence scores and feature importance
    - Good interpretability for security analysis
    """
    
    def __init__(
        self,
        n_estimators: int = 100,
        max_depth: Optional[int] = 10,
        random_state: int = 42,
        **kwargs
    ):
        """
        Initialize Random Forest classifier.
        
        Args:
            n_estimators: Number of trees in the forest
            max_depth: Maximum depth of trees (None for unlimited)
            random_state: Random seed for reproducibility
            **kwargs: Additional sklearn RandomForestClassifier parameters
        """
        super().__init__("RandomForest")
        
        self.n_estimators = n_estimators
        self.max_depth = max_depth
        self.random_state = random_state
        
        self.model = RandomForestClassifier(
            n_estimators=n_estimators,
            max_depth=max_depth,
            random_state=random_state,
            **kwargs
        )
        
        self.classes_: Optional[List[str]] = None
        self.class_mapping: Optional[Dict[int, str]] = None
    
    def train(
        self,
        X_train: np.ndarray,
        y_train: np.ndarray,
        X_val: Optional[np.ndarray] = None,
        y_val: Optional[np.ndarray] = None,
        class_names: Optional[List[str]] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Train Random Forest classifier.
        
        Args:
            X_train: Training features
            y_train: Training labels (0=normal, 1+=attacks)
            X_val: Optional validation features
            y_val: Optional validation labels
            class_names: Optional list of class names for labeling
            **kwargs: Additional parameters
            
        Returns:
            Training metrics and metadata
        """
        if y_train is None:
            raise ValueError("Random Forest requires labels (y_train)")
        
        print(f"Training {self.model_name} on {X_train.shape[0]} samples...")
        
        # Create class mapping
        unique_labels = np.unique(y_train)
        if class_names:
            self.classes_ = class_names
            self.class_mapping = {i: name for i, name in enumerate(class_names)}
        else:
            # Default class names
            self.classes_ = [f"Class_{i}" for i in unique_labels]
            self.class_mapping = {i: f"Class_{i}" for i in unique_labels}
        
        start_time = time.time()
        self.model.fit(X_train, y_train)
        training_time = time.time() - start_time
        
        self.is_trained = True
        
        # Training predictions
        train_pred = self.model.predict(X_train)
        train_proba = self.model.predict_proba(X_train)
        train_accuracy = accuracy_score(y_train, train_pred)
        
        metrics = {
            'training_time_sec': training_time,
            'n_samples': X_train.shape[0],
            'n_features': X_train.shape[1],
            'n_classes': len(unique_labels),
            'n_estimators': self.n_estimators,
            'max_depth': self.max_depth,
            'train_accuracy': float(train_accuracy),
            'classes': self.classes_,
        }
        
        # Class distribution
        for label, name in self.class_mapping.items():
            count = (y_train == label).sum()
            metrics[f'train_{name}_count'] = int(count)
        
        # Feature importance
        if self.feature_names:
            feature_importance = dict(zip(
                self.feature_names,
                self.model.feature_importances_
            ))
            metrics['feature_importance'] = feature_importance
        
        # Validation metrics if provided
        if X_val is not None and y_val is not None:
            val_pred = self.model.predict(X_val)
            val_proba = self.model.predict_proba(X_val)
            val_accuracy = accuracy_score(y_val, val_pred)
            
            # Detailed classification metrics
            report = classification_report(
                y_val, val_pred,
                target_names=self.classes_,
                output_dict=True,
                zero_division=0
            )
            
            cm = confusion_matrix(y_val, val_pred)
            
            metrics.update({
                'val_accuracy': float(val_accuracy),
                'val_classification_report': report,
                'val_confusion_matrix': cm.tolist(),
                'val_precision_macro': float(report['macro avg']['precision']),
                'val_recall_macro': float(report['macro avg']['recall']),
                'val_f1_macro': float(report['macro avg']['f1-score']),
                'val_precision_weighted': float(report['weighted avg']['precision']),
                'val_recall_weighted': float(report['weighted avg']['recall']),
                'val_f1_weighted': float(report['weighted avg']['f1-score']),
            })
        
        self.training_metadata = metrics
        
        print(f"Training complete in {training_time:.2f}s")
        print(f"  Training accuracy: {train_accuracy:.3f}")
        if 'val_accuracy' in metrics:
            print(f"  Validation accuracy: {metrics['val_accuracy']:.3f}")
            print(f"  Validation F1 (macro): {metrics['val_f1_macro']:.3f}")
        
        return metrics
    
    def predict(self, X: np.ndarray) -> ModelResult:
        """
        Predict class and confidence for input.
        
        Args:
            X: Features, shape (n_features,) or (n_samples, n_features)
            
        Returns:
            ModelResult with prediction, confidence, and probabilities
        """
        self.validate_input(X)
        
        # Handle single sample
        single_sample = (X.ndim == 1)
        if single_sample:
            X = X.reshape(1, -1)
        
        start_time = time.time()
        
        # Get prediction and probabilities
        predictions = self.model.predict(X)
        probabilities = self.model.predict_proba(X)
        
        latency_ms = (time.time() - start_time) * 1000
        
        # Return first result if single sample
        if single_sample:
            pred_class = int(predictions[0])
            pred_name = self.class_mapping.get(pred_class, f"Class_{pred_class}")
            proba = probabilities[0]
            confidence = float(proba.max())
            
            # Create probability dictionary
            prob_dict = {
                self.class_mapping.get(i, f"Class_{i}"): float(p)
                for i, p in enumerate(proba)
            }
            
            # Attack is anything non-zero class (assuming 0=NORMAL)
            is_attack = (pred_class != 0)
            
            # Feature importance if available
            feature_imp = None
            if self.feature_names:
                feature_imp = dict(zip(
                    self.feature_names,
                    [float(x) for x in self.model.feature_importances_]
                ))
            
            return ModelResult(
                model_name=self.model_name,
                is_attack=is_attack,
                prediction=pred_name,
                confidence=confidence,
                probabilities=prob_dict,
                feature_importance=feature_imp,
                latency_ms=latency_ms
            )
        else:
            # Batch prediction - return first result
            pred_class = int(predictions[0])
            pred_name = self.class_mapping.get(pred_class, f"Class_{pred_class}")
            proba = probabilities[0]
            confidence = float(proba.max())
            
            prob_dict = {
                self.class_mapping.get(i, f"Class_{i}"): float(p)
                for i, p in enumerate(proba)
            }
            
            is_attack = (pred_class != 0)
            
            return ModelResult(
                model_name=self.model_name,
                is_attack=is_attack,
                prediction=pred_name,
                confidence=confidence,
                probabilities=prob_dict,
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
            'n_estimators': self.n_estimators,
            'max_depth': self.max_depth,
            'classes_': self.classes_,
            'class_mapping': self.class_mapping,
            'training_metadata': self.training_metadata,
        }
        
        joblib.dump(model_data, filepath)
        print(f"Model saved to {filepath}")
    
    @classmethod
    def load(cls, filepath: str) -> 'RandomForestModel':
        """
        Load model from disk.
        
        Args:
            filepath: Path to saved model file
            
        Returns:
            Loaded RandomForestModel instance
        """
        model_data = joblib.load(filepath)
        
        instance = cls(
            n_estimators=model_data['n_estimators'],
            max_depth=model_data.get('max_depth')
        )
        
        instance.model = model_data['model']
        instance.is_trained = model_data['is_trained']
        instance.feature_names = model_data.get('feature_names')
        instance.classes_ = model_data.get('classes_')
        instance.class_mapping = model_data.get('class_mapping')
        instance.training_metadata = model_data.get('training_metadata', {})
        
        print(f"Model loaded from {filepath}")
        return instance
    
    def get_feature_importance(self) -> Optional[Dict[str, float]]:
        """
        Get feature importance scores.
        
        Returns:
            Dictionary mapping feature names to importance scores
        """
        if not self.is_trained or not self.feature_names:
            return None
        
        return dict(zip(
            self.feature_names,
            [float(x) for x in self.model.feature_importances_]
        ))
