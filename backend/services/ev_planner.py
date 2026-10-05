from dataclasses import dataclass
from typing import Optional


# ============================================================
# EV Trip Planner
# ============================================================


@dataclass
class ChargingStop:
    charger: dict
    distance_from_previous_stop_km: float
    route_position_percent: float
    battery_arrival_percent: float
    battery_departure_percent: float
    charge_added_percent: float


# ============================================================
# Utility Functions
# ============================================================

def battery_percent_for_distance(
    distance_km: float,
    max_range_km: float,
) -> float:

    if max_range_km <= 0:
        raise ValueError(
            "Maximum range must be greater than zero."
        )

    return (
        distance_km
        / max_range_km
        * 100
    )


def distance_for_battery_percent(
    battery_percent: float,
    max_range_km: float,
) -> float:

    if max_range_km <= 0:
        raise ValueError(
            "Maximum range must be greater than zero."
        )

    return (
        battery_percent
        / 100
        * max_range_km
    )


# ============================================================
# Charger Feasibility
# ============================================================

def _charger_distance(
    charger: dict,
    route_distance_km: float,
) -> Optional[float]:

    position = charger.get(
        "route_position_percent"
    )

    if position is None:
        return None

    try:
        position = float(position)
    except (TypeError, ValueError):
        return None

    if position <= 0 or position >= 100:
        return None

    return (
        position
        / 100
        * route_distance_km
    )


def _can_complete_from_position(
    chargers: list[dict],
    current_distance_km: float,
    current_battery_percent: float,
    route_distance_km: float,
    max_range_km: float,
    reserve_percent: float,
    target_charge_percent: float,
    used_charger_ids: frozenset[str] = frozenset(),
    memo: Optional[dict] = None,
) -> bool:
    """
    Check whether the trip can still be completed from the current
    route position.

    This is a deterministic look-ahead check. It does not simply ask
    whether a charger is reachable; it asks whether the vehicle can
    continue from that charger to the destination or through additional
    reachable chargers while maintaining the reserve.

    Returns True if at least one valid continuation exists.
    """

    if memo is None:
        memo = {}

    # Destination is reachable from the current position.
    remaining_distance_km = (
        route_distance_km
        - current_distance_km
    )

    usable_battery_percent = (
        current_battery_percent
        - reserve_percent
    )

    if usable_battery_percent < 0:
        return False

    reachable_distance_km = (
        distance_for_battery_percent(
            usable_battery_percent,
            max_range_km,
        )
    )

    if remaining_distance_km <= reachable_distance_km:
        return True

    # Avoid repeated calculations for the same state.
    state_key = (
        round(current_distance_km, 4),
        round(current_battery_percent, 4),
        tuple(sorted(used_charger_ids)),
    )

    if state_key in memo:
        return memo[state_key]

    # The current position cannot reach the destination, so find
    # a future charger that can be reached while preserving reserve.
    future_candidates = []

    maximum_reachable_distance = (
        current_distance_km
        + reachable_distance_km
    )

    for charger in chargers:

        charger_id = str(
            charger.get("id")
        )

        if charger_id in used_charger_ids:
            continue

        charger_distance_km = _charger_distance(
            charger,
            route_distance_km,
        )

        if charger_distance_km is None:
            continue

        if charger_distance_km <= current_distance_km:
            continue

        if charger_distance_km > maximum_reachable_distance:
            continue

        distance_to_charger_km = (
            charger_distance_km
            - current_distance_km
        )

        battery_used_percent = (
            battery_percent_for_distance(
                distance_to_charger_km,
                max_range_km,
            )
        )

        battery_arrival_percent = (
            current_battery_percent
            - battery_used_percent
        )

        # Charging target remains user-configurable.
        battery_departure_percent = max(
            target_charge_percent,
            battery_arrival_percent,
        )

        future_candidates.append(
            (
                charger_distance_km,
                charger,
                battery_departure_percent,
            )
        )

    # Try furthest viable chargers first. This still minimizes
    # unnecessary stops, but only after feasibility is established.
    future_candidates.sort(
        key=lambda item: item[0],
        reverse=True,
    )

    for (
        charger_distance_km,
        charger,
        battery_departure_percent,
    ) in future_candidates:

        charger_id = str(
            charger.get("id")
        )

        next_used_ids = (
            used_charger_ids
            | frozenset({charger_id})
        )

        if _can_complete_from_position(
            chargers=chargers,
            current_distance_km=charger_distance_km,
            current_battery_percent=battery_departure_percent,
            route_distance_km=route_distance_km,
            max_range_km=max_range_km,
            reserve_percent=reserve_percent,
            target_charge_percent=target_charge_percent,
            used_charger_ids=next_used_ids,
            memo=memo,
        ):
            memo[state_key] = True
            return True

    memo[state_key] = False
    return False


