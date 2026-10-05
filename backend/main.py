from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

load_dotenv()

from pydantic import BaseModel, Field

from services.geocoding import search_places
from services.mcp_tools import list_tools
from services.orchestrator import handle_message
from services.route_chargers import filter_chargers_near_route
from services.tata_chargers import (
    get_all_tata_chargers,
    get_tata_chargers_in_bbox,
    search_tata_chargers,
    get_tata_charger_stats,
)
from services.ev_planner import plan_ev_trip
from services.routing import get_multi_stop_route
from services.trip_context import TripContextStore


app = FastAPI(
    title="GeoPilot AI",
    description="Conversational geospatial travel and EV assistant",
    version="2.0.6",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:4173",
        "http://127.0.0.1:4173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

store = TripContextStore()


@app.get("/")
async def root():
    return {"name": "GeoPilot AI", "status": "running", "version": "2.0.6"}


@app.get("/health")
async def health():
    return {"status": "healthy", "sessions": store.size(), "version": "2.0.6"}


@app.get("/geocode/search")
async def geocode_search(q: str = Query(..., min_length=1), limit: int = Query(5, ge=1, le=20)):
    try:
        results = await search_places(q, limit)
        return {"query": q, "count": len(results), "results": results}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Geocoding failed: {exc}") from exc


@app.get("/tata-chargers")
async def tata_chargers():
    return {"count": len(get_all_tata_chargers()), "chargers": get_all_tata_chargers()}


@app.get("/tata-chargers/bbox")
async def tata_chargers_bbox(west: float, south: float, east: float, north: float):
    return {
        "count": len(get_tata_chargers_in_bbox(south=south, west=west, north=north, east=east)),
        "chargers": get_tata_chargers_in_bbox(south=south, west=west, north=north, east=east),
    }


@app.get("/tata-chargers/search")
async def tata_chargers_search(
    q: str = Query("", min_length=0),
    limit: int = Query(50, ge=1, le=500),
):
    chargers = get_all_tata_chargers()
    q_norm = q.strip().lower()
    if q_norm:
        chargers = [
            charger for charger in chargers
            if q_norm in " ".join(str(charger.get(k, "")) for k in ["name", "city", "state", "address", "cpoName"]).lower()
        ]
    return {"query": q, "count": min(len(chargers), limit), "chargers": chargers[:limit]}


@app.get("/tata-chargers/stats")
async def tata_chargers_stats():
    return get_tata_charger_stats()


class RouteRequest(BaseModel):
    stops: list[dict[str, Any]] = Field(min_length=2, max_length=10)


@app.post("/route")
async def route(request: RouteRequest):
    try:
        return await get_multi_stop_route(request.stops)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Routing failed: {exc}") from exc


class EVPlanRequest(BaseModel):
    stops: list[dict[str, Any]] = Field(min_length=2, max_length=10)
    max_range_km: float = Field(gt=0)
    battery_percent: float = Field(ge=0, le=100)
    reserve_percent: float = Field(default=15, ge=0, lt=100)
    target_charge_percent: float = Field(default=80, gt=0, le=100)
    corridor_km: float = Field(default=5, gt=0, le=50)


@app.post("/ev/plan")
async def ev_plan(request: EVPlanRequest):
    if request.target_charge_percent <= request.reserve_percent:
        raise HTTPException(status_code=400, detail="target_charge_percent must be greater than reserve_percent")
    try:
        route = await get_multi_stop_route(request.stops)
        coords = route["geometry"]["coordinates"]
        from services.overpass_pois import route_bbox
        bbox = route_bbox(coords, request.corridor_km)
        candidates = get_tata_chargers_in_bbox(**bbox)
        chargers = filter_chargers_near_route(route["geometry"], candidates, request.corridor_km)
        plan = plan_ev_trip(
            route_distance_km=route["distance_km"],
            chargers=chargers,
            max_range_km=request.max_range_km,
            starting_battery_percent=request.battery_percent,
            reserve_percent=request.reserve_percent,
            target_charge_percent=request.target_charge_percent,
        )
        return {"route": route, "charger_count": len(chargers), "chargers": chargers, "ev_plan": plan}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"EV planning failed: {exc}") from exc


class EVCheckRequest(BaseModel):
    distance_km: float = Field(gt=0)
    max_range_km: float = Field(gt=0)
    battery_percent: float = Field(default=100, ge=0, le=100)
    reserve_percent: float = Field(default=15, ge=0, lt=100)


@app.post("/ev/check")
async def ev_check(request: EVCheckRequest):
    usable_battery = max(request.battery_percent - request.reserve_percent, 0)
    usable_range = usable_battery / 100 * request.max_range_km
    required = request.distance_km / request.max_range_km * 100
    return {
        "trip_possible": request.distance_km <= usable_range,
        "distance_km": round(request.distance_km, 2),
        "max_range_km": round(request.max_range_km, 2),
        "battery_percent": round(request.battery_percent, 2),
        "reserve_percent": round(request.reserve_percent, 2),
        "usable_range_km": round(usable_range, 2),
        "battery_required_percent": round(required, 2),
        "battery_remaining_percent": round(max(request.battery_percent - required, 0), 2),
    }


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    session_id: str | None = None


@app.post("/chat")
async def chat(request: ChatRequest):
    context = store.get(request.session_id) if request.session_id else store.create()
    try:
        context, result, reply = await handle_message(context, request.message)
        saved = store.save(context)
        return {
            "session_id": saved.session_id,
            "message": request.message,
            "reply": reply,
            "result": result,
            "context": saved.to_dict(),
        }
    except ValueError as exc:
        store.save(context)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        store.save(context)
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/session/{session_id}")
async def get_session(session_id: str):
    return store.get(session_id).to_dict()


@app.delete("/session/{session_id}")
async def delete_session(session_id: str):
    return {"deleted": store.delete(session_id), "session_id": session_id}


@app.get("/mcp/tools")
async def mcp_tools():
    """MCP-ready capability registry used by the orchestrator."""
    return {"tools": list_tools()}
