# GeoPilot AI â€” HERE Edition 4.3.1

GeoPilot AI is a conversational geospatial travel and EV planning application built around a persistent **Trip Context**.

<CodeBlock language="markdown" editable>
## ðŸŽ¬ GeoPilot AI â€” Demo Video

Watch GeoPilot AI in action.
â–¶ Watch the GeoPilot AI Demo
Download the demo video
</CodeBlock>

## Architecture

```text
React + HERE Maps JavaScript SDK
          â†“
      FastAPI /chat
          â†“
   Persistent Trip Context
          â†“
      AI Orchestrator
      â”Œâ”€â”€â”€â”€â”´â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
      â”‚ Groq intent + response           â”‚
      â””â”€â”€â”€â”€â”¬â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜
           â†“
      MCP-ready tool registry
      â”œâ”€â”€ HERE Geocoding & Search
      â”œâ”€â”€ HERE Routing API v8
      â”œâ”€â”€ HERE Search POIs
      â”œâ”€â”€ OpenStreetMap / Overpass fallback
      â”œâ”€â”€ HERE EV Charging Search
      â”œâ”€â”€ GeoPilot EV Charging Dataset
      â””â”€â”€ deterministic EV planner
```

### Provider responsibilities

- **HERE Geocoding & Search** â€” India-first place resolution; this prevents ambiguous names such as `Goa` from being resolved to an unrelated country.
- **HERE Routing API v8** â€” ordered multi-stop road routing and HERE Flexible Polyline decoding.
- **HERE native EV routing** â€” attempted for EV trips with the user-declared vehicle context. If the HERE project/region does not accept the EV-specific request, GeoPilot safely falls back to a normal HERE road route and keeps its deterministic EV planner.
- **HERE Search** â€” primary provider for restaurants, hotels, cafes, hospitals, pharmacies, fuel, supermarkets, convenience stores, tourist attractions and parking along routes or near locations. If HERE fails or returns no matches, GeoPilot tries live OpenStreetMap / Overpass records and labels that source separately.
- **HERE EV Charging Search** â€” independent charger discovery near an arbitrary place.
- **GeoPilot EV Charging Dataset** â€” authoritative portfolio dataset for route-aware charging candidates and deterministic battery/charging calculations.
- **Open-Meteo** â€” optional current weather snapshots at route stops, the destination, and planned charging stops. No API key is required for the public endpoint; weather failures do not block trip planning. Weather is advisory, not an arrival-time forecast.
- **Groq** â€” natural-language intent parsing and answer generation. It does not invent coordinates or charging facts.

OpenStreetMap / Overpass is used as a live fallback for supported POI categories if HERE Search is unavailable or returns no matches. A map result is only rendered when a real provider record with coordinates is returned; LLM-generated place names or approximate coordinates are never inserted into the map-results card.

## Key capabilities

- Conversational follow-up questions with persistent session context
- Multi-stop trips and waypoint editing
- HERE route geometry and map visualization
- Route-corridor POI discovery
- Independent POI searches such as `restaurants near Anantnag`
- Independent EV charger searches such as `show me chargers near Anantnag`
- `add a charging stop at Anantnag` without confusing it with a trip waypoint
- Deterministic EV planning with reserve, target charge and route-aware charger filtering
- Native HERE EV-routing attempt plus deterministic GeoPilot EV fallback
- User-declared vehicle context and battery what-if simulation
- HERE map markers and clickable charging-stop information popups
- Weather summaries for the destination and planned charging stops
- Structured chat result cards for charging-stop, route, and nearby-place responses
- HERE tourist-attraction query fallbacks, precise distance/radius filtering, alternate nearby search terms, and live OSM/Overpass provider fallback
- MCP-ready internal capability registry at `/mcp/tools`

## Run on Windows PowerShell

### Backend

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

Set at minimum:

```text
HERE_API_KEY=your_existing_here_project_key
GROQ_API_KEY=your_groq_key
GROQ_MODEL=openai/gpt-oss-20b
HERE_EV_ENABLED=true
```

### Frontend

Open another PowerShell window:

```powershell
cd C:\Users\prdas4\GeoPilot-AI\frontend
npm install
npm run dev
```

Frontend `.env`:

```text
VITE_BACKEND_URL=http://127.0.0.1:8000
VITE_HERE_API_KEY=your_existing_here_project_key
```

## Useful tests

```text
Plan an EV trip from Bengaluru to Goa to Mumbai
Show me recommended charging stop
Show me detailed information about charging stop 2
Find 10 tourist places near Goa and show their name and distance
Find restaurants along the route
Find hotels around my destination
Find restaurants near Anantnag
Show me charger near Anantnag
Add a charging stop at Anantnag
Add Goa
What if I start with 60%?
Change reserve to 20%
Charge only to 70%
```

For an explicit charging stop, GeoPilot keeps the charger separate from the trip waypoint list. For `Add Goa`, Goa becomes a trip waypoint.

## Endpoints

- `GET /health`
- `GET /geocode/search?q=...`
- `POST /route`
- `POST /ev/plan`
- `POST /ev/check`
- `POST /chat`
- `GET /session/{session_id}`
- `DELETE /session/{session_id}`
- `GET /mcp/tools`

## Storage

Trip Context remains in-memory for this portfolio release. The 9,683-station GeoPilot/Tata charging CSV remains bundled with the project. PostGIS can be added later for indexed charger storage and multi-instance session persistence.

## Version 4.3.1 updates

- Falls back to live OpenStreetMap / Overpass POI records when HERE Search fails or returns no matching places; source labels are preserved in chat, map popups, and result cards.
- Makes place-search responses deterministic so the LLM cannot fabricate fallback attractions, distances, or coordinates when providers are unavailable.
- Makes EV station markers mouse, touch, and keyboard interactive and opens a selectable station-details panel in addition to the map information bubble.
- Adds provider-fallback regression tests and removes unused declarations that could block strict frontend checks.

## Version 4.3.0 features retained

- Open-Meteo current-condition context at destinations and planned charging stops, without silently changing EV range or battery calculations.
- Numbered charging-stop follow-ups so `charging stop 2` selects the second planned stop.
- HERE tourist-attraction query fallbacks, alternate terms, accurate radius filtering, deduplication, and a 15 km default only when no radius is specified.
- Structured UI cards for charging-stop details, weather, nearby places, and trip metrics.

See `FIX_NOTES_V4.3.1.md` for the latest patch and validation status.

## Demo Video

Watch the GeoPilot AI demo:

[![Watch GeoPilot AI Demo](https://img.shields.io/badge/Watch-GeoPilot%20AI%20Demo-blue?style=for-the-badge)](assets/Recording-2.mp4)

[Open or play the demo video](assets/Recording-2.mp4)
