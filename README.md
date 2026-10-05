# GeoPilot AI V2.0.1

GeoPilot AI is a conversational geospatial travel and EV planning application built around a persistent **Trip Context**. The frontend is React + TypeScript + MapLibre; the backend is FastAPI; routing uses OSRM; place search uses Nominatim; POIs use OpenStreetMap / Overpass; Tata EV chargers use the included CSV dataset. PostGIS remains available as the next storage layer rather than a blocker for this release.

## V2 capabilities

- Conversational follow-up questions with persistent session context
- Multi-stop trips: origin → waypoints → destination
- Trip edits: add/remove stops, change origin/destination
- POIs along the route corridor from OSM/Overpass
- Restaurants, cafes and hotels near trip stops
- POIs near planned charging stops
- Deterministic EV planning with reserve, target charge and route-aware charger filtering
- Vehicle context captured conversationally and treated as user-declared input
- Battery what-if simulation such as “What if I start with 60%?”
- MapLibre route, stops, Tata chargers and OSM POIs
- MCP-ready internal tool registry at `/mcp/tools`
- Heuristic fallback when Groq is unavailable, so the core workflow remains usable without the LLM

## Architecture

```text
React + MapLibre
       ↓
FastAPI /chat
       ↓
Persistent Trip Context
       ↓
AI Orchestrator
   ┌───┴─────────────────────────────┐
   │ Groq/GPT-OSS intent + response  │
   └───┬─────────────────────────────┘
       ↓
MCP-ready tool registry
   ├── Nominatim geocoding
   ├── OSRM multi-stop routing
   ├── Tata charger repository (CSV)
   ├── OSM/Overpass POI search
   └── deterministic EV planner
```

The LLM interprets language and explains verified results. Coordinates, routes, charger filtering and battery calculations remain deterministic backend operations.

## Run on Windows PowerShell

### 1. Backend

```powershell
cd C:\Users\prdas4\GeoPilot-AI\backend
py -3.10 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
Copy-Item .env.example .env
notepad .env
python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

Put your Groq key in `.env`:

```text
GROQ_API_KEY=your_key_here
```

The application still supports deterministic/heuristic fallback when the key is missing.

### 2. Frontend

Open a second PowerShell window:

```powershell
cd C:\Users\prdas4\GeoPilot-AI\frontend
npm install
npm run dev
```

Optional backend override:

```text
VITE_BACKEND_URL=http://localhost:8000
```

## First test conversation

Use the chat panel and send these messages:

```text
Plan an EV trip from Bengaluru to Mysuru
My vehicle is Tata Nexon EV with 400km range with 50 kWh battery pack currently having 90% charge
What if I start with 60%
Add Coorg
Find restaurants along the route
Find a hotel near my first charging stop
Change reserve to 20%
Charge only to 70%
Remove Coorg
```

The same session is reused automatically by the browser through local storage.

## Endpoints

- `GET /health`
- `GET /geocode/search?q=...`
- `POST /route` — ordered multi-stop route
- `POST /ev/plan` — route + Tata chargers + EV plan
- `POST /ev/check` — simple feasibility check
- `POST /chat` — conversational stateful orchestration
- `GET /session/{session_id}` — current Trip Context
- `DELETE /session/{session_id}` — reset server-side context
- `GET /mcp/tools` — tool registry and input schemas

## Current storage choice

The 9,683-station Tata dataset continues to load from the project CSV. The existing PostGIS work can be wired in later without redesigning the user-facing conversation model.

## OSM / Overpass behavior

POI queries use a single bounding-box or multi-point Overpass request, precise route-corridor filtering, five-minute in-process caching, and a second Overpass endpoint as a fallback. Public Overpass infrastructure can rate-limit requests, so repeated broad searches should be kept reasonable.

## Session persistence

Trip Context is intentionally in-memory for this portfolio release. It survives normal chat turns and browser reloads while the FastAPI process is running. A production deployment should move the session store to PostgreSQL/Redis and use multiple workers safely.

## TLS

TLS verification is enabled by default. Only set `GEO_HTTP_VERIFY_SSL=false` or `GROQ_VERIFY_SSL=false` for a controlled local environment when certificate trust is known to be the cause of a connection problem.

## Current scope exclusions

Satellite/imagery GeoAI, a vehicle-profile database and a separate spatial-analytics UI are not part of V2. The project keeps geospatial infrastructure modular so they can be added later.


### Local SSL / corporate proxy note

If the local network intercepts HTTPS and Python reports `CERTIFICATE_VERIFY_FAILED`, set `GROQ_VERIFY_SSL=false` in `backend/.env` and restart Uvicorn. The application loads `.env` before importing outbound HTTP services. Keep TLS verification enabled in production once the correct corporate/root CA is trusted by Python.
