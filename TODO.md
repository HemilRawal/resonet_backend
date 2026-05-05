
## TODO.md

```markdown
# DACRO — Task Tracker

## STATUS KEY
[ ] = not started | [~] = in progress | [x] = done | [!] = blocked

---

## PHASE 1 — Foundation
[x] config.py — all constants, weights, API keys, thresholds
[x] messaging/message_types.py — all dataclasses (Event, RFP, Bid, Award, AgentState)
[x] messaging/broker.py — Redis wrapper with asyncio.Queue fallback
[x] persistence/decision_log.py — SQLite schema + insert/query functions
[x] agents/base_agent.py — abstract base class all agents inherit

## PHASE 2 — Simulation Engine
[x] simulation/city_model.py — 12-zone city graph, pre-seeded nodes/edges
[x] simulation/earthquake.py — event generator, severity computation, damage radius
[x] simulation/zone_classifier.py — rule-based classifier + sklearn wrapper

## PHASE 3 — Agent Negotiation
[x] negotiation/protocol.py — Contract Net Protocol message factory
[x] negotiation/scoring.py — composite bid scoring (urgency × availability × fairness)
[x] negotiation/orchestrator.py — runs full 12-step CNP cycle, triggers XAI, logs decision
[x] agents/sensing_agent.py — ingests earthquake events, classifies zones, triggers RFPs, dispatches rescue
[x] agents/power_agent.py — manages power units, LIFE SAFETY OVERRIDE for hospitals
[x] agents/hospital_agent.py — monitors capacity, issues RFPs for power/personnel
[x] agents/fire_agent.py — fire suppression resources, responds to RFPs
[x] agents/police_agent.py — crowd control, zone access management
[x] agents/ndrf_agent.py — heavy rescue, single power RFP per event
[x] agents/rescue_coordinator.py — AERIAL/LAND routing, returns lat/lon waypoints for Leaflet
[x] agents/policy_agent.py — Gini monitor, fairness intervention, bid score adjustment
[x] intelligence/fairness.py — Gini coefficient, allocation summary

## PHASE 4 — XAI + LLM
[x] intelligence/llm_client.py — Groq primary → Gemini → Claude → templated fallback
[x] agents/xai_agent.py — generates RATIONALE|COUNTERFACTUAL, patches SQLite, broadcasts WebSocket

## PHASE 5 — API Layer
[x] main.py — FastAPI app, lifespan startup/shutdown, all agents wired
[x] api/routes.py — 9 endpoints including POST /simulate/reset
[x] api/websocket.py — WebSocketManager, broadcasts to all clients

## PHASE 6 — Integration + Demo
[x] Wire all agents into orchestrator startup sequence
[x] Seed demo scenario — one-click POST /simulate/scenario/hospital-earthquake
[x] Verify full cycle: event → classify → negotiate → award → XAI → WebSocket push
[x] Test Redis fallback (asyncio.Queue takes over when Redis is down)
[x] Verify SQLite logs all decisions with full context
[x] Narrative logging — zone table, bid collection, scoring, award, Gini delta
[x] POST /simulate/reset — restores city and agents without server restart
[x] Dispatch fires after classification, routes broadcast to frontend via WebSocket
[x] zone_update events include lat/lon for direct Leaflet marker placement

## PHASE 7 — ML Training
[x] training/train_zone_classifier.py — domain-informed synthetic + real Nepal data path
[x] Trained on 260,601 buildings from 2015 Nepal Gorkha earthquake (Mw 7.8)
[x] 1414 ward-level zones, percentile-based labels, 99.6% weighted F1
[x] models/zone_classifier.pkl auto-loaded at startup; falls back to synthetic if missing
[x] zone_classifier.py updated to load saved model via joblib

## PHASE 8 — Frontend (IN PROGRESS — teammate)
[ ] React + Leaflet map — zone polygons coloured by classification
[ ] Real-time zone_update events → change zone colour on map
[ ] Negotiation panel — live feed of bids, scores, winner per RFP
[ ] XAI panel — RATIONALE + COUNTERFACTUAL per decision
[ ] Dispatch overlay — AERIAL/LAND routes drawn as polylines
[ ] Agent status sidebar — resource pools, current_load bars
[ ] Demo controls — trigger earthquake button, reset button

## PHASE 9 — Dispatch & Routing (AFTER FRONTEND)
[ ] Wire rescue_coordinator.coordinate_dispatch into POST /simulate/earthquake response
[ ] Animate vehicle movement along LAND waypoints on the Leaflet map
[ ] Distinguish AERIAL (dashed arc) vs LAND (solid polyline) on map
[ ] Add ambulance/helicopter icons at dispatch origin zones

## DISCOVERED TASKS
[x] Create requirements.txt and .env.example
[x] Add __init__.py to all packages
[x] DecisionLog.update_xai_explanation — async XAI patch-back to SQLite
[x] Switch google-generativeai → google-genai (deprecated package)
[x] Fix RFP cascade: hospital triggers only for Zone-B, NDRF issues 1 power RFP per event
[x] Fix CRITICAL class missing from real Nepal data — switched to percentile-based labeling
[x] Add GROQ as primary LLM provider (higher RPM than Gemini free tier)
[x] Dispatch path returns lat/lon waypoints instead of zone ID strings
[x] POST /simulate/reset endpoint for demo re-runs
[x] zone_update payload includes lat/lon for frontend
[!] GROQ key not yet added to .env — XAI will fall through to Gemini/Claude/template until added

---
Last updated: 2026-05-05 — Phases 1–7 complete, Phase 8 in progress, Phase 9 queued
```
