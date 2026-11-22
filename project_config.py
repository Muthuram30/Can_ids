"""Paths shared by the live controller and its compatible trainer."""
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent


def project_path(name, default):
    value = Path(os.environ.get(name, default)).expanduser()
    return str(value if value.is_absolute() else PROJECT_ROOT / value)
