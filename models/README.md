# Models Directory

This directory stores trained ML models and preprocessors.

## Generated Files

After training, you'll find:

### Isolation Forest
- isolation_forest.joblib - Trained model
- preprocessor.joblib - Feature preprocessor
- isolation_forest_metadata.json - Training metadata

### Random Forest
- andom_forest.joblib - Trained model
- f_preprocessor.joblib - Feature preprocessor
- andom_forest_metadata.json - Training metadata

## Training

Train models using:
```bash
python -m ids.train --model isolation_forest
python -m ids.train --model random_forest
```

## Model Files

⚠️ **Model files are not tracked in git** (.gitignore)

Each deployment must train models or copy from secure storage.
