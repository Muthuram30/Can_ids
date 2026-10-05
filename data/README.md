# Data Directory

This directory stores training and test data for the CAN IDS models.

## Structure

- 
ormal/ - Normal CAN traffic samples
- ttack/ - Attack traffic samples  
- processed/ - Preprocessed feature vectors

## Data Format

Data files should be in CSV or numpy format with features matching those in
ids/feature_extraction.py.

## Generating Data

To collect real data:
```bash
python -m ids.collect_telemetry
```

To use simulated data:
```bash
python -m ids.train --model isolation_forest --sim-hours 2.0
```
