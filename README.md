# DACRO — Decentralized Autonomous Crisis Resource Orchestrator

A multi-agent backend system for real-time resource negotiation during natural disasters. Agents representing hospitals, NDRF, fire, police, and power utilities bid for scarce resources using the Contract Net Protocol, with a fairness monitor ensuring equitable allocation and an LLM generating human-readable explanations for every decision.

Built as a 14-hour hackathon project.

---

## What it does

When an earthquake hits, DACRO:

1. **Senses** the event and computes severity for all 12 city zones using haversine distance from the epicenter
2. **Classifies** each zone (CRITICAL / HIGH / LOW / SAFE) using a rule-based weighted scorer + a RandomForest cross-check trained on synthetic earthquake damage patterns
3. **Triggers** affected agents — hospital issues power RFPs, NDRF deploys units, fire dispatches to critical zones
4. **Negotiates** resources via the Contract Net Protocol: agents bid, bids are scored on urgency + availability + fairness, the policy agent penalises hoarders if the Gini coefficient is too high, and the best bid wins
5. **Explains** every decision: an XAI agent calls Gemini (Claude fallback) to generate a RATIONALE + COUNTERFACTUAL in plain English
6. **Persists** every negotiation cycle to SQLite and broadcasts all events to connected WebSocket clients in real time

---

## Stack

| Layer | Technology |
|---|---|
| API | FastAPI + Uvicorn |
| Messaging | Redis Pub/Sub (asyncio.Queue fallback if Redis is down) |
| Agents | Pure Python state machines — no LangGraph, no LangChain |
| City graph | NetworkX DiGraph (12 zones, Bangalore-inspired) |
| Zone ML | scikit-learn RandomForestClassifier |
| LLM | Gemini 2.0 Flash (primary) → Claude Sonnet (fallback) |
| Persistence | SQLite via `decisions.db` |
| Real-time | WebSocket (`/ws`) |

---

## Project structure

```
dacro/
├── config.py                  # All constants — thresholds, API keys, zone seeds
├── main.py                    # FastAPI app, lifespan startup/shutdown
├── agents/
│   ├── base_agent.py          # Abstract base: process_event, evaluate_rfp, get_state
│   ├── sensing_agent.py       # Earthquake ingestion → zone classify → trigger RFPs
│   ├── power_agent.py         # Power grid management, LIFE SAFETY OVERRIDE for hospitals
│   ├── hospital_agent.py      # Patient load tracking, auto power + personnel RFPs
│   ├── fire_agent.py          # Fire suppression dispatch
│   ├── police_agent.py        # Crowd control and zone access
│   ├── ndrf_agent.py          # Heavy rescue, aerial units
│   ├── rescue_coordinator.py  # AERIAL vs LAND routing via NetworkX
│   ├── policy_agent.py        # Gini monitor, bid score adjustment
│   └── xai_agent.py           # LLM explanation generator
├── negotiation/
│   ├── protocol.py            # Contract Net Protocol message factory (pure, no side effects)
│   ├── scoring.py             # Composite bid scorer: urgency × availability × fairness
│   └── orchestrator.py        # Runs full 12-step CNP cycle per RFP
├── simulation/
│   ├── city_model.py          # NetworkX city graph, road damage, power status
│   ├── earthquake.py          # Event generator, haversine severity, damage application
│   └── zone_classifier.py     # Rule-based + RandomForest zone priority classifier
├── intelligence/
│   ├── llm_client.py          # Gemini → Claude → templated fallback
│   └── fairness.py            # Gini coefficient, allocation summary
├── messaging/
│   ├── broker.py              # Redis Pub/Sub with asyncio.Queue fallback
│   └── message_types.py       # All typed dataclasses — no raw dicts in the system
├── persistence/
│   └── decision_log.py        # SQLite: log, query, and patch decisions
└── api/
    ├── routes.py              # REST endpoints
    └── websocket.py           # WebSocketManager, broadcast to all clients
```

---

## Setup

**Prerequisites:** Python 3.11+, Redis running locally

```bash
# Clone and enter
cd ResoNet

# Create virtualenv
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env — add your GEMINI_API_KEY (and ANTHROPIC_API_KEY if you want the Claude fallback)
```

`.env` keys:

| Key | Required | Notes |
|---|---|---|
| `GEMINI_API_KEY` | Yes (for live XAI) | Free tier works; falls back to template if quota exhausted |
| `ANTHROPIC_API_KEY` | No | Only used if Gemini fails or `USE_CLAUDE=true` |
| `USE_CLAUDE` | No | Set `true` to skip Gemini entirely |
| `REDIS_URL` | No | Defaults to `redis://localhost:6379` |

---

## Running

```bash
# Start Redis (if not already running)
redis-server

# Start DACRO
python main.py
```

Server starts on `http://0.0.0.0:8000`. Startup log should show:

```
DACRO system initialised — 9 agents online
```

---

## API reference

### Health and state

```bash
# Is the system up? How many agents? Is Redis connected?
GET /health

# Full snapshot: all agent states, all zone statuses, last 10 decisions
GET /state

# Zone graph (nodes + edges with travel times)
GET /zones

# Decision history from SQLite
GET /decisions?limit=20
```

### Simulation triggers

```bash
# Trigger the pre-seeded demo scenario (Zone-D epicenter, M7.2)
POST /simulate/scenario/hospital-earthquake

# Trigger a custom earthquake
POST /simulate/earthquake
Content-Type: application/json
{"lat": 12.97, "lon": 77.59, "magnitude": 6.5}

# Adjust an agent's priority weight at runtime
POST /agents/hospital_agent/priority
Content-Type: application/json
{"weight": 2.5}
```

