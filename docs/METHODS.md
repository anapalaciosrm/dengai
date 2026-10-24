# Methods and sources

Every layer of Dengai, the established technique behind it, and where it comes from.
Status labels: **sourced** (published evidence), **standard method** (textbook technique),
**our design choice** (reasonable but untested, so we test it with sensitivity analysis),
**placeholder** (waiting for mentor or data).

Assumption values live in `config/assumptions.csv`, which has the same status labels.

## How the pieces fit

```
drone AI detections ──> 1. study area ──> 2. enrich with GIS ──> 3. priority score
                                                                        │
              6. learn from inspections <── 5. evaluate <── 4. route teams
```

Detection is done upstream by the source team. Dengai starts from their output.

---

## 0. Upstream: where the sites come from

| What | Technique | Source | Status |
|---|---|---|---|
| Tire detection in drone images of Tallo, Makassar | Deep learning segmentation (U-Net++, DeepLabV3+), F1 0.87 and 0.82 | Hassan, Chamberlin, Tarpenning, et al., Rosser. *Remote Sensing Applications: Society and Environment* (2026). doi:10.1016/j.rsase.2026.102011. Code: github.com/Rosser-Lab/Aedes-Tire-Detection | sourced |
| Drones vs ground surveys for trash | UAV orthomosaics vs walkthroughs: 1.8 to 4.4 times more trash found, 94% of labeled sites correct, misses under vegetation | Tarpenning et al., Rosser. *Parasites and Vectors* 18 (2025) | sourced |
| Reliability of manual labels | Inter rater agreement, Fleiss kappa 0.80 (0.90 for collapsed risk groups) | Woo et al., Rosser. *Parasites and Vectors* (2026). doi:10.1186/s13071-026-07646-0 | sourced |

**Why it matters for us:** the detector outputs binary detections (tire or not), so per site
confidence may not exist. Fallback: give every detection the model's accuracy (`default_confidence`).

## 1. Study area

| What | Technique | Source | Status |
|---|---|---|---|
| Tallo sub-district boundary | Geocoding OpenStreetMap administrative boundary | OpenStreetMap via OSMnx (Boeing 2017, *Computers, Environment and Urban Systems*) | standard method |
| Health centers as team start points | OSM tags `amenity=clinic/hospital/doctors`, `healthcare=*`; names containing "puskesmas" | OpenStreetMap. In Indonesia, local health centers (puskesmas) coordinate dengue field work and community larva monitors (jumantik) | standard method; which center is a **placeholder** (ask mentor) |
| Buildings | OSM building footprints, stored as center points | OpenStreetMap | standard method |
| Walking network | OSM street and footpath graph (`network_type="walk"`) | OpenStreetMap via OSMnx | standard method |
| Coordinate system | Project to UTM zone 50S (EPSG:32750) for meters | Standard GIS practice | standard method |

## 2. GIS enrichment of each site

| Layer | Technique | Source | Status |
|---|---|---|---|
| **Exposure** | Count buildings within the buffer radius (buffer + spatial join) | Risk = hazard × exposure, the standard risk framework in public health and disaster risk | standard method; scaling 0.5 to 1.5 is **our design choice** |
| **Buffer radius 100 m** | Average Aedes aegypti flight range | Moore and Brown, *Journal of Medical Entomology* (2022), meta analysis of 38 mark release recapture studies: about 106 m | sourced |
| **Clustering** | Count other predicted sites within the buffer. Upgrade: Getis Ord Gi* hotspot statistic | The source team's own repo includes kernel density and Getis Ord Gi* hotspot maps (`spatial_analysis_tires.py`) | standard method; scaling is **our design choice** |
| **Road access** (stretch) | Distance from site to nearest walkable edge, converted to extra minutes | OSMnx nearest edge | standard method; minutes per meter is **placeholder** |

## 3. Priority score

**priority = type weight × confidence × exposure × clustering × urgency**