# ============================================================
# Find Best Feasible Charger
# ============================================================

def select_next_charger(
    chargers: list[dict],
    current_distance_km: float,
    current_battery_percent: float,
    route_distance_km: float,
    max_range_km: float,
    reserve_percent: float,
    target_charge_percent: float,
) -> Optional[dict]:

    usable_battery_percent = (
        current_battery_percent
        - reserve_percent
    )

    if usable_battery_percent <= 0:
        return None

    reachable_distance_km = (
        distance_for_battery_percent(
            usable_battery_percent,
            max_range_km,
        )
    )

    maximum_reachable_distance = (
        current_distance_km
        + reachable_distance_km
    )

    candidates = []

    for charger in chargers:

        position = charger.get(
            "route_position_percent"
        )

        if position is None:
            continue

        try:
            position = float(position)
        except (TypeError, ValueError):
            continue

        if position <= 0:
            continue

        if position >= 100:
            continue

        charger_distance_km = (
            position
            / 100
            * route_distance_km
        )

        # Charger must be ahead.
        if charger_distance_km <= current_distance_km:
            continue

        # Charger must be reachable while maintaining reserve.
        if charger_distance_km > maximum_reachable_distance:
            continue

        distance_to_charger_km = (
            charger_distance_km
            - current_distance_km
        )

        battery_used_percent = (
            battery_percent_for_distance(
                distance_to_charger_km,
                max_range_km,
            )
        )

        battery_arrival_percent = (
            current_battery_percent
            - battery_used_percent
        )

        # Keep the selected target charge user-configurable.
        battery_departure_percent = max(
            target_charge_percent,
            battery_arrival_percent,
        )

        # ----------------------------------------------------
        # SMART FEASIBILITY CHECK
        # ----------------------------------------------------
        #
        # Do not select a charger merely because it is reachable.
        # First check whether the trip remains solvable after
        # charging there.
        #
        # The check can use additional chargers if necessary.
        # This prevents a charger that looks close/comfortable
        # from creating a dead end later in the trip.
        # ----------------------------------------------------

        charger_id = str(
            charger.get("id")
        )

        if not _can_complete_from_position(
            chargers=chargers,
            current_distance_km=charger_distance_km,
            current_battery_percent=battery_departure_percent,
            route_distance_km=route_distance_km,
            max_range_km=max_range_km,
            reserve_percent=reserve_percent,
            target_charge_percent=target_charge_percent,
            used_charger_ids=frozenset({charger_id}),
            memo={},
        ):
            continue

        charger_copy = dict(charger)

        charger_copy[
            "_route_distance_km"
        ] = charger_distance_km

        charger_copy[
            "_battery_arrival_percent"
        ] = battery_arrival_percent

        charger_copy[
            "_battery_departure_percent"
        ] = battery_departure_percent

        candidates.append(
            charger_copy
        )

    if not candidates:
        return None

    # Among chargers that leave a valid continuation, prefer the
    # furthest one. This preserves the original goal of avoiding
    # unnecessary charging stops without sacrificing feasibility.
    candidates.sort(
        key=lambda charger:
        charger["_route_distance_km"],
        reverse=True,
    )

    return candidates[0]


# ============================================================
# Main EV Trip Planner
# ============================================================

