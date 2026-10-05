from services.ev_planner import plan_ev_trip


def charger(cid, pos):
    return {
        "id": cid,
        "name": f"Charger {cid}",
        "latitude": 12.0,
        "longitude": 77.0,
        "chargerType": "50 kW",
        "route_position_percent": pos,
    }


def test_trip_that_fits_needs_no_charge():
    plan = plan_ev_trip(
        route_distance_km=100,
        chargers=[charger("1", 50)],
        max_range_km=150,
        starting_battery_percent=100,
        reserve_percent=15,
        target_charge_percent=80,
    )
    assert plan["trip_possible"] is True
    assert plan["charging_stops"] == []


def test_route_can_use_feasible_charger():
    plan = plan_ev_trip(
        route_distance_km=240,
        chargers=[charger("1", 45), charger("2", 80)],
        max_range_km=150,
        starting_battery_percent=100,
        reserve_percent=15,
        target_charge_percent=80,
    )
    assert plan["trip_possible"] is True
    assert len(plan["charging_stops"]) >= 1
