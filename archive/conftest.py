"""Root conftest.py for openGuiclaw — adds project root to sys.path."""
import sys
from pathlib import Path

# Ensure the openGuiclaw project root is importable as a package root
sys.path.insert(0, str(Path(__file__).resolve().parent))
