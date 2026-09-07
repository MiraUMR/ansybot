"""Compatibility wrapper — prefer scripts/build_character_workflows.py."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_character_workflows import main

if __name__ == "__main__":
    main()
