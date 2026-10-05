"""Offline smoke test for the stateful orchestration layer."""
import asyncio

import services.orchestrator as orchestrator
from services.trip_context import TripContextStore


async def fake_geocode(query):
    coordinates = {
        "Bengaluru": (12.9716, 77.5946),
        "Mysuru": (12.2958, 76.6394),
        "Coorg": (12.3375, 75.8069),
    }
    latitude, longitude = coordinates.get(query, (12.0, 77.0))
    return [{"display_name": query, "latitude": latitude, "longitude": longitude}]


async def fake_route(stops):
    return {
        "distance_km": 240.0,
        "duration_minutes": 300.0,
        "geometry": {"type": "LineString", "coordinates": [[s["longitude"], s["latitude"]] for s in stops]},
        "legs": [],
        "stop_positions": [],
        "waypoint_count": len(stops),
    }


def fake_chargers(route, corridor):
    return [
        {"id": "c1", "name": "Charge 1", "latitude": 12.5, "longitude": 77.0, "chargerType": "50 kW", "route_position_percent": 45.0},
        {"id": "c2", "name": "Charge 2", "latitude": 12.3, "longitude": 76.7, "chargerType": "50 kW", "route_position_percent": 80.0},
    ]


async def fake_route_pois(*args, **kwargs):
    return [{"osm_id": 1, "osm_type": "node", "name": "Test Restaurant", "category": "restaurant", "latitude": 12.4, "longitude": 77.1}]


async def fake_nearby(*args, **kwargs):
    return [{"osm_id": 2, "osm_type": "node", "name": "Test Hotel", "category": "hotel", "latitude": 12.4, "longitude": 77.1}]


async def main():
    orchestrator.geocode_place = fake_geocode
    orchestrator.calculate_route = fake_route
    orchestrator._route_chargers = fake_chargers
    orchestrator.find_route_pois = fake_route_pois
    orchestrator.find_nearby_pois = fake_nearby

    context = TripContextStore().create()
    context, result, _ = await orchestrator.handle_message(context, "Plan an EV trip from Bengaluru to Mysuru")
    assert result["needs_vehicle"]

    context, _, _ = await orchestrator.handle_message(
        context,
        "My vehicle is Tata Nexon EV with 400km range with 50 kWh battery pack currently having 90% charge",
    )
    assert context.vehicle.max_range_km == 400
    assert context.ev_plan["trip_possible"]

    context, _, _ = await orchestrator.handle_message(context, "What if I start with 60%")
    assert context.vehicle.current_battery_percent == 60

    context, _, _ = await orchestrator.handle_message(context, "Add Coorg")
    assert [stop.name for stop in context.stops] == ["Bengaluru", "Coorg", "Mysuru"]

    context, _, _ = await orchestrator.handle_message(context, "Find restaurants along the route")
    assert context.pois[0]["category"] == "restaurant"

    context, _, _ = await orchestrator.handle_message(context, "Find a hotel near my first charging stop")
    assert context.pois[0]["category"] == "hotel"

    print("GeoPilot orchestrator smoke test: PASS")


if __name__ == "__main__":
    asyncio.run(main())
