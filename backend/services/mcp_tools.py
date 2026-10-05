from __future__ import annotations

from typing import Any, Awaitable, Callable

from services.geocoding import search_places
from services.overpass_pois import find_pois_along_route, find_pois_near_points
from services.routing import get_multi_stop_route


ToolFn = Callable[..., Awaitable[Any]]


async def geocode_place(query: str) -> list[dict[str, Any]]:
    return await search_places(query=query, limit=5)


async def calculate_route(stops: list[dict[str, Any]]) -> dict[str, Any]:
    return await get_multi_stop_route(stops)


async def find_route_pois(route_geometry: dict[str, Any], category: str, corridor_km: float, limit: int = 60):
    return await find_pois_along_route(route_geometry, category, corridor_km, limit)


async def find_nearby_pois(points: list[dict[str, float]], category: str, radius_km: float, limit: int = 80):
    return await find_pois_near_points(points, category, radius_km, limit)


TOOLS: dict[str, dict[str, Any]] = {
    "geocode_place": {
        "description": "Geocode one place with Nominatim.",
        "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
        "handler": geocode_place,
    },
    "calculate_multi_stop_route": {
        "description": "Calculate an ordered driving route through all supplied stops using OSRM.",
        "input_schema": {"type": "object", "properties": {"stops": {"type": "array"}}, "required": ["stops"]},
        "handler": calculate_route,
    },
    "find_pois_along_route": {
        "description": "Find OSM POIs within a corridor of a verified route.",
        "input_schema": {"type": "object", "properties": {"category": {"type": "string"}, "corridor_km": {"type": "number"}}, "required": ["category"]},
        "handler": find_route_pois,
    },
    "find_pois_near_location": {
        "description": "Find OSM POIs around one or more locations.",
        "input_schema": {"type": "object", "properties": {"category": {"type": "string"}, "radius_km": {"type": "number"}}, "required": ["category"]},
        "handler": find_nearby_pois,
    },
}


def list_tools() -> list[dict[str, Any]]:
    return [
        {
            "name": name,
            "description": definition["description"],
            "input_schema": definition["input_schema"],
        }
        for name, definition in TOOLS.items()
    ]
