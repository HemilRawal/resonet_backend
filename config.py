"""
Central configuration for DACRO — all constants, thresholds, API keys, and seed data live here.
No magic numbers anywhere else in the codebase; import from this module.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# --- Infrastructure ---
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")

# --- API Keys ---
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
USE_CLAUDE = os.getenv("USE_CLAUDE", "false").lower() == "true"

# --- Model Names ---
GROQ_MODEL = "llama-3.3-70b-versatile"   # primary — high RPM, large context, free tier
GEMINI_MODEL = "gemini-2.0-flash"         # secondary fallback
CLAUDE_MODEL = "claude-sonnet-4-20250514" # tertiary fallback

# --- Fairness & Routing Thresholds ---
GINI_THRESHOLD = 0.4
AERIAL_ETA_THRESHOLD = 25  # minutes — switch to aerial if land ETA exceeds this

# --- Zone Classification Weights ---
ZONE_SEVERITY_WEIGHTS = {"severity": 0.4, "population": 0.3, "critical_infra": 0.3}

# --- Zone Priority Classification Thresholds ---
PRIORITY_THRESHOLDS = {"critical": 0.7, "high": 0.4, "low": 0.1}

# --- Initial Resource Pools per Agent Type ---
AGENT_INITIAL_RESOURCES = {
    "power": {
        "power_units": 200,
    },
    "hospital": {
        "power_units": 50,
        "beds": 300,
        "personnel": 80,
        "ambulances": 10,
    },
    "fire": {
        "vehicles": 12,
        "personnel": 60,
        "water_units": 500,
    },
    "police": {
        "personnel": 100,
        "vehicles": 20,
    },
    "ndrf": {
        "heavy_equipment": 15,
        "personnel": 120,
        "aerial_units": 4,
    },
    "rescue_coordinator": {},
    "sensing": {},
    "xai": {},
    "policy": {},
}

# --- City Graph: 12 Pre-Seeded Zones (Bangalore-inspired) ---
# Zone-B: hospital | Zone-D: epicenter | Zone-A: NDRF base | Zone-F: fire station
CITY_ZONES = [
    {
        "id": "Zone-A",
        "name": "Rajajinagar",
        "lat": 12.9914,
        "lon": 77.5561,
        "population_density": 0.65,
        "has_critical_infra": True,   # NDRF base
        "connected_zones": ["Zone-B", "Zone-C", "Zone-G"],
    },
    {
        "id": "Zone-B",
        "name": "Malleshwaram",
        "lat": 13.0035,
        "lon": 77.5710,
        "population_density": 0.80,
        "has_critical_infra": True,   # Hospital
        "connected_zones": ["Zone-A", "Zone-C", "Zone-H"],
    },
    {
        "id": "Zone-C",
        "name": "Yeshwanthpur",
        "lat": 13.0245,
        "lon": 77.5503,
        "population_density": 0.70,
        "has_critical_infra": False,
        "connected_zones": ["Zone-A", "Zone-B", "Zone-D"],
    },
    {
        "id": "Zone-D",
        "name": "Peenya",
        "lat": 12.9700,
        "lon": 77.5900,
        "population_density": 0.75,
        "has_critical_infra": False,  # Earthquake epicenter
        "connected_zones": ["Zone-C", "Zone-E", "Zone-I"],
    },
    {
        "id": "Zone-E",
        "name": "Nagarbhavi",
        "lat": 12.9580,
        "lon": 77.5200,
        "population_density": 0.60,
        "has_critical_infra": False,
        "connected_zones": ["Zone-D", "Zone-F", "Zone-J"],
    },
    {
        "id": "Zone-F",
        "name": "Kengeri",
        "lat": 12.9085,
        "lon": 77.4842,
        "population_density": 0.55,
        "has_critical_infra": True,   # Fire station
        "connected_zones": ["Zone-E", "Zone-G", "Zone-K"],
    },
    {
        "id": "Zone-G",
        "name": "Vijayanagar",
        "lat": 12.9691,
        "lon": 77.5394,
        "population_density": 0.72,
        "has_critical_infra": False,
        "connected_zones": ["Zone-A", "Zone-F", "Zone-H"],
    },
    {
        "id": "Zone-H",
        "name": "Basaveshwara Nagar",
        "lat": 12.9899,
        "lon": 77.5443,
        "population_density": 0.68,
        "has_critical_infra": False,
        "connected_zones": ["Zone-B", "Zone-G", "Zone-I"],
    },
    {
        "id": "Zone-I",
        "name": "Mahalakshmi Layout",
        "lat": 13.0051,
        "lon": 77.5591,
        "population_density": 0.62,
        "has_critical_infra": False,
        "connected_zones": ["Zone-D", "Zone-H", "Zone-J"],
    },
    {
        "id": "Zone-J",
        "name": "Nandini Layout",
        "lat": 12.9803,
        "lon": 77.5108,
        "population_density": 0.50,
        "has_critical_infra": False,
        "connected_zones": ["Zone-E", "Zone-I", "Zone-K"],
    },
    {
        "id": "Zone-K",
        "name": "Ullal",
        "lat": 12.9301,
        "lon": 77.5020,
        "population_density": 0.40,
        "has_critical_infra": False,
        "connected_zones": ["Zone-F", "Zone-J", "Zone-L"],
    },
    {
        "id": "Zone-L",
        "name": "Kanakapura Road",
        "lat": 12.8890,
        "lon": 77.5190,
        "population_density": 0.30,
        "has_critical_infra": False,
        "connected_zones": ["Zone-K"],
    },
]

# --- Responder Stations (multi-location dispatch registry) ---
# Each responder type has 2-3 physical stations distributed geographically
# (north / south / east / west) so dispatch goes from the *closest* station
# to the disaster epicenter. Both backend (sensing_agent) and frontend
# (EmergencyRoutes.jsx) read from these coordinates — they MUST stay in sync.
RESPONDER_LOCATIONS = {
    "hospital": [
        {"id": "HOSP-E", "name": "Hebbal Medical Centre",          "lat": 13.030, "lon": 77.660},
        {"id": "HOSP-W", "name": "Magadi West Medical Centre",     "lat": 12.985, "lon": 77.460},
        {"id": "HOSP-N", "name": "Yelahanka District Hospital",    "lat": 13.055, "lon": 77.530},
    ],
    "fire": [
        {"id": "FIRE-E", "name": "Banaswadi Fire Station",         "lat": 12.908, "lon": 77.640},
        {"id": "FIRE-W", "name": "Magadi Road Fire Station",       "lat": 12.968, "lon": 77.450},
        {"id": "FIRE-S", "name": "Kanakapura Fire Station",        "lat": 12.870, "lon": 77.560},
    ],
    "police": [
        {"id": "POL-C",  "name": "Central Police HQ",              "lat": 12.971, "lon": 77.594},
        {"id": "POL-W",  "name": "West Bangalore Police HQ",       "lat": 13.000, "lon": 77.480},
        {"id": "POL-S",  "name": "South Bangalore Police HQ",      "lat": 12.890, "lon": 77.530},
    ],
    "ndrf": [
        {"id": "NDRF-E", "name": "Hebbal NDRF Rapid Response",     "lat": 12.985, "lon": 77.662},
        {"id": "NDRF-W", "name": "Nelamangala NDRF Base",          "lat": 12.945, "lon": 77.460},
        {"id": "NDRF-N", "name": "Yelahanka NDRF Base",            "lat": 13.060, "lon": 77.580},
    ],
}

# --- Demo Earthquake Seed ---
DEMO_EARTHQUAKE = {
    "epicenter_lat": 12.97,
    "epicenter_lon": 77.59,
    "magnitude": 7.2,
    "epicenter_zone": "Zone-D",
}

# --- Demo Fire Seed ---
DEMO_FIRE = {
    "epicenter_lat": 13.0051,    # Zone-I (Mahalakshmi Layout)
    "epicenter_lon": 77.5591,
    "intensity": 5.0,            # analogous to magnitude
    "radius_km": 0.4,            # very tight — fire affects only the epicenter zone visually
    "epicenter_zone": "Zone-I",
}

# --- Default Road Travel Time (minutes) for city graph edges ---
DEFAULT_EDGE_TRAVEL_TIME = 10  # minutes per edge, before damage
BLOCKED_ROAD_TRAVEL_TIME = 999  # effectively impassable

# --- Bid Scoring Weights ---
BID_SCORE_WEIGHTS = {
    "urgency": 0.5,
    "availability": 0.3,
    "fairness": 0.2,
}

# --- Agent Status Constants ---
STATUS_IDLE = "IDLE"
STATUS_ACTIVE = "ACTIVE"
STATUS_OVERLOADED = "OVERLOADED"
STATUS_OFFLINE = "OFFLINE"

# --- Channel Names ---
CHANNEL_BROADCAST = "dacro:broadcast"
CHANNEL_RFP = "dacro:rfp"
CHANNEL_AWARDS = "dacro:awards"
CHANNEL_EARTHQUAKE = "dacro:earthquake"

# --- Persistence ---
SQLITE_DB_PATH = "decisions.db"