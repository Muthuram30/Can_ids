"""
Preprocessing Pipeline for CAN IDS

Handles feature scaling, normalization, and transformation.
Training and inference MUST use the same preprocessing pipeline.
"""

import pickle
from typing import List, Optional, Tuple
import numpy as np
from sklearn.preprocessing import StandardScaler


class CANPreprocessor:
    """
    Preprocessing pipeline for CAN traffic features.
    
    Wraps sklearn StandardScaler and ensures consistent transformation
    between training and inference.
    """
    
    def __init__(self):
        self.scaler = StandardScaler()
        self.is_fitted = False
        self.feature_names: Optional[List[str]] = None
        self.n_features: Optional[int] = None
    
    def fit(self, X: np.ndarray, feature_names: Optional[List[str]] = None) -> 'CANPreprocessor':
        """
        Fit the preprocessor on training data.
        
        Args:
            X: Training features, shape (n_samples, n_features)
            feature_names: Optional list of feature names for validation
            
        Returns:
            self for chaining
        """
        self.scaler.fit(X)
        self.is_fitted = True
        self.n_features = X.shape[1]
        self.feature_names = feature_names
        return self
    
    def transform(self, X: np.ndarray) -> np.ndarray:
        """
        Transform features using fitted scaler.
        
        Args:
            X: Features to transform, shape (n_samples, n_features)
            
        Returns:
            Transformed features
            
        Raises:
            RuntimeError: If preprocessor not fitted
            ValueError: If feature dimensions don't match
        """
        if not self.is_fitted:
            raise RuntimeError("Preprocessor not fitted. Call fit() first.")
        
        if X.shape[1] != self.n_features:
            raise ValueError(
                f"Feature dimension mismatch: expected {self.n_features}, "
                f"got {X.shape[1]}"
            )
        
        return self.scaler.transform(X)
    
    def fit_transform(self, X: np.ndarray, feature_names: Optional[List[str]] = None) -> np.ndarray:
        """
        Fit preprocessor and transform data in one step.
        
        Args:
            X: Training features
            feature_names: Optional list of feature names
            
        Returns:
            Transformed features
        """
        self.fit(X, feature_names)
        return self.transform(X)
    
    def inverse_transform(self, X_scaled: np.ndarray) -> np.ndarray:
        """
        Transform scaled features back to original scale.
        
        Args:
            X_scaled: Scaled features
            
        Returns:
            Original scale features
        """
        if not self.is_fitted:
            raise RuntimeError("Preprocessor not fitted.")
        return self.scaler.inverse_transform(X_scaled)
    
    def save(self, filepath: str) -> None:
        """
        Save preprocessor to disk.
        
        Args:
            filepath: Path to save file (typically .pkl or .joblib)
        """
        with open(filepath, 'wb') as f:
            pickle.dump({
                'scaler': self.scaler,
                'is_fitted': self.is_fitted,
                'feature_names': self.feature_names,
                'n_features': self.n_features
            }, f)
    
    @classmethod
    def load(cls, filepath: str) -> 'CANPreprocessor':
        """
        Load preprocessor from disk.
        
        Args:
            filepath: Path to saved preprocessor file
            
        Returns:
            Loaded preprocessor instance
        """
        with open(filepath, 'rb') as f:
            data = pickle.load(f)
        
        preprocessor = cls()
        preprocessor.scaler = data['scaler']
        preprocessor.is_fitted = data['is_fitted']
        preprocessor.feature_names = data.get('feature_names')
        preprocessor.n_features = data.get('n_features')
        return preprocessor
    
    def get_feature_statistics(self) -> dict:
        """
        Get statistics about fitted scaler.
        
        Returns:
            Dictionary with mean, std, min, max for each feature
        """
        if not self.is_fitted:
            raise RuntimeError("Preprocessor not fitted.")
        
        return {
            'mean': self.scaler.mean_.tolist(),
            'std': self.scaler.scale_.tolist(),
            'n_samples_seen': int(self.scaler.n_samples_seen_),
            'feature_names': self.feature_names
        }


def create_windows_from_frames(
    frames: List[Tuple[float, int, bytes]], 
    window_seconds: float = 2.0,
    overlap: float = 0.0
) -> List[List[Tuple[float, int, bytes]]]:
    """
    Slice a continuous frame stream into sliding windows.
    
    Args:
        frames: List of (timestamp, arbitration_id, data) tuples, sorted by time
        window_seconds: Window size in seconds
        overlap: Overlap fraction (0.0 = no overlap, 0.5 = 50% overlap)
        
    Returns:
        List of windows, each window is a list of frames
    """
    if not frames:
        return []
    
    frames = sorted(frames, key=lambda f: f[0])
    
    start_time = frames[0][0]
    end_time = frames[-1][0]
    
    step = window_seconds * (1.0 - overlap)
    
    windows = []
    window_start = start_time
    
    while window_start < end_time:
        window_end = window_start + window_seconds
        
        # Extract frames in this window
        window_frames = [
            f for f in frames 
            if window_start <= f[0] < window_end
        ]
        
        windows.append(window_frames)
        window_start += step
    
    return windows


def validate_feature_vector(features: List[float], expected_length: int = 8) -> bool:
    """
    Validate that feature vector has correct structure.
    
    Args:
        features: Feature vector to validate
        expected_length: Expected number of features
        
    Returns:
        True if valid, False otherwise
    """
    if len(features) != expected_length:
        return False
    
    if not all(isinstance(f, (int, float)) for f in features):
        return False
    
    if any(np.isnan(f) or np.isinf(f) for f in features):
        return False
    
    return True
