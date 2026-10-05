"""
Model Factory for CAN IDS

Provides unified interface for creating and loading different ML models.
"""

from typing import Optional, Dict, Any
from .base_model import BaseCANModel
from .isolation_forest_model import IsolationForestModel
from .random_forest_model import RandomForestModel


class ModelFactory:
    """
    Factory for creating CAN IDS models.
    
    Supports dynamic model selection and loading.
    """
    
    # Registry of available models
    _models = {
        'isolation_forest': IsolationForestModel,
        'random_forest': RandomForestModel,
    }
    
    @classmethod
    def create_model(
        cls,
        model_type: str,
        **kwargs
    ) -> BaseCANModel:
        """
        Create a new model instance.
        
        Args:
            model_type: Type of model ('isolation_forest', 'random_forest')
            **kwargs: Model-specific initialization parameters
            
        Returns:
            Initialized model instance
            
        Raises:
            ValueError: If model_type is unknown
        """
        model_type = model_type.lower()
        
        if model_type not in cls._models:
            available = ', '.join(cls._models.keys())
            raise ValueError(
                f"Unknown model type '{model_type}'. "
                f"Available: {available}"
            )
        
        model_class = cls._models[model_type]
        return model_class(**kwargs)
    
    @classmethod
    def load_model(cls, filepath: str, model_type: Optional[str] = None) -> BaseCANModel:
        """
        Load a model from disk.
        
        Args:
            filepath: Path to saved model file
            model_type: Optional model type hint (auto-detected if omitted)
            
        Returns:
            Loaded model instance
            
        Raises:
            ValueError: If model_type is unknown or can't be detected
        """
        if model_type is None:
            # Try to detect from filename
            filepath_lower = filepath.lower()
            if 'isolation' in filepath_lower or 'if_' in filepath_lower:
                model_type = 'isolation_forest'
            elif 'random' in filepath_lower or 'rf_' in filepath_lower:
                model_type = 'random_forest'
            else:
                # Try loading with joblib and checking metadata
                import joblib
                try:
                    data = joblib.load(filepath)
                    if 'model_name' in data:
                        name = data['model_name'].lower()
                        if 'isolation' in name:
                            model_type = 'isolation_forest'
                        elif 'random' in name:
                            model_type = 'random_forest'
                except Exception:
                    pass
        
        if model_type is None:
            raise ValueError(
                "Could not detect model type. Please specify model_type parameter."
            )
        
        model_type = model_type.lower()
        
        if model_type not in cls._models:
            available = ', '.join(cls._models.keys())
            raise ValueError(
                f"Unknown model type '{model_type}'. "
                f"Available: {available}"
            )
        
        model_class = cls._models[model_type]
        return model_class.load(filepath)
    
    @classmethod
    def list_models(cls) -> list:
        """
        List available model types.
        
        Returns:
            List of model type names
        """
        return list(cls._models.keys())
    
    @classmethod
    def register_model(cls, name: str, model_class: type) -> None:
        """
        Register a custom model type.
        
        Args:
            name: Model type name
            model_class: Model class (must inherit from BaseCANModel)
        """
        if not issubclass(model_class, BaseCANModel):
            raise TypeError("Model class must inherit from BaseCANModel")
        
        cls._models[name.lower()] = model_class


def create_model(model_type: str, **kwargs) -> BaseCANModel:
    """
    Convenience function to create a model.
    
    Args:
        model_type: Type of model to create
        **kwargs: Model-specific parameters
        
    Returns:
        Initialized model instance
    """
    return ModelFactory.create_model(model_type, **kwargs)


def load_model(filepath: str, model_type: Optional[str] = None) -> BaseCANModel:
    """
    Convenience function to load a model.
    
    Args:
        filepath: Path to saved model
        model_type: Optional model type hint
        
    Returns:
        Loaded model instance
    """
    return ModelFactory.load_model(filepath, model_type)
