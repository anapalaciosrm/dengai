# Dengai

Daily inspection routes for dengue vector control in Makassar, Indonesia.
Stanford Cleantech Hackathon 2026, Track 2: Climate and Health.

Drones and AI can already find likely mosquito breeding sites, such as discarded tires, across a city.
Dengai answers the next question for a local health center (puskesmas): with the staff, vehicles,
hours and budget it has today, which sites should each team inspect, and in what order?

Team: Ana Palacios, Lara Rozanski, Alied Monica Camana Ttito.

## Results (synthetic sites in Tallo, 4 walking teams, 6 hours)

| Plan | High priority sites reached | Total priority reached | Cost per day | Cost per high priority site |
|---|---|---|---|---|
| Nearest site next | 19 of 50 | 34.9 | US$41.13 | US$2.16 |
| Highest priority next | 34 of 50 | 39.0 | US$40.38 | US$1.19 |
| **Dengai** | **43 of 50** | **54.8** | **US$41.24** | **US$0.96** |

* **Robustness:** in 1,000 simulated realities where each detection is real or false according to its
  confidence, Dengai beat both baselines every time, including when the detector is 25% less accurate
  than it claims.
* **Sensitivity:** changing teams (2 to 6), hours (4 to 8), inspection time (×0.5 to ×1.5) or site
  weights one at a time, Dengai won 9 of 9 cases, with gains from +26% to +58%.
* **Cost:** almost all of the cost is field labor. The software is free and open source, runs offline
  on one laptop, and makes no paid API or language model calls.

These numbers measure inspection value of predicted sites, not mosquitoes or dengue cases prevented.

## Why the data is synthetic

The challenge brief offered a curated dataset of detections "subject to final data-sharing approval",
with synthetic data as the fallback. The Rosser lab's real Tallo detections were not released during the
hackathon, and the challenge lead confirmed that generated detections were acceptable and that judging
focuses on the approach rather than on fidelity to Makassar data.

So everything real about the place is real, and only the detections are simulated:

* **Real:** the Tallo sub-district boundary, its streets and footpaths, building footprints, and
  puskesmas locations, all from OpenStreetMap. Travel times are walked on the real street network.
* **Simulated:** 200 detected sites (`engine/make_fake_sites.py`), placed to match what the published
  studies report. Sites sit next to real buildings, most come in clusters (the source team found tire
  hotspots), tires are the most common type, and detection confidence centers on the published
  tire detector's F1 score of 0.87 (Hassan et al. 2026).
* **Never used for planning:** each synthetic site also has an `is_real` flag drawn from its confidence.
  It exists only to score plans in the robustness test; the planner never sees it.

Swapping in real detections takes one command, and nothing else changes:

```
python engine/load_sites.py data/raw/<detections file>
python run_pipeline.py
```

The loader reads CSV, Excel, GeoJSON, shapefiles, GeoPackage or KML, points or polygons (such as tire
outlines from a segmentation model), English or Indonesian column names, and merges detections closer
than 10 m into one site.

## How it works

1. **Score each site:** priority = site type × detection confidence × people nearby × clustering × recent rain.
   People nearby and clustering count buildings and other sites within 100 m, about how far
   *Aedes aegypti* flies.
2. **Plan the routes:** a team orienteering problem solved with Google OR-Tools. Every site is optional;
   teams collect the most priority they can within their hours and budget, starting and ending at
   their own puskesmas, on real street travel times.
3. **Test the plan:** compare with two simpler strategies, then run the Monte Carlo robustness test and
   one at a time sensitivity analysis.
4. **Send and learn:** each team gets its stops and Google Maps links by WhatsApp, and a short phone form
   for the end of the day. Reports measure how often each detection type was real and how long sites
   really take, and missed sites move to the front of the next day's plan.

Full methods, equations and sources: [`docs/METHODS.md`](docs/METHODS.md).
The organizers' brief: [`docs/CHALLENGE.md`](docs/CHALLENGE.md).

## Run it

```
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python run_pipeline.py             # about 3 minutes
streamlit run app.py
```

The study area files are already in `data/raw/`. To download them again (needs internet):
`python engine/setup_area.py`. To make a different synthetic layout:
`python engine/make_fake_sites.py --scenario sparse|clustered|dense --n 200 --seed 42`.

### Opening team report forms on a phone

A phone cannot open `localhost`. Either use the Network URL Streamlit prints (same Wi-Fi), or open a
free tunnel in a second terminal:

```
cloudflared tunnel --url http://localhost:8501
```

Paste the `https://...trycloudflare.com` address it prints into **Address teams' phones open for reports**
in the app. Team messages and report links then use that address.

## Repository

| Path | What it does |
|---|---|
| `app.py` | Streamlit app: daily plan and map, team messages, comparisons, end of day reports |
| `run_pipeline.py` | Runs every engine step in order |
| `config/assumptions.csv` | Every number the model uses, with its unit, status and source |
| `engine/setup_area.py` | Downloads the Tallo boundary, walking network, buildings and health centers |
| `engine/make_fake_sites.py` | Generates synthetic detections inside Tallo |
| `engine/load_sites.py` | Converts real detection files into `data/processed/sites.csv` |
| `engine/enrich_gis.py` | People nearby, clustering and access for each site |
| `engine/scoring.py` | Priority score |
| `engine/travel_matrix.py` | Walking minutes between all sites and start points |
| `engine/teams.py` | Forms teams from each puskesmas's staff, volunteers and vehicles |
| `engine/baseline.py` | Nearest site next and highest priority next |
| `engine/optimizer.py` | Team orienteering with OR-Tools |
| `engine/plan_day.py` | Plans one day for every method and computes costs |
| `engine/cost.py` | Labor, fuel and larvicide costs |
| `engine/route_paths.py`, `engine/navigation.py` | Street paths for the map, Google Maps links and WhatsApp messages |
| `engine/reports.py` | End of day field reports and carry over to the next day |
| `engine/evaluate.py` | Monte Carlo robustness and sensitivity analysis |
| `engine/scenarios.py` | What if scenarios: fewer staff, motorbikes, tight budget, two puskesmas, scale up |

Generated files go to `outputs/` and are not tracked in git.

## Assumptions and limits

* Team sizes, hours, minutes per inspection and site type weights are estimates, marked as such in
  `config/assumptions.csv`. The sensitivity analysis shows the conclusion holds across their plausible range.
* Prices are sourced: Makassar 2026 minimum wage (Rp23,980 per hour), Pertalite fuel, bulk temephos
  larvicide, and Rp17,900 per US dollar.
* The next step is a pilot with one puskesmas for a few weeks, using the field reports to measure real
  detection accuracy by site type and real inspection times.

## Acknowledgements

Challenge by Joelle Rosser MD and Matthew Leipzig (Stanford). Site detection research by the Rosser lab
(Hassan et al. 2026; Tarpenning et al. 2025). Map data © OpenStreetMap contributors.
