from __future__ import annotations

import re
from typing import Any


PLACE_SPLIT_RE = re.compile(r"\s*(?:,|\band\b|\bthen\b|->|→)\s*", re.IGNORECASE)


def _number(message: str, patterns: list[str]) -> float | None:
    for pattern in patterns:
        match = re.search(pattern, message, flags=re.IGNORECASE)
        if match:
            return float(match.group(1))
    return None


def _vehicle_update(message: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    max_range = _number(message, [
        r"range\s*(?:of|is|=)?\s*(\d+(?:\.\d+)?)\s*km",
        r"(\d+(?:\.\d+)?)\s*km\s*(?:range|driving range)",
    ])
    battery = _number(message, [
        r"(?:current|currently)\s+battery\s*(?:is|at|=)?\s*(\d+(?:\.\d+)?)\s*%",
        r"battery\s*(?:at|is|=)?\s*(\d+(?:\.\d+)?)\s*%",
        r"(\d+(?:\.\d+)?)\s*%\s+battery\b",
        r"(\d+(?:\.\d+)?)\s*%\s+charge\b",
        r"(?:currently\s+)?(?:at|having|with)\s*(\d+(?:\.\d+)?)\s*%\s*(?:charge|battery)",
    ])
    capacity = _number(message, [
        r"battery\s*capacity\s*(?:of|is|=)?\s*(\d+(?:\.\d+)?)\s*kwh",
        r"(\d+(?:\.\d+)?)\s*kwh\s*(?:battery\s*)?pack?",
        r"(\d+(?:\.\d+)?)\s*kwh\b",
    ])
    if max_range is not None:
        result["max_range_km"] = max_range
    if battery is not None:
        result["current_battery_percent"] = battery
    if capacity is not None:
        result["battery_capacity_kwh"] = capacity

    vehicle_match = re.search(r"(?:vehicle|car|i\s*(?:have|drive|am driving|own)|my car)\s*(?:is|=)?\s*([A-Za-z][A-Za-z0-9-]*(?:\s+[A-Za-z][A-Za-z0-9-]*){0,3})", message, flags=re.IGNORECASE)
    if vehicle_match:
        text = vehicle_match.group(1).strip()
        parts = text.split()
        if len(parts) >= 2:
            result["make"] = parts[0].title()
            result["model"] = " ".join(parts[1:])
        else:
            result["model"] = text

    for make, model in [
        ("Tata", "Nexon EV"),
        ("MG", "ZS EV"),
        ("Hyundai", "Kona Electric"),
        ("Mahindra", "XUV400"),
        ("BYD", "Atto 3"),
    ]:
        if re.search(rf"\b{re.escape(model)}\b", message, flags=re.IGNORECASE):
            result["make"] = make
            result["model"] = model
            break
    return result


def _compound_trip_request(text: str, context: dict[str, Any]) -> dict[str, Any] | None:
    """Recognize a single user message containing a full trip + POI workflow."""
    lower = text.lower()
    plan_match = re.search(
        r"(?:plan|plan an|plan a)\s+(?:an\s+)?(?:ev\s+)?trip\s+from\s+(.+?)\s+to\s+(.+?)(?:\s+via\s+(.+?))?(?:[.!?]|$)",
        text,
        flags=re.IGNORECASE,
    )
    if not plan_match or not any(k in lower for k in ("restaurant", "hotel", "tourist", "recommended charging", "charging stop")):
        return None

    origin = plan_match.group(1).strip()
    destination = plan_match.group(2).strip()
    via = (plan_match.group(3) or "").strip()
    places = [origin]
    if via:
        places.extend([p.strip() for p in re.split(r"\s*(?:,|and)\s*", via) if p.strip()])
    places.append(destination)

    requests: list[dict[str, Any]] = []
    # Explicit charging-stop references.
    ordinal_map = {"first": 0, "1st": 0, "second": 1, "2nd": 1, "third": 2, "3rd": 2, "fourth": 3, "4th": 3, "fifth": 4, "5th": 4}
    for category in ("restaurant", "hotel", "tourist attraction", "tourist places", "attractions"):
        for match in re.finditer(
            rf"{re.escape(category)}s?\s+(?:near|at|around|in|on)\s+(?:the\s+)?([^.!?;]+)",
            text,
            flags=re.IGNORECASE,
        ):
            ref = match.group(1).strip().rstrip(" ,")
            # Stop at conjunctions that begin another request.
            ref = re.split(r"\s+(?:and|then)\s+(?=(?:restaurants?|hotels?|tourist|attractions?))", ref, maxsplit=1, flags=re.IGNORECASE)[0].strip()
            ref_lower = ref.lower()
            request: dict[str, Any] = {"category": category.replace(" ", "_"), "scope": "route", "index": None, "radius_km": 3.0}
            charging_match = re.search(r"(first|1st|second|2nd|third|3rd|fourth|4th|fifth|5th)\s+(?:actual\s+)?(?:charging|charger)\s+stop", ref_lower)
            if charging_match:
                request["scope"] = "charging_stop"
                request["index"] = ordinal_map.get(charging_match.group(1), 0)
            else:
                for i, place in enumerate(places):
                    if place.lower() in ref_lower or ref_lower in place.lower():
                        request["scope"] = "stop"
                        request["index"] = i
                        break
            requests.append(request)

    if re.search(r"\b(?:recommend|recommended|suggest|show)\b.*\b(?:charging|charger)\s+stop\b", lower):
        recommend = True
    else:
        recommend = False

    vehicle_updates = _vehicle_update(text)
    settings: dict[str, float] = {}
    reserve = _number(text, [r"reserve\s*(?:to|=|at|of)?\s*(\d+(?:\.\d+)?)\s*%?", r"(\d+(?:\.\d+)?)\s*%\s+reserve\b"])
    target = _number(text, [r"(?:charge|target charge)\s*(?:to|up to|=|at|only to)\s*(\d+(?:\.\d+)?)\s*%?"])
    if reserve is not None:
        settings["reserve_percent"] = reserve
    if target is not None:
        settings["target_charge_percent"] = target

    return {
        "intent": "compound_trip_request",
        "places": places,
        "ev_required": bool(re.search(r"\b(?:ev|electric|battery|charging|charger)\b", lower)),
        "vehicle_updates": vehicle_updates,
        "settings": settings,
        "recommend_charger": recommend,
        "poi_requests": requests,
    }


def parse(message: str, context: dict[str, Any]) -> dict[str, Any]:
    text = message.strip()
    lower = text.lower()

    compound = _compound_trip_request(text, context)
    if compound:
        return compound

    if any(word in lower for word in ["what is my trip", "show context", "what do you know", "trip context"]):
        return {"intent": "context"}

    if context.get("pois") and re.search(r"\b(?:show|share|list|display)\b.*\b(?:here|map|places|them)\b", lower):
        return {"intent": "show_pois"}

    vehicle_fields = _vehicle_update(text)
    if vehicle_fields and any(k in lower for k in ["vehicle", "car", "range", "battery", "kwh", "charge"]):
        if any(k in lower for k in ["range", "battery", "kwh", "charge", "vehicle", "car"]):
            return {"intent": "update_vehicle", "vehicle_updates": vehicle_fields}

    reserve = _number(text, [r"reserve\s*(?:to|=|at|of)?\s*(\d+(?:\.\d+)?)\s*%?", r"(\d+(?:\.\d+)?)\s*%\s+reserve\b"])
    target = _number(text, [r"(?:charge|target charge)\s*(?:to|up to|=|at|only to)\s*(\d+(?:\.\d+)?)\s*%?"])
    corridor = _number(text, [r"corridor\s*(?:to|=|of)\s*(\d+(?:\.\d+)?)\s*km"])
    if reserve is not None or target is not None or corridor is not None:
        return {"intent": "update_settings", "settings": {k: v for k, v in [("reserve_percent", reserve), ("target_charge_percent", target), ("corridor_km", corridor)] if v is not None}}

    battery_change = _number(text, [r"(?:start|starting|leave)\s*(?:with|at)\s*(\d+(?:\.\d+)?)\s*%", r"what if i (?:start|leave)\s*(?:with|at)\s*(\d+(?:\.\d+)?)\s*%"])
    if battery_change is not None:
        return {"intent": "simulate", "field": "battery_percent", "value": battery_change}

    remove = re.search(r"(?:remove|delete|drop)\s+(?:stop|place)?\s*(\d+)", lower)
    if remove:
        return {"intent": "modify_trip", "operation": "remove_stop", "index": int(remove.group(1)) - 1}
    for known_stop in context.get("stops", []):
        name = str(known_stop.get("name", "")).strip()
        if name and re.search(rf"(?:remove|delete|drop)\s+(?:stop|place)?\s*{re.escape(name)}\b", text, flags=re.IGNORECASE):
            try:
                idx = [str(stop.get("name", "")).lower() for stop in context.get("stops", [])].index(name.lower())
            except ValueError:
                continue
            return {"intent": "modify_trip", "operation": "remove_stop", "index": idx}

    destination_match = re.search(r"(?:change|set|make)\s+destination\s+(?:to|as)\s+(.+)$", text, flags=re.IGNORECASE)
    if destination_match:
        return {"intent": "modify_trip", "operation": "set_destination", "place": destination_match.group(1).strip().rstrip(".")}
    origin_match = re.search(r"(?:change|set|make)\s+origin\s+(?:to|as)\s+(.+)$", text, flags=re.IGNORECASE)
    if origin_match:
        return {"intent": "modify_trip", "operation": "set_origin", "place": origin_match.group(1).strip().rstrip(".")}

    # Natural-language stop edits: "add goa", "add Goa stop",
    # "add stop at Goa", "include Goa in the trip", etc.
    add_at_match = re.search(r"(?:add|include|insert)\s+(?:a\s+)?(?:stop|waypoint)\s+(?:at|in)\s+(.+)$", text, flags=re.IGNORECASE)
    if add_at_match:
        return {"intent": "modify_trip", "operation": "add_stop", "place": add_at_match.group(1).strip().rstrip(".")}

    add_match = re.search(r"(?:add|include|insert)\s+(?:a\s+)?(?:stop|waypoint)?\s*(?:at|in)?\s*(.+?)(?:\s+(?:to|into|my)\s+(?:the\s+)?trip|\s+(?:as|as a)\s+(?:stop|waypoint)|$)", text, flags=re.IGNORECASE)
    if add_match and any(k in lower for k in ["stop", "trip", "via", "add", "include", "insert"]):
        place = add_match.group(1).strip().rstrip(".")
        place = re.sub(r"^(?:stop|waypoint)\s+", "", place, flags=re.IGNORECASE).strip()
        place = re.sub(r"\s+(?:stop|waypoint)$", "", place, flags=re.IGNORECASE).strip()
        if place:
            return {"intent": "modify_trip", "operation": "add_stop", "place": place}

    # Charging-stop recommendations must use the deterministic EV planner,
    # not generic OSM POI proximity.
    if re.search(r"\b(?:recommend|suggest|show)\b.*\b(?:charging|charger)\s+stop\b|\b(?:recommended|best|nearest)\s+(?:charging|charger)\b|\bfind\s+(?:me\s+)?(?:a\s+)?(?:charging|charger)\s+stop\b", lower):
        return {"intent": "recommend_charger"}

    poi_category = None
    for candidate in ["restaurant", "restaurants", "cafe", "hotel", "hotels", "hospital", "pharmacy", "fuel", "supermarket", "convenience", "tourist attraction", "tourist attractions", "tourist place", "tourist places", "tourists places", "tourist spot", "tourist spots", "places to visit", "attractions", "parking", "charging"]:
        if candidate in lower:
            poi_category = candidate
            break
    if poi_category:
        scope = "route"
        if "charging stop" in lower or "charger stop" in lower:
            scope = "charging_stop"
        elif "stop" in lower:
            scope = "stop"
        index = None
        for stop_index, stop in enumerate(context.get("stops", [])):
            stop_name = str(stop.get("name", "")).strip()
            if stop_name and stop_name.lower() in lower:
                index = stop_index
                scope = "stop"
                break
        ordinal_pattern = r"(\d+|\d+(?:st|nd|rd|th)|first|second|third|fourth|fifth)"
        match = re.search(
            rf"(?:{ordinal_pattern})\s+(?:charging|charger)\s+stop",
            lower,
        )
        if not match:
            match = re.search(
                rf"(?:stop|charging stop)\s*(?:number\s*)?{ordinal_pattern}",
                lower,
            )
        if match:
            raw = match.group(1)
            ordinal_index = {"first": 0, "second": 1, "third": 2, "fourth": 3, "fifth": 4}
            if raw in ordinal_index:
                index = ordinal_index[raw]
            elif raw[:-2].isdigit() and raw[-2:] in {"st", "nd", "rd", "th"}:
                index = int(raw[:-2]) - 1
            elif raw.isdigit():
                index = int(raw) - 1
            else:
                index = 0
        radius = _number(text, [r"within\s*(\d+(?:\.\d+)?)\s*km", r"radius\s*(?:of|=)\s*(\d+(?:\.\d+)?)\s*km"])
        normalized_category = "tourist_attraction" if poi_category in {"tourist attraction", "tourist attractions", "tourist place", "tourist places", "tourists places", "tourist spot", "tourist spots", "places to visit", "attractions"} else poi_category.replace(" ", "_")
        return {"intent": "find_pois", "category": normalized_category, "scope": scope, "index": index, "radius_km": radius or 3.0}

    ev_requested = any(k in lower for k in ["ev", "electric", "charge", "charging stop", "battery", "charger"])
    places = extract_places(text)
    if len(places) >= 2:
        return {"intent": "plan_trip", "places": places, "ev_required": ev_requested}

    if "distance" in lower or "drive" in lower or "route" in lower or "time" in lower:
        return {"intent": "route", "places": places}

    if context.get("stops") and any(k in lower for k in ["plan", "replan", "recalculate", "continue"]):
        return {"intent": "plan_trip", "places": [s["name"] for s in context["stops"]], "ev_required": ev_requested}

    return {"intent": "context" if context.get("stops") else "geocode", "place": text}


def extract_places(text: str) -> list[str]:
    match = re.search(r"(?:from|between)\s+(.+?)\s+(?:to|and)\s+(.+)$", text, flags=re.IGNORECASE)
    if match:
        first = match.group(1).strip(" .")
        rest = match.group(2).strip(" .")
        via_match = re.split(r"\s+(?:via|through|with stop at|stopping at)\s+", rest, maxsplit=1, flags=re.IGNORECASE)
        if len(via_match) == 2:
            dest, middle = via_match[0], via_match[1]
            middle_parts = [p.strip() for p in re.split(r"\s*,\s*|\s+and\s+", middle) if p.strip()]
            return [first] + middle_parts + [dest]
        return [first, rest]

    arrow = re.split(r"\s*(?:->|→)\s*", text)
    if len(arrow) >= 2:
        return [p.strip() for p in arrow if p.strip()]
    return []