| Term | Meaning | Source | Status |
|---|---|---|---|
| Type weight | How productive and persistent each container type is | **Key container concept.** Tun Lin et al., *Tropical Medicine and International Health* 14(9) (2009): treating only the most productive container types was as effective as treating all, and cheaper, across 8 countries. Mwakutwaa et al., *Parasitology Research* (2023): drums, pots, and tires produced over 85% of pupae in coastal Kenya | sourced direction; exact numbers partly **our design choice** |
| Confidence | Probability a detection is real; multiplying gives the **expected value** of a visit | Probability theory; model accuracy from Hassan et al. 2026 | standard method |
| Exposure | People affected if the site breeds | See layer 2 | see above |
| Clustering | Hotspots worth a stop | See layer 2 | see above |
| Urgency | Boost after rain, because refilled containers will produce adults within days | CDC: egg to adult in 7 to 10 days | sourced biology; boost size and threshold are **our design choice** |
| Multiplying the terms | Combining factors multiplicatively | Common in multi criteria risk indices; Lima et al., *JMIR Public Health and Surveillance* (2021) built a weighted index for Aedes inspection priority | **our design choice**, tested in sensitivity analysis |

**Honest limitation:** we cannot see how long each container has held water, so urgency is
citywide (rain), and persistence is captured by type weights.

## 4. Routing teams

| What | Technique | Source | Status |
|---|---|---|---|
| Problem formulation | **Team orienteering problem**: several teams with a time limit choose which sites to visit and in what order to collect the most value | Chao, Golden, Wasil, *European Journal of Operational Research* 88(3) (1996) | standard method |
| Solver | Google OR-Tools vehicle routing with **optional visits**: skipping a site costs a penalty equal to its priority | OR-Tools guide, "Penalties and Dropping Visits" | standard method |
| Travel times | Shortest walking paths on the street network, divided by walking speed | Dijkstra shortest paths via OSMnx and NetworkX | standard method |
| Fallback travel times | Straight line distance × 1.3 detour factor | Common approximation | **our design choice** |
| Related work in vector control | Route planning for mosquito abatement (Machala, Ecuador); City Block Routing Problem for fogging (Araújo, Unicamp PhD thesis, 2026) | See `Literature Review and Prior Work` in Drive | context |

**Our contribution:** existing work routes fogging trucks or whole neighborhoods. We route
inspectors to individual drone detected sites, with detection uncertainty built in.

## 5. Evaluation

| What | Technique | Source | Status |
|---|---|---|---|
| Baseline 1 | **Greedy nearest neighbor**: always go to the closest unvisited site | Classic routing heuristic | standard method |
| Baseline 2 | **Highest priority first**: always go to the best scoring site, ignoring travel | Simple ranking strategy | standard method |
| Fair comparison | Same sites, start points, teams, hours, travel times for every method | Experimental design | standard method |
| Robustness | **Monte Carlo simulation**: treat confidence as the chance a site is real, sample 1,000 versions of reality, count real sites each plan reaches, report mean and range | Standard simulation method; error rates from Tarpenning et al. 2025 | standard method |
| Sensitivity | Rerun with weights, inspection times, and scaling changed to show conclusions hold | Standard practice for uncertain parameters | standard method |
| Compute cost | Measure energy and emissions of the optimizer | CodeCarbon library | standard method |

**What we claim and do not claim:** we report expected high priority sites reached per day,
travel time, and cost per site. We do **not** claim reductions in mosquitoes or dengue cases,
as the challenge brief requires.

## 6. Stretch: learning from inspections (Bayesian updating)

| What | Technique | Source | Status |
|---|---|---|---|
| Updating confidence after each day | **Bayesian updating with a Beta Binomial model.** Each site type (or neighborhood) starts with a prior belief about how often detections are real. Each inspection result (real or false alarm) updates it. Tomorrow's confidence values, and therefore routes, shift toward what teams actually found | Standard Bayesian statistics (Beta distribution is the conjugate prior for a success rate) | standard method; prior strength is **our design choice** |
| Exploration vs exploitation (optional) | Occasionally inspect uncertain sites to learn whether predictions in that area are reliable | Multi armed bandit idea (for example Thompson sampling) | standard method; **stretch only** |

**Why it matters:** it answers "robustness to uncertainty and changing conditions" (15% of the
score) with a system that gets better each day instead of trusting the detector forever.

## 7. Optional: plain language briefing

| What | Technique | Source | Status |
|---|---|---|---|
| Daily team briefing in Bahasa Indonesia | One LLM call per day to turn the plan into short messages per team | Brief allows LLMs if costs are controlled | **optional**; never used for routing or scoring |

## Open questions for the mentor

1. Dataset format and whether it includes confidence scores.
2. Which health center serves the study area; how many teams; hours; foot or motorbike.
3. Minutes per inspection and what happens at a site (inspect, treat, remove).
4. Relative importance of tires, containers, drains, and trash in Makassar.
5. How often sites should be revisited.
