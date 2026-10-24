# Dengai

Daily inspection planning for dengue vector control in Makassar, Indonesia.
Stanford Cleantech Hackathon, Track 2 (Climate and Health).

AI finds the breeding sites. Dengai plans the response: which sites each team visits, in what order, within their working hours.

Team Members: Ana Palacios, Lara Rozanski and Alied Monica Camana Ttito  

## Read first

* `docs/CHALLENGE.md`: the organizers' brief, deliverables, and scoring
* `docs/METHODS.md`: every layer, the established technique behind it, and its source
* `.github/copilot-instructions.md`: project rules (Copilot reads this automatically)

## Study area setup (run once, needs internet)

```
python engine/setup_area.py        # Tallo boundary, walking network, health centers, buildings
python engine/make_fake_sites.py   # synthetic sites inside Tallo (options: --scenario sparse|clustered|dense --n 200 --seed 42)
streamlit run app.py               # map of sites and health centers
```

Fake site files are already in `data/processed/`, so the app works even before `setup_area.py` runs.

## Pipeline

Run everything after setup with one command:

```
python run_pipeline.py
streamlit run app.py
```

0. `engine/setup_area.py` and `engine/make_fake_sites.py` prepare the study area and synthetic sites (run once)
1. `engine/load_sites.py` converts the organizers' data into `data/processed/sites.csv` (tomorrow)
2. `engine/enrich_gis.py` adds exposure (buildings within 100 m) and clustering (sites within 100 m)
3. `engine/scoring.py` computes the priority score
4. `engine/travel_matrix.py` picks the start puskesmas and computes walking minutes on Tallo's streets
5. `engine/baseline.py` plans routes with two baselines: nearest site next, highest priority next
6. `engine/optimizer.py` plans routes with OR-Tools, team orienteering problem
7. `engine/evaluate.py` compares plans and runs the Monte Carlo robustness test
8. `app.py` is the Streamlit dashboard: map, routes, and comparison table

Shared code: `engine/config.py` (paths and assumptions) and `engine/plan_tools.py` (building and measuring plans).

## Setup

```
pip install -r requirements.txt
streamlit run app.py
```

## Data rules

* `data/raw/` is never edited.
* Organizer data is not public. Keep this repo private.
* Assumptions live in `config/assumptions.csv`, exported from the shared Google Sheet.
