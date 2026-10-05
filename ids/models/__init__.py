"""
Machine Learning Models for CAN Intrusion Detection

Provides modular ML model architecture with support for:
- Isolation Forest (unsupervised anomaly detection)
- Random Forest (supervised classification)
- Model factory for easy switching
"""

from .base_model import BaseCANModel, ModelResult
from .model_factory import ModelFactory, create_model
from .isolation_forest_model import IsolationForestModel
from .random_forest_model import RandomForestModel

__all__ = [
    'BaseCANModel',
    'ModelResult',
    'ModelFactory',
    'create_model',
    'IsolationForestModel',
    'RandomForestModel',
]
