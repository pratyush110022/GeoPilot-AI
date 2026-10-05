# GeoPilot AI V2 — Architecture & Research Notes

## Design objective

Turn GeoPilot from independent one-shot commands into a conversational geospatial system where every follow-up edits a single active Trip Context and then recalculates only the affected derived state.

## Research basis used for this implementation

The implementation follows the documented usage patterns already present in the supplied project for FastAPI, MapLibre GL, OSRM, Nominatim and Overpass, and keeps the existing deterministic EV planner as the source of truth for battery/charger calculations.

Live web verification was not available in this build session, so API/provider limits and current hosted-service policies were not independently rechecked against today's documentation. The code therefore uses configurable endpoints, conservative timeouts, public-service fallback/caching and explicit attribution.

Reference documentation for later live verification:

- OSRM API: https://project-osrm.org/docs/v5.24.0/api/
- Nominatim API: https://nominatim.org/release-docs/latest/api/Search/
- Overpass API language: https://wiki.openstreetmap.org/wiki/Overpass_API/Overpass_QL
- MapLibre GL JS: https://maplibre.org/maplibre-gl-js/docs/
- FastAPI: https://fastapi.tiangolo.com/
- Model Context Protocol: https://modelcontextprotocol.io/

## Conversation model

```text
user message
   ↓
Groq structured intent parser (optional)
   ↓
heuristic parser fallback
   ↓
AI Orchestrator
   ↓
Trip Context mutation
   ↓
verified tools
   ├── Nominatim
   ├── OSRM
   ├── Tata CSV + route corridor filter
   └── OSM/Overpass POI search
   ↓
verified result
   ↓
LLM explanation (optional)
   ↓
frontend map + conversation history
```

## Trip Context

The context owns:

- ordered stops (origin, waypoints, destination)
- user-declared vehicle information
- current battery percentage
- battery capacity, when supplied
- estimated vehicle range, when supplied
- reserve percentage
- target charge percentage
- route geometry and route legs
- route-aware Tata charging candidates
- current OSM POI result set
- deterministic EV plan

This means follow-ups such as `Add Coorg`, `Remove Mysuru`, `What if I start with 60%`, `Change reserve to 20%`, and `Find a hotel near my first charging stop` can act on existing state.

## Tool boundary

The backend keeps capabilities separated:

- OSRM: road routing only.
- Nominatim: place geocoding only.
- Overpass/OSM: dynamic POI discovery only.
- Tata CSV: charger repository for the portfolio dataset.
- EV planner: deterministic battery/charging calculations.
- Orchestrator: conversation/state management only.

`mcp_tools.py` is an MCP-ready internal tool registry. `/mcp/tools` publishes the available capabilities and input schemas. A full external MCP transport can be added without changing the tool implementations.

## POI strategy

For route POIs, GeoPilot builds a route bounding box, requests one category from Overpass, then performs precise route-corridor filtering using the route geometry.

For POIs near stops or charging stops, GeoPilot sends one multi-point Overpass query rather than one HTTP request per stop. Results are deduplicated, cached for five minutes in-process, and retried against a fallback Overpass endpoint after rate limiting or endpoint failure.

## EV strategy

The EV planner receives the actual OSRM route distance plus route-positioned charger candidates. User-declared range is used directly and is never presented as an official vehicle specification. Reserve and charge target remain explicit user controls.

## Storage strategy

The current release intentionally keeps Trip Context in memory and charger data in the included CSV. The existing PostGIS foundation remains separate so the next release can move charger/recent-session storage to PostgreSQL/Redis without redesigning the UI conversation model.

## Production hardening next

- Persist Trip Context in PostgreSQL/Redis.
- Put Nominatim/Overpass behind a controlled proxy or hosted provider with usage limits.
- Add rate limiting and auth around the API.
- Replace public CSV scans with PostGIS indexed spatial queries.
- Add a standards-compliant MCP transport if an external MCP client needs to connect directly.
- Add observed charger availability/connector status only when a trustworthy live provider is integrated.
