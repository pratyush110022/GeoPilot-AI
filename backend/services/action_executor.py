import json
import math
from typing import Any

from services.geocoding import search_places
from services.routing import get_route
from services.tata_chargers import get_tata_chargers_in_bbox
from services.route_chargers import filter_chargers_near_route
from services.ev_planner import plan_ev_trip


ALLOWED_ACTIONS = {
    "route",
    "geocode",
    "ev_trip",
}


# ============================================================
# VALIDATION HELPERS
# ============================================================

def _require_string(
    data: dict,
    key: str,
) -> str:

    value = data.get(key)

    if not isinstance(value, str) or not value.strip():
        raise ValueError(
            f"'{key}' is required."
        )

    return value.strip()


def _get_float(
    data: dict,
    key: str,
    default: float,
) -> float:

    value = data.get(key, default)

    try:
        return float(value)
    except (TypeError, ValueError):

        raise ValueError(
            f"'{key}' must be a number."
        )


# ============================================================
# GEOCODING
# ============================================================

async def _geocode(
    place: str,
) -> dict[str, Any]:

    results = await search_places(
        query=place,
        limit=1,
    )

    if not results:

        return {
            "success": False,
            "action": "geocode",
            "query": place,
            "error": (
                f"Could not find '{place}'."
            ),
        }

    result = results[0]

    return {
        "success": True,
        "action": "geocode",
        "query": place,
        "place": {
            "display_name": result.get(
                "display_name"
            ),
            "latitude": float(
                result["latitude"]
            ),
            "longitude": float(
                result["longitude"]
            ),
        },
    }


# ============================================================
# ROUTING
# ============================================================

async def _route(
    origin: str,
    destination: str,
) -> dict[str, Any]:

    origin_result = await _geocode(
        origin
    )

    if not origin_result["success"]:
        return origin_result

    destination_result = await _geocode(
        destination
    )

    if not destination_result["success"]:
        return destination_result

    start = origin_result["place"]
    end = destination_result["place"]

    route = await get_route(
        start_latitude=start["latitude"],
        start_longitude=start["longitude"],
        end_latitude=end["latitude"],
        end_longitude=end["longitude"],
    )

    return {
        "success": True,
        "action": "route",

        "origin": {
            "query": origin,
            **start,
        },

        "destination": {
            "query": destination,
            **end,
        },

        "route": route,
    }


# ============================================================
# ROUTE BBOX
# ============================================================

def _calculate_route_bbox(
    route_coordinates: list,
    padding_km: float,
) -> dict[str, float]:

    if not route_coordinates:

        raise ValueError(
            "Route contains no coordinates."
        )

    longitudes = [
        float(coordinate[0])
        for coordinate in route_coordinates
    ]

    latitudes = [
        float(coordinate[1])
        for coordinate in route_coordinates
    ]

    min_latitude = min(latitudes)
    max_latitude = max(latitudes)

    min_longitude = min(longitudes)
    max_longitude = max(longitudes)

    latitude_padding = (
        padding_km / 111.0
    )

    center_latitude = (
        min_latitude
        + max_latitude
    ) / 2

    longitude_factor = max(
        abs(
            math.cos(
                math.radians(
                    center_latitude
                )
            )
        ),
        0.1,
    )

    longitude_padding = (
        padding_km
        / (
            111.0
            * longitude_factor
        )
    )

    return {
        "west": (
            min_longitude
            - longitude_padding
        ),
        "south": (
            min_latitude
            - latitude_padding
        ),
        "east": (
            max_longitude
            + longitude_padding
        ),
        "north": (
            max_latitude
            + latitude_padding
        ),
    }


# ============================================================
# GET ROUTE CHARGERS
# ============================================================

def _get_route_chargers(
    route: dict,
    corridor_km: float,
) -> list[dict]:

    geometry = route.get(
        "geometry"
    )

    if not geometry:

        raise ValueError(
            "Route does not contain geometry."
        )

    route_coordinates = geometry.get(
        "coordinates",
        [],
    )

    if len(route_coordinates) < 2:

        raise ValueError(
            "Route geometry must contain "
            "at least two coordinates."
        )

    bbox = _calculate_route_bbox(
        route_coordinates=route_coordinates,
        padding_km=corridor_km,
    )

    candidates = get_tata_chargers_in_bbox(
        west=bbox["west"],
        south=bbox["south"],
        east=bbox["east"],
        north=bbox["north"],
    )

    route_chargers = (
        filter_chargers_near_route(
            route_geometry=geometry,
            stations=candidates,
            corridor_km=corridor_km,
        )
    )

    return route_chargers


# ============================================================
# EV TRIP
# ============================================================