def plan_ev_trip(
    route_distance_km: float,
    chargers: list[dict],
    max_range_km: float,
    starting_battery_percent: float,
    reserve_percent: float = 15.0,
    target_charge_percent: float = 80.0,
    battery_capacity_kwh: float | None = None,
    route_duration_minutes: float | None = None,
):

    # ========================================================
    # Validate
    # ========================================================

    if route_distance_km <= 0:
        raise ValueError(
            "Route distance must be greater than zero."
        )

    if max_range_km <= 0:
        raise ValueError(
            "Maximum range must be greater than zero."
        )

    if not 0 <= starting_battery_percent <= 100:
        raise ValueError(
            "Starting battery must be between 0 and 100."
        )

    if not 0 <= reserve_percent < 100:
        raise ValueError(
            "Reserve must be between 0 and 100."
        )

    if not 0 < target_charge_percent <= 100:
        raise ValueError(
            "Target charge must be between 0 and 100."
        )

    if target_charge_percent <= reserve_percent:
        raise ValueError(
            "Target charge must be greater than reserve."
        )

    # ========================================================
    # Total battery required
    # ========================================================

    total_battery_required_percent = (
        battery_percent_for_distance(
            route_distance_km,
            max_range_km,
        )
    )

    # ========================================================
    # Direct-trip check
    # ========================================================

    usable_start_battery = (
        starting_battery_percent
        - reserve_percent
    )

    direct_usable_range_km = (
        distance_for_battery_percent(
            max(
                usable_start_battery,
                0,
            ),
            max_range_km,
        )
    )

    if route_distance_km <= direct_usable_range_km:

        arrival_battery = (
            starting_battery_percent
            - total_battery_required_percent
        )

        return {
            "trip_possible": True,
            "requires_charging": False,
            "route_distance_km": round(
                route_distance_km,
                2,
            ),
            "total_battery_required_percent": round(
                total_battery_required_percent,
                2,
            ),
            "starting_battery_percent": round(
                starting_battery_percent,
                2,
            ),
            "destination_battery_percent": round(
                arrival_battery,
                2,
            ),
            "charging_stops": [],
            "message": (
                "Destination can be reached "
                "without charging."
            ),
        }

    # ========================================================
    # Prepare route chargers
    # ========================================================

    route_chargers = []

    for charger in chargers:

        position = charger.get(
            "route_position_percent"
        )

        if position is None:
            continue

        try:
            position = float(position)
        except (TypeError, ValueError):
            continue

        if position <= 0 or position >= 100:
            continue

        charger_copy = dict(charger)

        charger_copy[
            "_route_distance_km"
        ] = (
            position
            / 100
            * route_distance_km
        )

        route_chargers.append(
            charger_copy
        )

    route_chargers.sort(
        key=lambda charger:
        charger["_route_distance_km"]
    )

    # ========================================================
    # Planning State
    # ========================================================

    current_distance_km = 0.0

    current_battery_percent = (
        starting_battery_percent
    )

    charging_stops = []

    used_chargers = set()

    # ========================================================
    # Charging Loop
    # ========================================================

    max_iterations = (
        len(route_chargers) + 1
    )

    iteration = 0

    while current_distance_km < route_distance_km:

        iteration += 1

        if iteration > max_iterations:

            return {
                "trip_possible": False,
                "requires_charging": True,
                "route_distance_km": round(
                    route_distance_km,
                    2,
                ),
                "starting_battery_percent": round(
                    starting_battery_percent,
                    2,
                ),
                "charging_stops": charging_stops,
                "failure_reason": (
                    "EV planner exceeded the "
                    "maximum planning iterations."
                ),
            }

        # ----------------------------------------------------
        # Check whether destination is reachable
        # ----------------------------------------------------

        usable_battery_percent = (
            current_battery_percent
            - reserve_percent
        )

        if usable_battery_percent <= 0:

            return {
                "trip_possible": False,
                "requires_charging": True,
                "route_distance_km": round(
                    route_distance_km,
                    2,
                ),
                "starting_battery_percent": round(
                    starting_battery_percent,
                    2,
                ),
                "charging_stops": charging_stops,
                "failure_reason": (
                    "Battery reached reserve "
                    "before the destination."
                ),
            }

        reachable_distance_km = (
            distance_for_battery_percent(
                usable_battery_percent,
                max_range_km,
            )
        )

        remaining_distance_km = (
            route_distance_km
            - current_distance_km
        )

        if remaining_distance_km <= reachable_distance_km:

            battery_used = (
                battery_percent_for_distance(
                    remaining_distance_km,
                    max_range_km,
                )
            )

            destination_battery = (
                current_battery_percent
                - battery_used
            )

            return {
                "trip_possible": True,
                "requires_charging": (
                    len(charging_stops) > 0
                ),
                "route_distance_km": round(
                    route_distance_km,
                    2,
                ),
                "total_battery_required_percent": round(
                    total_battery_required_percent,
                    2,
                ),
                "starting_battery_percent": round(
                    starting_battery_percent,
                    2,
                ),
                "destination_battery_percent": round(
                    destination_battery,
                    2,
                ),
                "charging_stops": charging_stops,
                "message": (
                    "Trip can be completed with "
                    "the selected charging stops."
                ),
            }

        # ----------------------------------------------------
        # Find next reachable AND feasible charger
        # ----------------------------------------------------

        available_chargers = []

        for charger in route_chargers:

            charger_id = str(
                charger.get("id")
            )

            if charger_id in used_chargers:
                continue

            available_chargers.append(
                charger
            )

        next_charger = (
            select_next_charger(
                chargers=available_chargers,
                current_distance_km=(
                    current_distance_km
                ),
                current_battery_percent=(
                    current_battery_percent
                ),
                route_distance_km=(
                    route_distance_km
                ),
                max_range_km=max_range_km,
                reserve_percent=reserve_percent,
                target_charge_percent=(
                    target_charge_percent
                ),
            )
        )

        if next_charger is None:

            return {
                "trip_possible": False,
                "requires_charging": True,
                "route_distance_km": round(
                    route_distance_km,
                    2,
                ),
                "starting_battery_percent": round(
                    starting_battery_percent,
                    2,
                ),
                "charging_stops": charging_stops,
                "failure_reason": (
                    "No reachable Tata charger "
                    "was found that leaves a "
                    "feasible continuation to "
                    "the destination."
                ),
            }

        # ----------------------------------------------------
        # Charger distance
        # ----------------------------------------------------

        charger_distance_km = (
            next_charger[
                "_route_distance_km"
            ]
        )

        distance_from_previous_stop = (
            charger_distance_km
            - current_distance_km
        )

        if distance_from_previous_stop <= 0:

            return {
                "trip_possible": False,
                "requires_charging": True,
                "route_distance_km": round(
                    route_distance_km,
                    2,
                ),
                "charging_stops": charging_stops,
                "failure_reason": (
                    "Invalid charger route position."
                ),
            }

        # ----------------------------------------------------
        # Battery consumed
        # ----------------------------------------------------

        battery_used = (
            battery_percent_for_distance(
                distance_from_previous_stop,
                max_range_km,
            )
        )

        battery_arrival = (
            current_battery_percent
            - battery_used
        )

        # ----------------------------------------------------
        # Charge vehicle
        # ----------------------------------------------------

        battery_departure = max(
            target_charge_percent,
            battery_arrival,
        )

        charge_added = (
            battery_departure
            - battery_arrival
        )

        # ----------------------------------------------------
        # Remove internal calculation fields
        # ----------------------------------------------------

        charger_result = dict(
            next_charger
        )

        charger_result.pop(
            "_route_distance_km",
            None,
        )

        charger_result.pop(
            "_battery_arrival_percent",
            None,
        )

        charger_result.pop(
            "_battery_departure_percent",
            None,
        )

        # ----------------------------------------------------
        # Save charging stop
        # ----------------------------------------------------

        route_position_percent = round(
            float(next_charger["route_position_percent"]),
            2,
        )
        estimated_power_kw = next_charger.get("estimated_power_kw")
        energy_to_target_kwh = None
        estimated_charging_time_minutes = None
        if battery_capacity_kwh and battery_capacity_kwh > 0:
            energy_to_target_kwh = round(
                battery_capacity_kwh * max(charge_added, 0) / 100,
                2,
            )
            if estimated_power_kw and estimated_power_kw > 0:
                estimated_charging_time_minutes = round(
                    energy_to_target_kwh / estimated_power_kw * 60,
                    1,
                )

        time_to_reach_minutes = None
        if route_duration_minutes is not None:
            time_to_reach_minutes = round(
                route_duration_minutes * route_position_percent / 100,
                1,
            )

        charging_stops.append(
            {
                "charger": charger_result,
                "distance_from_previous_stop_km": round(distance_from_previous_stop, 2),
                "distance_from_start_km": round(charger_distance_km, 2),
                "route_position_percent": route_position_percent,
                "battery_arrival_percent": round(battery_arrival, 2),
                "battery_departure_percent": round(battery_departure, 2),
                "charge_added_percent": round(charge_added, 2),
                "time_to_reach_minutes": time_to_reach_minutes,
                "energy_to_target_kwh": energy_to_target_kwh,
                "estimated_charging_time_minutes": estimated_charging_time_minutes,
            }
        )

        # ----------------------------------------------------
        # Update state
        # ----------------------------------------------------

        current_distance_km = (
            charger_distance_km
        )

        current_battery_percent = (
            battery_departure
        )

        used_chargers.add(
            str(
                next_charger.get("id")
            )
        )

    # ========================================================
    # Fallback
    # ========================================================

    return {
        "trip_possible": False,
        "requires_charging": True,
        "route_distance_km": round(
            route_distance_km,
            2,
        ),
        "starting_battery_percent": round(
            starting_battery_percent,
            2,
        ),
        "charging_stops": charging_stops,
        "failure_reason": (
            "No valid charging plan was found."
        ),
    }
