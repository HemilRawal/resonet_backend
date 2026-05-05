# DACRO — Claude Code Instructions

## Project Identity
DACRO: Decentralized Autonomous Crisis Resource Orchestrator
A Multi-Agent System for real-time crisis resource negotiation during natural disasters.

## Mandate
You are building the backend of DACRO — a hackathon project with a 14-hour clock.
Every decision must prioritize: working demo > architectural perfection.
Trickery (fallbacks, mocks, hardcoded seeds) is explicitly allowed if it keeps the demo stable.

## Stack
- Python 3.11+
- Redis (Pub/Sub + simple KV store)
- FastAPI + WebSocket
- Gemini API (primary LLM) with Claude API fallback hook
- NetworkX (city graph, routing — stub for now)
- scikit-learn (zone classifier — rule-based first, ML wrapper second)
- SQLite (decision log persistence)

## Code Rules
1. Every file starts with a module-level docstring explaining what it does.
2. Every agent class has: `__init__`, `process_event`, `publish`, `get_state` methods minimum.
3. All inter-agent messages are typed dataclasses — no raw dicts flying around.
4. All config (thresholds, weights, API keys) lives in `config.py` — never hardcoded inline.
5. Every negotiation cycle MUST produce a log entry in `decisions.db`.
6. Fallback behavior: if any agent fails, the system continues with degraded mode, not crash.
7. No LangGraph. No LangChain. Pure Python state machines.

## File Update Discipline
After completing each module, update:
- `TODO.md` — mark done, add discovered tasks
- `CONTEXT.md` — append what was built, key decisions made, known issues

## Folder Structure
dacro/
├── CLAUDE.md
├── CONTEXT.md  
├── TODO.md
├── config.py
├── main.py                  # FastAPI entrypoint
├── agents/
│   ├── base_agent.py
│   ├── sensing_agent.py
│   ├── power_agent.py
│   ├── hospital_agent.py
│   ├── fire_agent.py
│   ├── police_agent.py
│   ├── ndrf_agent.py
│   ├── rescue_coordinator.py
│   ├── policy_agent.py
│   └── xai_agent.py
├── negotiation/
│   ├── protocol.py          # Contract Net Protocol
│   ├── orchestrator.py      # Runs negotiation cycles
│   └── scoring.py           # Bid scoring logic
├── simulation/
│   ├── earthquake.py        # Event generator
│   ├── city_model.py        # City graph + zones
│   └── zone_classifier.py   # Zone priority labeling
├── messaging/
│   ├── broker.py            # Redis wrapper
│   └── message_types.py     # All typed message dataclasses
├── intelligence/
│   ├── llm_client.py        # Gemini + Claude fallback
│   └── fairness.py          # Gini coefficient calculator
├── persistence/
│   └── decision_log.py      # SQLite decision history
└── api/
    ├── routes.py            # REST endpoints
    └── websocket.py         # WebSocket event push



 LLM Client Contract
llm_client.py must expose a single function:
pythonasync def generate_explanation(decision_context: dict) -> str
Internally it tries Gemini first, falls back to Claude if env var USE_CLAUDE=true or Gemini fails.
Demo Resilience Rules

City model is pre-seeded with 12 zones — never generated dynamically on first call
All agents initialize with hardcoded resource pools from config
The "Hospital Fire / Earthquake" scenario can be triggered via POST /simulate/earthquake
If Redis is unavailable, fall back to in-process queue (asyncio.Queue)