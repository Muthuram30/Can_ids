"""
Base Model Interface for CAN IDS

Defines the common interface all ML models must implement.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, Dict, Any
import numpy as np


@dataclass
class ModelResult:
    """
    Standardized result from model prediction.
    
    Different models populate different fields:
    - Isolation Forest: anomaly_score, is_attack
    - Random Forest: prediction, confidence, is_attack
    - Hybrid: all fields
    """
    model_name: str
    is_attack: bool
    
    # Supervised model fields
    prediction: Optional[str] = None
    confidence: Optional[float] = None
    probabilities: Optional[Dict[str, float]] = None
    
    # Unsupervised model fields  
    anomaly_score: Optional[float] = None
    
    # Additional metadata
    feature_importance: Optional[Dict[str, float]] = None
    latency_ms: Optional[float] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert result to dictionary."""
        return {
            'model_name': self.model_name,
            'is_attack': self.is_attack,
            'prediction': self.prediction,
            'confidence': self.confidence,
            'probabilities': self.probabilities,
            'anomaly_score': self.anomaly_score,
            'feature_importance': self.feature_importance,
            'latency_ms': self.latency_ms
        }


class BaseCANModel(ABC):
    """
    Abstract base class for CAN intrusion detection models.
    
    All models must implement:
    - train(): Fit model on training data
    - predict(): Make prediction on new data
    - save(): Persist model to disk
    - load(): Restore model from disk
    """
    
    def __init__(self, model_name: str):
        self.model_name = model_name
        self.is_trained = False
        self.feature_names: Optional[list] = None
        self.training_metadata: Dict[str, Any] = {}
    
    @abstractmethod
    def train(
        self, 
        X_train: np.ndarray, 
        y_train: Optional[np.ndarray] = None,
        X_val: Optional[np.ndarray] = None,
        y_val: Optional[np.ndarray] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Train the model on provided data.
        
        Args:
            X_train: Training features, shape (n_samples, n_features)
            y_train: Training labels (optional for unsupervised)
            X_val: Validation features (optional)
            y_val: Validation labels (optional)
            **kwargs: Model-specific training parameters
            
        Returns:
            Dictionary with training metrics and metadata
        """
        pass
    
    @abstractmethod
    def predict(self, X: np.ndarray) -> ModelResult:
        """
        Make prediction on new data.
        
        Args:
            X: Features, shape (n_samples, n_features) or (n_features,)
            
        Returns:
            ModelResult with prediction and metadata
            
        Raises:
            RuntimeError: If model not trained
        """
        pass
    
    @abstractmethod
    def save(self, filepath: str) -> None:
        """
        Save model to disk.
        
        Args:
            filepath: Path to save model file
        """
        pass
    
    @classmethod
    @abstractmethod
    def load(cls, filepath: str) -> 'BaseCANModel':
        """
        Load model from disk.
        
        Args:
            filepath: Path to saved model file
            
        Returns:
            Loaded model instance
        """
        pass
    
    def get_model_info(self) -> Dict[str, Any]:
        """
        Get model information and metadata.
        
        Returns:
            Dictionary with model details
        """
        return {
            'model_name': self.model_name,
            'is_trained': self.is_trained,
            'feature_names': self.feature_names,
            'training_metadata': self.training_metadata
        }
    
    def validate_input(self, X: np.ndarray) -> None:
        """
        Validate input features.
        
        Args:
            X: Input features to validate
            
        Raises:
            RuntimeError: If model not trained
            ValueError: If input shape is invalid
        """
        if not self.is_trained:
            raise RuntimeError(f"{self.model_name} not trained. Call train() first.")
        
        # Handle single sample
        if X.ndim == 1:
            X = X.reshape(1, -1)
        
        expected_features = len(self.feature_names) if self.feature_names else None
        if expected_features and X.shape[1] != expected_features:
            raise ValueError(
                f"Expected {expected_features} features, got {X.shape[1]}"
            )
