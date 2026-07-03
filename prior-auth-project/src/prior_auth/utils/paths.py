"""Centralized path resolution for the prior_auth package."""

from pathlib import Path

# The root of the repository (assuming src/prior_auth/utils/paths.py)
PROJECT_ROOT = Path(__file__).resolve().parents[3]

# The datasets
DATASET_ROOT = PROJECT_ROOT / "dataset"
LEGACY_DATA_ROOT = DATASET_ROOT / "legacy_full"

# Common logs
LOGS_ROOT = PROJECT_ROOT / "logs"
