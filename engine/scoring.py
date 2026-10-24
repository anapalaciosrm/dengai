"""Step 4: priority score for each site.

priority = type weight × confidence × exposure × clustering × urgency

Reads  data/processed/sites_enriched.csv
Writes data/processed/sites_scored.csv with columns:
    type_weight, urgency, priority, inspect_min, high_priority

Every term and its source is explained in docs/METHODS.md, layer 3.
The way the terms are combined (multiplying) is our design choice, tested later
with a sensitivity analysis.

Run: python engine/scoring.py
"""

import sys
from pathlib import Path

import pandas as pd

sys.path.append(str(Path(__file__).resolve().parent))
import config as C  # noqa: E402


def urgency_today(cfg):
    """Citywide urgency: boost if recent rain likely refilled containers (CDC: 7 to 10 day cycle)."""
    if cfg["rain_mm_last7d"] >= cfg["rain_threshold_mm"]:
        return cfg["rain_boost"]
    return 1.0


def main():
    cfg = C.load_assumptions()
    sites = pd.read_csv(C.ENRICHED_FILE)

    # If the organizers' data has no confidence, use the detector's accuracy for every site.
    if "confidence" not in sites.columns or sites["confidence"].isna().all():
        print(f"No confidence in data; using default_confidence {cfg['default_confidence']}")
        sites["confidence"] = cfg["default_confidence"]
    sites["confidence"] = sites["confidence"].fillna(cfg["default_confidence"])

    sites["type_weight"] = [C.type_weight(cfg, t) for t in sites["site_type"]]
    sites["urgency"] = urgency_today(cfg)

    sites["priority"] = (
        sites["type_weight"]
        * sites["confidence"]
        * sites["exposure"]
        * sites["clustering"]
        * sites["urgency"]
    ).round(4)

    sites["inspect_min"] = [C.inspect_minutes(cfg, t) for t in sites["site_type"]]

    threshold = sites["priority"].quantile(cfg["high_priority_quantile"])
    sites["high_priority"] = sites["priority"] >= threshold

    sites = sites.sort_values("priority", ascending=False)
    sites.to_csv(C.SCORED_FILE, index=False)

    print(f"Scored {len(sites)} sites. Urgency today: {sites['urgency'].iloc[0]}")
    print(f"High priority threshold (top {1 - cfg['high_priority_quantile']:.0%}): {threshold:.3f}")
    print("Top 5 sites:")
    cols = ["site_id", "site_type", "confidence", "exposure", "clustering", "priority"]
    print(sites[cols].head().to_string(index=False))


if __name__ == "__main__":
    main()
