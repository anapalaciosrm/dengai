"""Run every engine step in order. Run from the repo folder: python run_pipeline.py

Steps that need internet (engine/setup_area.py) are not included; run that once by hand.
"""

import subprocess
from pathlib import Path
import sys

STEPS = [
    "engine/enrich_gis.py",
    "engine/scoring.py",
    "engine/travel_matrix.py",
    "engine/baseline.py",
    "engine/optimizer.py",
    "engine/route_paths.py",
    "engine/evaluate.py",
]

# A new pipeline run plans with assumptions.csv, so forget the app's last custom settings.
Path("outputs/plan_settings.json").unlink(missing_ok=True)

for step in STEPS:
    print(f"\n=== {step} ===")
    result = subprocess.run([sys.executable, step])
    if result.returncode != 0:
        print(f"\nStopped: {step} failed. Read the error above.")
        sys.exit(result.returncode)

print("\nAll steps done. Next: streamlit run app.py")