### WebSocket

```
ws://localhost:8000/ws
```

All events are JSON with shape `{"event_type": "...", "payload": {...}, "timestamp": "..."}`.

| `event_type` | When it fires | Key payload fields |
|---|---|---|
| `zone_update` | After earthquake damage is computed | `zone_id`, `severity_score`, `classification`, `road_blocked`, `power_status` |
| `negotiation` | After each CNP cycle completes | `requester`, `winner`, `resource_type`, `amount_awarded`, `gini_before`, `gini_after` |
| `xai` | After LLM generates explanation (~1–3s lag) | `decision_id`, `rationale`, `counterfactual` |
| `agent_state` | After resource transfers | `agent_id`, `resource_pool`, `status`, `current_load` |
| `dispatch` | After rescue coordinator assigns units | `assignments` per zone with `mode` (AERIAL/LAND), `eta_minutes` |

---

## Demo walkthrough — what to expect

Run the demo scenario:

```bash
curl -X POST http://localhost:8000/simulate/scenario/hospital-earthquake
```

**What happens (in order):**

1. M7.2 quake generates at Zone-D (Peenya). All zones within ~8 km get severity > 0.6 — roads blocked, power cut.
2. Zone classifications: Zone-A, B, F → CRITICAL (high population + critical infra). Most others → HIGH.
3. Hospital agent (Zone-B) detects no power → issues power RFP with urgency=1.0.
4. NDRF deploys to Zone-A, issues one power RFP for equipment.
5. Fire agent dispatches to CRITICAL zones.
6. Power agent bids on both RFPs. It wins both — hospital gets 50 units, NDRF gets 30.
7. If patient load spikes > 80%, hospital also issues a personnel RFP.
8. Gini coefficient is computed before and after each award.
9. XAI agent fires async — Gemini/Claude generates 2-sentence explanation per decision.
10. All of this is broadcast to WebSocket and logged to `decisions.db`.

**Good result signs:**
- `/health` returns `{"redis": true}` — Redis is connected
- `negotiation` WebSocket events appear with `winner` != `null` — bids are being accepted
- `xai` events appear within 5 seconds with non-empty `rationale`
- `/decisions` returns rows with `award_json.winner_agent_id` = `"power_agent"` for the hospital RFP
- `gini_before` and `gini_after` are both between 0.3 and 0.7 (expected range for this scenario)
- Power agent `status` = `"ACTIVE"`, load around 0.5–0.7 after the scenario

**Warning signs (not crashes, just degraded):**
- `xai` events have `rationale` starting with `"RATIONALE: power_units allocated..."` — this is the templated fallback, meaning both LLM providers failed (check API keys / quota)
- `negotiation` events with `winner: null` — power agent hit its 20% reserve floor; it has given out too much and can't bid further. Re-run will fail until the server restarts and resets state.
- `/health` returns `{"redis": false}` — Redis is down, system is running on in-process queues. Everything still works but pub/sub won't survive a second process connecting.

---

## How the negotiation works

Each resource request (RFP) goes through a 12-step cycle:

```
RFP broadcast
    → all agents evaluate_rfp() in parallel (2s timeout each)
    → bids scored: urgency×0.5 + availability×0.3 + fairness×0.2
    → PolicyAgent checks Gini: if > 0.4, bids from under-utilised agents penalised by 0.2
    → winner selected, resources transferred
    → Gini recomputed
    → XAI agent triggered async
    → decision logged to SQLite
    → WebSocketEvent("negotiation", ...) broadcast
```

**Fairness adjustment:** the `fairness` term in bid scoring = `1 - current_gini`. When resources are unevenly distributed (high Gini), all bids get a lower fairness score — this acts as automatic pressure to rebalance without any explicit rule.

**LIFE SAFETY OVERRIDE:** `power_agent.reallocate_to_hospital()` bypasses bidding entirely. Hospitals always receive power regardless of auction outcome. This is hardcoded by design and clearly commented in `agents/power_agent.py`.

---

## Zone map (Bangalore-inspired)

| Zone | Neighbourhood | Critical infra | Role in demo |
|---|---|---|---|
| Zone-A | Rajajinagar | NDRF base | NDRF deploys from here |
| Zone-B | Malleshwaram | Hospital | Issues power + personnel RFPs |
| Zone-C | Yeshwanthpur | — | HIGH severity zone |
| Zone-D | Peenya | — | **Earthquake epicenter** |
| Zone-E | Nagarbhavi | — | HIGH severity zone |
| Zone-F | Kengeri | Fire station | Fire dispatches from here |
| Zone-G–L | Various | — | Outer zones, lower severity |

---

## ML model

`simulation/zone_classifier.py` trains a `RandomForestClassifier` at startup on 500 synthetic samples. Features are `[severity_score, population_density, has_critical_infra]`. Labels are generated by the rule-based scorer.

The rule-based classifier is always authoritative. The RF is a secondary cross-check — if they disagree, rule-based wins and the disagreement is logged. This means the RF can be swapped for a model trained on real data (Nepal 2015 Gorkha earthquake dataset, Kaggle) without changing any other code.

To replace with a pre-trained model: train offline, save with `joblib.dump(model, "models/zone_classifier.pkl")`, then load it in `ZoneClassifier.__init__` instead of calling `train_ml_model()`.
