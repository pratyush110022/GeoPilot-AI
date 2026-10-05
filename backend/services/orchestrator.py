from __future__ import annotations

import re
from typing import Any

from services.ev_planner import plan_ev_trip
from services.groq_llm import final_answer, parse_intent
from services.heuristic_intent import parse as heuristic_parse
from services.mcp_tools import calculate_route, find_nearby_pois, find_route_pois, geocode_place
from services.route_chargers import filter_chargers_near_route
from services.tata_chargers import get_tata_chargers_in_bbox
from services.trip_context import PlaceContext, TripContext, VehicleContext


def _geocoded_place(query: str, result: dict[str, Any], role: str) -> PlaceContext:
    return PlaceContext(
        name=query,
        display_name=result.get("display_name") or query,
        latitude=float(result["latitude"]),
        longitude=float(result["longitude"]),
        role=role,
    )


async def _resolve_place(query: str, role: str = "stop") -> PlaceContext:
    results = await geocode_place(query)
    if not results:
        raise ValueError(f"Could not find '{query}'.")
    result = results[0]
    return _geocoded_place(query, result, role)


def _place_text(value: Any) -> str:
    """Normalize LLM place objects to a plain place-name string."""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for key in ("name", "place", "query", "display_name", "text"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
    return str(value).strip()


def _normalize_places(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    return [p for p in (_place_text(v) for v in values) if p]


def _safe_float(value: Any, default: float) -> float:
    """Return a finite float or a safe default for optional LLM fields."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number != number or number in (float("inf"), float("-inf")):
        return default
    return number


def _charger_as_poi(charger: dict[str, Any]) -> dict[str, Any]:
    """Adapt the verified GeoPilot EV layer to the common POI shape."""
    return {
        "osm_id": None,
        "osm_type": None,
        "name": charger.get("name") or charger.get("address") or "EV charging station",
        "category": "ev_charging",
        "latitude": float(charger["latitude"]),
        "longitude": float(charger["longitude"]),
        "operator": charger.get("cpoName"),
        "address": charger.get("address"),
        "source": "GeoPilot EV Charging Dataset",
        "charger_id": charger.get("id"),
        "charger": charger,
        "socket_type": charger.get("socket_type") or charger.get("chargerType"),
        "charging_speed": charger.get("charging_speed"),
        "estimated_power_kw": charger.get("estimated_power_kw"),
        "brand_key": charger.get("brand_key", "generic-ev"),
        "distance_from_route_km": charger.get("distance_from_route_km"),
        "route_position_percent": charger.get("route_position_percent"),
    }


def _validate_vehicle(context: TripContext) -> str | None:
    vehicle = context.vehicle
    if vehicle is None:
        return "Please share your vehicle profile: model, estimated range in km, and current battery %."
    missing = []
    if vehicle.max_range_km is None:
        missing.append("estimated range in km")
    if vehicle.current_battery_percent is None:
        missing.append("current battery %")
    if missing:
        return "Please share your " + " and ".join(missing) + "."
    return None


def _validate_settings(context: TripContext) -> None:
    if not 0 <= context.reserve_percent < 100:
        raise ValueError("Reserve must be between 0 and 99%.")
    if not 0 < context.target_charge_percent <= 100:
        raise ValueError("Target charge must be between 1 and 100%.")
    if context.target_charge_percent <= context.reserve_percent:
        raise ValueError("Target charge must be above the reserve percentage.")
    if context.corridor_km <= 0 or context.corridor_km > 50:
        raise ValueError("Corridor must be between 0 and 50 km.")


def _route_bbox(route: dict[str, Any], padding_km: float) -> dict[str, float]:
    coords = route.get("geometry", {}).get("coordinates", [])
    if len(coords) < 2:
        raise ValueError("Route geometry is missing.")
    from services.overpass_pois import route_bbox
    return route_bbox(coords, padding_km)


def _route_chargers(route: dict[str, Any], corridor_km: float) -> list[dict[str, Any]]:
    geometry = route["geometry"]
    bbox = _route_bbox(route, corridor_km)
    candidates = get_tata_chargers_in_bbox(**bbox)
    return filter_chargers_near_route(geometry, candidates, corridor_km)


def _compact_chargers(chargers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return chargers


def _result_base(context: TripContext) -> dict[str, Any]:
    return {
        "session_id": context.session_id,
        "stops": context.to_dict()["stops"],
        "vehicle": context.to_dict().get("vehicle"),
    }


async def _recalculate_route(context: TripContext, ev_required: bool = False) -> dict[str, Any]:
    if len(context.stops) < 2:
        return {"success": False, "needs_destination": True, "message": "Add an origin and destination first."}
    _validate_settings(context)
    route = await calculate_route([{
        "name": stop.name,
        "latitude": stop.latitude,
        "longitude": stop.longitude,
    } for stop in context.stops])
    context.route = route
    context.chargers = _route_chargers(route, context.corridor_km)
    context.pois = []
    context.ev_plan = None

    result: dict[str, Any] = {
        "success": True,
        "action": "plan_trip",
        "route": route,
        "chargers": _compact_chargers(context.chargers),
    }

    if ev_required:
        vehicle_error = _validate_vehicle(context)
        if vehicle_error:
            return {
                **result,
                "ev_required": True,
                "needs_vehicle": True,
                "message": vehicle_error,
            }
        vehicle = context.vehicle
        assert vehicle is not None
        plan = plan_ev_trip(
            route_distance_km=route["distance_km"],
            chargers=context.chargers,
            max_range_km=float(vehicle.max_range_km),
            starting_battery_percent=float(vehicle.current_battery_percent),
            reserve_percent=context.reserve_percent,
            target_charge_percent=context.target_charge_percent,
            battery_capacity_kwh=float(vehicle.battery_capacity_kwh) if vehicle.battery_capacity_kwh is not None else None,
            route_duration_minutes=float(route.get("duration_minutes")) if route.get("duration_minutes") is not None else None,
        )
        context.ev_plan = plan
        result["ev_plan"] = plan
        result["ev_required"] = True

    return result


def _update_vehicle(context: TripContext, updates: dict[str, Any]) -> None:
    vehicle = context.vehicle or VehicleContext()
    for field in ["make", "model", "max_range_km", "battery_capacity_kwh", "current_battery_percent"]:
        if field in updates and updates[field] is not None:
            value = updates[field]
            if field in {"max_range_km", "battery_capacity_kwh", "current_battery_percent"}:
                value = float(value)
            setattr(vehicle, field, value)
    context.vehicle = vehicle


def _settings(context: TripContext, updates: dict[str, Any]) -> None:
    for field in ["reserve_percent", "target_charge_percent", "corridor_km"]:
        if field in updates and updates[field] is not None:
            setattr(context, field, float(updates[field]))
    _validate_settings(context)


def _context_summary(context: TripContext) -> dict[str, Any]:
    return {
        **_result_base(context),
        "action": "context",
        "route_distance_km": context.route.get("distance_km") if context.route else None,
        "route_duration_minutes": context.route.get("duration_minutes") if context.route else None,
        "charging_stop_count": len((context.ev_plan or {}).get("charging_stops", [])),
        "pois_count": len(context.pois),
        "settings": {
            "reserve_percent": context.reserve_percent,
            "target_charge_percent": context.target_charge_percent,
            "corridor_km": context.corridor_km,
        },
    }


async def handle_message(context: TripContext, message: str) -> tuple[TripContext, dict[str, Any], str]:
    context.turn_count += 1
    try:
        llm_action = parse_intent(message, context.to_dict())
    except Exception:
        llm_action = None
    heuristic_action = heuristic_parse(message, context.to_dict())
    action = llm_action or heuristic_action

    # Deterministic heuristics take precedence for compound workflows and
    # explicit trip/EV edits. This keeps the orchestrator faithful to what
    # the user actually asked for even when the LLM returns a partial intent.
    heuristic_intent = heuristic_action.get("intent")
    if heuristic_intent == "compound_trip_request":
        action = heuristic_action
    elif heuristic_intent == "recommend_charger":
        action = heuristic_action
    elif heuristic_intent == "modify_trip":
        if not llm_action or llm_action.get("intent") != "modify_trip" or not llm_action.get("operation") or (llm_action.get("operation") == "add_stop" and not llm_action.get("place")):
            action = heuristic_action

    # The LLM is the intent classifier, but deterministic extraction is the
    # source of truth for numeric/profile fields explicitly supplied by the
    # user. This prevents a valid update_vehicle intent with missing fields
    # from silently discarding range/battery/capacity values.
    if (
        llm_action
        and llm_action.get("intent") == "update_vehicle"
        and heuristic_action.get("intent") == "update_vehicle"
    ):
        llm_updates = llm_action.get("vehicle_updates") or llm_action.get("vehicle") or {}
        deterministic_updates = heuristic_action.get("vehicle_updates") or {}
        action = {
            **llm_action,
            "vehicle_updates": {**deterministic_updates, **llm_updates},
        }

    if "intent" not in action and action.get("action"):
        legacy = dict(action)
        legacy["intent"] = {"ev_trip": "plan_trip", "route": "route", "geocode": "geocode"}.get(action.get("action"), action.get("action"))
        if legacy["intent"] == "plan_trip" and "places" not in legacy:
            legacy["places"] = [value for value in [action.get("origin"), action.get("destination")] if value]
        if legacy["intent"] == "plan_trip":
            legacy["ev_required"] = action.get("action") == "ev_trip"
        action = legacy
    result: dict[str, Any]
    intent = action.get("intent", "context")

    if intent == "compound_trip_request":
        places = _normalize_places(action.get("places"))
        if len(places) < 2:
            raise ValueError("Tell me an origin and destination for the trip.")
        resolved: list[PlaceContext] = []
        for i, place in enumerate(places):
            role = "origin" if i == 0 else "destination" if i == len(places) - 1 else "waypoint"
            resolved.append(await _resolve_place(place, role))
        context.stops = resolved
        if action.get("vehicle_updates"):
            _update_vehicle(context, action["vehicle_updates"])
        if action.get("settings"):
            _settings(context, action["settings"])
        route_result = await _recalculate_route(context, bool(action.get("ev_required")))
        if route_result.get("needs_vehicle"):
            result = route_result
        else:
            recommended = None
            recommended_stop = None
            if action.get("recommend_charger") and context.ev_plan:
                stops = context.ev_plan.get("charging_stops", [])
                if stops:
                    recommended_stop = stops[0]
                    recommended = dict(recommended_stop.get("charger", {}))
                    recommended["source"] = "GeoPilot EV Charging Dataset"

            poi_groups = []
            combined_pois = []
            for request in action.get("poi_requests", []):
                category = str(request.get("category") or "restaurant").replace(" ", "_")
                scope = request.get("scope") or "route"
                radius_km = _safe_float(request.get("radius_km"), 3.0)
                if radius_km <= 0:
                    radius_km = 3.0
                try:
                    if scope == "charging_stop":
                        stops = (context.ev_plan or {}).get("charging_stops", [])
                        idx = int(request.get("index") or 0)
                        if idx < 0 or idx >= len(stops):
                            raise ValueError(f"Charging stop #{idx + 1} is outside the current EV plan.")
                        charger = stops[idx]["charger"]
                        points = [{"latitude": float(charger["latitude"]), "longitude": float(charger["longitude"])}]
                        pois = await find_nearby_pois(points, category, radius_km, 80)
                    elif scope == "stop":
                        idx = int(request.get("index") or 0)
                        if idx < 0 or idx >= len(context.stops):
                            raise ValueError(f"Trip stop #{idx + 1} is outside the current trip.")
                        stop = context.stops[idx]
                        points = [{"latitude": stop.latitude, "longitude": stop.longitude}]
                        pois = await find_nearby_pois(points, category, radius_km, 80)
                    else:
                        pois = await find_route_pois(context.route["geometry"], category, context.corridor_km, 80)
                    group = {**request, "category": category, "scope": scope, "pois": pois, "source_status": "verified"}
                except Exception:
                    # Keep the route/EV result usable when OSM is temporarily
                    # unavailable. Groq receives an explicit unverified-source
                    # state and may provide generic guidance without inventing
                    # live POI listings.
                    group = {
                        **request,
                        "category": category,
                        "scope": scope,
                        "pois": [],
                        "source_status": "unavailable",
                        "source": "OpenStreetMap / Overpass",
                        "fallback_available": True,
                    }
                    pois = []
                poi_groups.append(group)
                combined_pois.extend(pois)

            context.pois = combined_pois
            result = {
                **route_result,
                "action": "compound_trip_request",
                "route": context.route,
                "ev_plan": context.ev_plan,
                "recommended_charger": recommended,
                "charging_stop": recommended_stop,
                "poi_groups": poi_groups,
                "pois": combined_pois,
                "poi_source_failures": [g.get("category") for g in poi_groups if g.get("source_status") == "unavailable"],
            }

    elif intent == "plan_trip":
        places = _normalize_places(action.get("places")) or [s.name for s in context.stops]
        if len(places) < 2:
            result = {"success": False, "action": "plan_trip", "message": "Tell me an origin and destination."}
        else:
            resolved: list[PlaceContext] = []
            for i, place in enumerate(places):
                role = "origin" if i == 0 else "destination" if i == len(places) - 1 else "waypoint"
                resolved.append(await _resolve_place(str(place), role))
            context.stops = resolved
            result = await _recalculate_route(context, bool(action.get("ev_required")))

    elif intent == "modify_trip":
        op = action.get("operation")
        if op == "add_stop":
            place = _place_text(action.get("place"))
            if not place:
                raise ValueError("Tell me which place to add.")
            new_stop = await _resolve_place(place, "waypoint")
            insert_index = action.get("index")
            if insert_index is None:
                insert_index = max(1, len(context.stops) - 1)
            index = max(1, min(int(insert_index), len(context.stops) - 1))
            context.stops.insert(index, new_stop)
        elif op == "remove_stop":
            if len(context.stops) <= 2:
                raise ValueError("A trip needs at least an origin and destination.")
            index = int(action.get("index", -1))
            if index < 0 or index >= len(context.stops):
                raise ValueError("That stop number is outside the current trip.")
            if index == 0 or index == len(context.stops) - 1:
                raise ValueError("Use a new origin/destination rather than removing an endpoint.")
            context.stops.pop(index)
        elif op == "set_origin":
            context.stops[0] = await _resolve_place(_place_text(action.get("place")), "origin")
        elif op == "set_destination":
            context.stops[-1] = await _resolve_place(_place_text(action.get("place")), "destination")
        else:
            raise ValueError("Unsupported trip edit.")
        context.stops[0].role = "origin"
        context.stops[-1].role = "destination"
        for stop in context.stops[1:-1]:
            stop.role = "waypoint"
        result = await _recalculate_route(context, bool(context.ev_plan))
        result["change"] = f"Trip updated: {', '.join(context.trip_names())}."

    elif intent == "update_vehicle":
        updates = action.get("vehicle_updates") or action.get("vehicle") or {}
        _update_vehicle(context, updates)
        ev_requested = any(k in message.lower() for k in ["ev", "battery", "charge", "range"]) or bool(context.ev_plan)
        result = {
            **_result_base(context),
            "success": True,
            "action": "update_vehicle",
            "vehicle": context.to_dict()["vehicle"],
        }
        if ev_requested and len(context.stops) >= 2:
            result.update(await _recalculate_route(context, True))
            result["action"] = "update_vehicle"

    elif intent == "update_settings":
        _settings(context, action.get("settings") or {})
        result = {
            **_result_base(context),
            "success": True,
            "action": "update_settings",
            "settings": {
                "reserve_percent": context.reserve_percent,
                "target_charge_percent": context.target_charge_percent,
                "corridor_km": context.corridor_km,
            },
        }
        if len(context.stops) >= 2:
            result.update(await _recalculate_route(context, bool(context.ev_plan)))
            result["action"] = "update_settings"

    elif intent == "simulate":
        field = action.get("field", "battery_percent")
        if field == "battery_percent":
            _update_vehicle(context, {"current_battery_percent": action.get("value")})
        elif field == "reserve_percent":
            _settings(context, {"reserve_percent": action.get("value")})
        elif field == "target_charge_percent":
            _settings(context, {"target_charge_percent": action.get("value")})
        else:
            raise ValueError("Unsupported what-if field.")
        if len(context.stops) < 2:
            raise ValueError("Plan a trip before running an EV simulation.")
        result = await _recalculate_route(context, True)
        result["action"] = "simulate"
        result["simulated_field"] = field
        result["simulated_value"] = action.get("value")

    elif intent == "recommend_charger":
        if len(context.stops) < 2:
            raise ValueError("Plan an EV trip before asking for a recommended charging stop.")
        vehicle_error = _validate_vehicle(context)
        if vehicle_error:
            raise ValueError(vehicle_error)
        # Always recompute from the current vehicle/battery/trip state so the
        # recommendation reflects the latest what-if or vehicle update.
        await _recalculate_route(context, True)
        plan = context.ev_plan or {}
        charging_stops = plan.get("charging_stops", [])
        if not charging_stops:
            result = {
                **_result_base(context),
                "success": bool(plan.get("trip_possible")),
                "action": "recommend_charger",
                "recommended_charger": None,
                "message": "No charging stop is required or no feasible charging stop was found with the current battery, range and reserve settings.",
                "ev_plan": plan,
            }
        else:
            first = charging_stops[0]
            charger = first.get("charger", {})
            charger = dict(charger)
            charger["source"] = "GeoPilot EV Charging Dataset"
            result = {
                **_result_base(context),
                "success": True,
                "action": "recommend_charger",
                "recommended_charger": charger,
                "charging_stop": first,
                "ev_plan": plan,
                "message": "Recommended by the deterministic EV planner from the GeoPilot EV Charging Dataset while maintaining the configured reserve.",
            }

    elif intent == "find_pois":
        if not context.route:
            if len(context.stops) < 2:
                raise ValueError("Plan a trip before searching for POIs.")
            await _recalculate_route(context, bool(context.ev_plan))
        category = str(action.get("category") or "restaurant").replace(" ", "_")
        scope = str(action.get("scope") or "route")
        radius_km = _safe_float(action.get("radius_km"), 3.0)
        if radius_km <= 0:
            radius_km = 3.0

        # EV charging is a first-party GeoPilot layer. Never send EV
        # charging requests to Overpass; only non-EV POIs use OSM.
        poi_source_status = "verified"
        if category == "ev_charging":
            if scope == "route":
                pois = [_charger_as_poi(charger) for charger in context.chargers]
            elif scope == "charging_stop":
                stops = (context.ev_plan or {}).get("charging_stops", [])
                if not stops:
                    raise ValueError("There are no planned charging stops yet.")
                idx = 0 if action.get("index") is None else int(action.get("index"))
                if idx < 0 or idx >= len(stops):
                    raise ValueError("That charging stop number is outside the current plan.")
                pois = [_charger_as_poi(stops[idx]["charger"])]
            else:
                # A direct EV-layer query near a trip stop uses the local
                # Tata dataset rather than creating an OSM charging query.
                points = []
                if scope == "destination":
                    points = [context.stops[-1]]
                elif scope == "origin":
                    points = [context.stops[0]]
                else:
                    idx = 0 if action.get("index") is None else int(action.get("index"))
                    if idx < 0 or idx >= len(context.stops):
                        raise ValueError("That stop number is outside the current trip.")
                    points = [context.stops[idx]]
                selected = []
                for charger in context.chargers:
                    for point in points:
                        # The route charger set is already corridor-filtered.
                        # Keep it deterministic and source-pure for the EV layer.
                        selected.append(_charger_as_poi(charger))
                        break
                pois = selected
        elif scope == "route":
            try:
                pois = await find_route_pois(context.route["geometry"], category, context.corridor_km, 80)
                poi_source_status = "verified"
            except Exception:
                pois = []
                poi_source_status = "unavailable"
        else:
            points: list[dict[str, float]] = []
            poi_source_status = "verified"
            index = action.get("index")
            if scope in {"destination", "origin", "all_stops"}:
                if scope == "destination":
                    target = context.stops[-1]
                    points = [{"latitude": target.latitude, "longitude": target.longitude}]
                elif scope == "origin":
                    target = context.stops[0]
                    points = [{"latitude": target.latitude, "longitude": target.longitude}]
                else:
                    points = [{"latitude": s.latitude, "longitude": s.longitude} for s in context.stops]
            elif scope == "charging_stop":
                stops = (context.ev_plan or {}).get("charging_stops", [])
                if not stops:
                    raise ValueError("There are no planned charging stops yet.")
                idx = 0 if index is None else int(index)
                if idx < 0 or idx >= len(stops):
                    raise ValueError("That charging stop number is outside the current plan.")
                charger = stops[idx]["charger"]
                try:
                    latitude = float(charger.get("latitude"))
                    longitude = float(charger.get("longitude"))
                except (TypeError, ValueError):
                    raise ValueError("The selected charging stop has invalid coordinates.")
                points = [{"latitude": latitude, "longitude": longitude}]
            else:
                idx = 0 if index is None else int(index)
                if scope == "stop":
                    if idx < 0 or idx >= len(context.stops):
                        raise ValueError("That stop number is outside the current trip.")
                    target = context.stops[idx]
                    points = [{"latitude": target.latitude, "longitude": target.longitude}]
                else:
                    points = [{"latitude": s.latitude, "longitude": s.longitude} for s in context.stops]
            try:
                pois = await find_nearby_pois(points, category, radius_km, 80)
                poi_source_status = "verified"
            except Exception:
                pois = []
                poi_source_status = "unavailable"
        context.pois = pois
        result = {
            **_result_base(context),
            "success": True,
            "action": "find_pois",
            "category": category,
            "scope": scope,
            "radius_km": radius_km,
            "pois": pois,
            "source_status": poi_source_status,
            "source": "GeoPilot EV Charging Dataset" if category == "ev_charging" else "OpenStreetMap / Overpass",
            "fallback_available": poi_source_status == "unavailable",
        }

    elif intent == "route":
        places = _normalize_places(action.get("places")) or [s.name for s in context.stops]
        if len(places) >= 2 and places != context.trip_names():
            resolved = []
            for i, place in enumerate(places):
                role = "origin" if i == 0 else "destination" if i == len(places) - 1 else "waypoint"
                resolved.append(await _resolve_place(str(place), role))
            context.stops = resolved
            result = await _recalculate_route(context, False)
        elif context.route:
            result = {**_result_base(context), "success": True, "action": "route", "route": context.route}
        else:
            raise ValueError("Tell me the origin and destination for the route.")

    elif intent == "geocode":
        query = str(action.get("place") or message)
        results = await geocode_place(query)
        result = {"success": bool(results), "action": "geocode", "query": query, "results": results[:5]}

    elif intent == "show_pois":
        result = {
            **_result_base(context),
            "success": True,
            "action": "show_pois",
            "pois": context.pois,
            "count": len(context.pois),
        }

    else:
        result = _context_summary(context)

    context.last_action = action
    response_context = context.to_dict()
    response_context.pop("last_action", None)
    # EV charging recommendations are source-sensitive. Keep this response
    # deterministic so the language model cannot substitute an OSM charger.
    if result.get("action") == "recommend_charger":
        reply = _fallback_reply(message, result, context)
    else:
        try:
            llm_reply = final_answer(message, response_context, result)
        except Exception:
            llm_reply = None
        reply = llm_reply or _fallback_reply(message, result, context)
    return context, result, reply


def _fallback_reply(message: str, result: dict[str, Any], context: TripContext) -> str:
    if result.get("needs_vehicle"):
        return result.get("message", "Please share your vehicle range and current battery percentage.")
    action = result.get("action")
    if action == "compound_trip_request" and result.get("route"):
        route = result["route"]
        text = f"Route: {route['distance_km']} km, about {route['duration_minutes']} min. Stops: {' → '.join(context.trip_names())}."
        plan = result.get("ev_plan") or {}
        if plan.get("trip_possible"):
            text += f" EV plan is feasible with {len(plan.get('charging_stops', []))} charging stop(s)."
        if result.get("recommended_charger"):
            charger = result["recommended_charger"]
            text += f" Next recommended charger: {charger.get('name') or 'EV charging station'} — Source: GeoPilot EV Charging Dataset."
        for group in result.get("poi_groups", []):
            pois = group.get("pois", [])
            category = str(group.get("category", "place")).replace("_", " ")
            if group.get("source_status") == "unavailable":
                text += f" Live OpenStreetMap/Overpass data for {category} is temporarily unavailable; general unverified guidance can still be provided by GeoPilot AI."
            else:
                text += f" Found {len(pois)} {category} POIs from OpenStreetMap/Overpass."
                names = [p.get("name") for p in pois[:5] if p.get("name")]
                if names:
                    text += " " + ", ".join(names) + "."
        return text
    if action in {"plan_trip", "route"} and result.get("route"):
        route = result["route"]
        text = f"Route: {route['distance_km']} km, about {route['duration_minutes']} min."
        if context.stops:
            text += " Stops: " + " → ".join(context.trip_names()) + "."
        if result.get("ev_plan"):
            plan = result["ev_plan"]
            if plan.get("trip_possible"):
                text += f" EV plan is feasible with {len(plan.get('charging_stops', []))} charging stop(s)."
            else:
                text += " I could not find a feasible charging plan with the current settings."
        return text
    if action == "recommend_charger":
        charger = result.get("recommended_charger")
        stop = result.get("charging_stop") or {}
        if not charger:
            return result.get("message", "No feasible charging stop was found.")
        name = charger.get("name") or charger.get("address") or "Unnamed charging station"
        operator = charger.get("cpoName") or "Operator not listed"
        return (
            f"Recommended charging stop: {name}. "
            f"Operator: {operator}. "
            f"About {charger.get('distance_from_route_km', 'n/a')} km from the route, "
            f"at {charger.get('route_position_percent', 'n/a')}% of the route. "
            f"Battery arrival is about {stop.get('battery_arrival_percent', 'n/a')}% and the planned departure is "
            f"about {stop.get('battery_departure_percent', 'n/a')}%. "
            f"Source: GeoPilot EV Charging Dataset (Tata charging layer)."
        )
    if action == "update_vehicle":
        return f"Vehicle context updated. Current vehicle details: {context.vehicle}."
    if action == "update_settings":
        return f"Trip settings updated: reserve {context.reserve_percent}%, charge target {context.target_charge_percent}%, corridor {context.corridor_km} km."
    if action == "simulate":
        plan = result.get("ev_plan", {})
        return f"What-if simulation recalculated with the updated EV setting. Feasible: {plan.get('trip_possible')}."
    if action == "find_pois":
        pois = result.get("pois", [])
        source = "GeoPilot EV Charging Dataset" if result.get("category") == "ev_charging" else "OpenStreetMap/Overpass"
        if result.get("source_status") == "unavailable":
            return f"Live {source} data is temporarily unavailable. I can still provide general, unverified guidance for {str(result.get('category', 'place')).replace('_', ' ')} based on GeoPilot AI's language model, but I won't present those suggestions as live map results."
        text = f"Found {len(pois)} {str(result.get('category', 'place')).replace('_', ' ')} POIs from {source}."
        names = [p.get("name") for p in pois[:10] if p.get("name")]
        if names:
            text += "\n" + "\n".join(f"{i + 1}. {name}" for i, name in enumerate(names))
        text += "\nThe matching POIs are also shown on the map."
        return text
    if action == "geocode":
        rows = result.get("results", [])
        if rows:
            p = rows[0]
            return f"{p.get('display_name', result.get('query'))} — {p.get('latitude')}, {p.get('longitude')}."
        return f"I couldn't find '{result.get('query')}'."
    if action == "show_pois":
        pois = result.get("pois", [])
        names = [p.get("name") for p in pois[:10] if p.get("name")]
        text = f"Showing {len(pois)} POIs on the map."
        if names:
            text += "\n" + "\n".join(f"{i + 1}. {name}" for i, name in enumerate(names))
        return text
    if action == "context":
        return f"Current trip: {' → '.join(context.trip_names()) or 'not set'}."
    return "I couldn't complete that request."