async def _ev_trip(
    action: dict,
) -> dict[str, Any]:

    # --------------------------------------------------------
    # Required inputs
    # --------------------------------------------------------

    origin = _require_string(
        action,
        "origin",
    )

    destination = _require_string(
        action,
        "destination",
    )

    # --------------------------------------------------------
    # EV parameters
    # --------------------------------------------------------

    max_range_km = _get_float(
        action,
        "max_range_km",
        150.0,
    )

    battery_percent = _get_float(
        action,
        "battery_percent",
        80.0,
    )

    reserve_percent = _get_float(
        action,
        "reserve_percent",
        15.0,
    )

    target_charge_percent = _get_float(
        action,
        "target_charge_percent",
        80.0,
    )

    corridor_km = _get_float(
        action,
        "corridor_km",
        5.0,
    )

    # --------------------------------------------------------
    # Validate EV inputs
    # --------------------------------------------------------

    if max_range_km <= 0:

        raise ValueError(
            "max_range_km must be greater than zero."
        )

    if not 0 <= battery_percent <= 100:

        raise ValueError(
            "battery_percent must be between 0 and 100."
        )

    if not 0 <= reserve_percent < 100:

        raise ValueError(
            "reserve_percent must be between 0 and 100."
        )

    if not 0 < target_charge_percent <= 100:

        raise ValueError(
            "target_charge_percent must be "
            "greater than 0 and at most 100."
        )

    if target_charge_percent <= reserve_percent:

        raise ValueError(
            "target_charge_percent must be "
            "greater than reserve_percent."
        )

    if corridor_km <= 0:

        raise ValueError(
            "corridor_km must be greater than zero."
        )

    # --------------------------------------------------------
    # Step 1: Geocode origin
    # --------------------------------------------------------

    origin_result = await _geocode(
        origin
    )

    if not origin_result["success"]:
        return origin_result

    # --------------------------------------------------------
    # Step 2: Geocode destination
    # --------------------------------------------------------

    destination_result = await _geocode(
        destination
    )

    if not destination_result["success"]:
        return destination_result

    start = origin_result["place"]
    end = destination_result["place"]

    # --------------------------------------------------------
    # Step 3: Calculate actual road route
    # --------------------------------------------------------

    route = await get_route(
        start_latitude=start["latitude"],
        start_longitude=start["longitude"],
        end_latitude=end["latitude"],
        end_longitude=end["longitude"],
    )

    route_distance_km = float(
        route["distance_km"]
    )

    # --------------------------------------------------------
    # Step 4: Find Tata chargers along route
    # --------------------------------------------------------

    chargers = _get_route_chargers(
        route=route,
        corridor_km=corridor_km,
    )

    # --------------------------------------------------------
    # Step 5: Run deterministic EV planner
    # --------------------------------------------------------

    ev_plan = plan_ev_trip(
        route_distance_km=route_distance_km,
        chargers=chargers,
        max_range_km=max_range_km,
        starting_battery_percent=battery_percent,
        reserve_percent=reserve_percent,
        target_charge_percent=target_charge_percent,
    )

    # --------------------------------------------------------
    # Step 6: Return verified result
    # --------------------------------------------------------

    return {
        "success": True,
        "action": "ev_trip",

        "origin": {
            "query": origin,
            **start,
        },

        "destination": {
            "query": destination,
            **end,
        },

        "route": route,

        "charger_count": len(
            chargers
        ),

        "chargers": chargers,

        "ev_parameters": {
            "max_range_km": max_range_km,
            "battery_percent": battery_percent,
            "reserve_percent": reserve_percent,
            "target_charge_percent": (
                target_charge_percent
            ),
            "corridor_km": corridor_km,
        },

        "ev_plan": ev_plan,
    }


# ============================================================
# ACTION EXECUTOR
# ============================================================

async def execute_action(
    action: dict,
) -> dict[str, Any]:

    if not isinstance(action, dict):

        raise ValueError(
            "Action must be a JSON object."
        )

    action_type = action.get(
        "action"
    )

    if action_type not in ALLOWED_ACTIONS:

        raise ValueError(
            f"Unsupported action "
            f"'{action_type}'. "
            f"Allowed actions: "
            f"{sorted(ALLOWED_ACTIONS)}"
        )

    # --------------------------------------------------------
    # Geocode
    # --------------------------------------------------------

    if action_type == "geocode":

        place = _require_string(
            action,
            "place",
        )

        return await _geocode(
            place
        )

    # --------------------------------------------------------
    # Route
    # --------------------------------------------------------

    if action_type == "route":

        origin = _require_string(
            action,
            "origin",
        )

        destination = _require_string(
            action,
            "destination",
        )

        return await _route(
            origin,
            destination,
        )

    # --------------------------------------------------------
    # EV Trip
    # --------------------------------------------------------

    if action_type == "ev_trip":

        return await _ev_trip(
            action
        )

    raise ValueError(
        f"Unsupported action: "
        f"{action_type}"
    )


# ============================================================
# EXECUTE JSON ACTION
# ============================================================

async def execute_action_from_json(
    action_json: str,
) -> dict[str, Any]:

    try:

        action = json.loads(
            action_json
        )

    except json.JSONDecodeError as exc:

        raise ValueError(
            "Invalid action JSON."
        ) from exc

    return await execute_action(
        action
    )