#!/usr/bin/env python3
"""Run the skill CLI directly from the source checkout."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'cli'))
from longred_skills import run, sync  # noqa: E402,F401

if __name__ == '__main__':
    run()
