from __future__ import annotations

import os
from typing import Any

import httpx

from services.http_utils import request


OSRM_URL = os.getenv("OSRM_URL", "https://router.project-osrm.org")


def _validate_stops(stops: list[dict[str, Any]]) -> None:
    if len(stops) < 2:
        raise ValueError("At least two stops are required for routing.")
    for index, stop in enumerate(stops):
        try:
            float(stop["latitude"])
            float(stop["longitude"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"Invalid coordinates for stop {index + 1}.") from exc


async def get_multi_stop_route(stops: list[dict[str, Any]]) -> dict[str, Any]:
    """Calculate one road route through all stops using OSRM's ordered waypoints."""
    _validate_stops(stops)

    coordinates = ";".join(
        f"{float(stop['longitude'])},{float(stop['latitude'])}"
        for stop in stops
    )
    url = f"{OSRM_URL}/route/v1/driving/{coordinates}"

    params = {
        "overview": "full",
        "geometries": "geojson",
        "steps": "false",
        "annotations": "false",
        "continue_straight": "false",
    }

    timeout = httpx.Timeout(connect=10.0, read=45.0, write=20.0, pool=10.0)
    response = await request(
        "GET",
        url,
        timeout=timeout,
        headers={"User-Agent": "GeoPilot-AI/2.0"},
        params=params,
    )
    if response.status_code != 200:
        raise RuntimeError(f"OSRM returned {response.status_code}: {response.text[:600]}")
    data = response.json()

    if data.get("code") != "Ok" or not data.get("routes"):
        raise RuntimeError(f"OSRM routing failed: {data.get('message', 'No route found')}")

    route = data["routes"][0]
    legs = route.get("legs", [])
    cumulative = 0.0
    leg_summaries: list[dict[str, Any]] = []
    stop_positions: list[dict[str, Any]] = []

    for i, stop in enumerate(stops):
        if i == 0:
            distance_from_start = 0.0
        else:
            previous_leg = legs[i - 1] if i - 1 < len(legs) else {}
            cumulative += float(previous_leg.get("distance", 0.0)) / 1000.0
            distance_from_start = cumulative

            leg_summaries.append(
                {
                    "from_stop_index": i - 1,
                    "to_stop_index": i,
                    "distance_km": round(float(previous_leg.get("distance", 0.0)) / 1000.0, 2),
                    "duration_minutes": round(float(previous_leg.get("duration", 0.0)) / 60.0, 1),
                }
            )

        stop_positions.append(
            {
                "stop_index": i,
                "name": stop.get("name") or stop.get("display_name") or f"Stop {i + 1}",
                "latitude": float(stop["latitude"]),
                "longitude": float(stop["longitude"]),
                "distance_from_start_km": round(distance_from_start, 2),
                "route_position_percent": round(
                    (distance_from_start / max(float(route["distance"]) / 1000.0, 0.001)) * 100.0,
                    2,
                ),
            }
        )

    return {
        "distance_meters": route["distance"],
        "distance_km": round(float(route["distance"]) / 1000.0, 2),
        "duration_seconds": route["duration"],
        "duration_minutes": round(float(route["duration"]) / 60.0, 1),
        "geometry": route["geometry"],
        "legs": leg_summaries,
        "stop_positions": stop_positions,
        "waypoint_count": len(stops),
    }


async def get_route(
    start_latitude: float,
    start_longitude: float,
    end_latitude: float,
    end_longitude: float,
):
    return await get_multi_stop_route(
        [
            {"name": "Origin", "latitude": start_latitude, "longitude": start_longitude},
            {"name": "Destination", "latitude": end_latitude, "longitude": end_longitude},
        ]
    )
