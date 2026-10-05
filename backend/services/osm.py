import asyncio
import httpx

from services.http_utils import request


OVERPASS_URL = "https://overpass-api.de/api/interpreter"

HEADERS = {
    "User-Agent": "GeoPilot-AI/0.1 (portfolio project)",
    "Accept": "application/json",
}


# ============================================================
# Parse Charging Stations
# ============================================================

def parse_charging_stations(data):
    stations = []

    for element in data.get("elements", []):
        tags = element.get("tags", {})

        stations.append(
            {
                "osm_id": element.get("id"),
                "osm_type": element.get("type"),
                "name": tags.get("name"),
                "latitude": element.get("lat"),
                "longitude": element.get("lon"),
                "operator": tags.get("operator"),
                "capacity": tags.get("capacity"),
                "socket": tags.get("socket"),
                "socket:type2": tags.get("socket:type2"),
                "socket:ccs2": tags.get("socket:ccs2"),
                "website": tags.get("website"),
                "opening_hours": tags.get("opening_hours"),
            }
        )

    return stations


# ============================================================
# Generic Overpass Request
# ============================================================

async def query_overpass(query: str):
    response = await request(
        "POST",
        OVERPASS_URL,
        timeout=httpx.Timeout(
            connect=10.0,
            read=60.0,
            write=30.0,
            pool=10.0,
        ),
        headers={
            **HEADERS,
            "Content-Type": "application/x-www-form-urlencoded",
        },
        content=query.encode("utf-8"),
    )

    if response.status_code != 200:
        raise Exception(
            f"Overpass API returned "
            f"{response.status_code}: "
            f"{response.text[:1000]}"
        )

    return response.json()


# ============================================================
# Charging Stations Around Point
# ============================================================

async def get_charging_stations(
    latitude: float,
    longitude: float,
    radius: int,
):
    """
    Find charging stations around a point.
    """

    query = f"""
    [out:json][timeout:25];

    node["amenity"="charging_station"]
      (around:{radius},{latitude},{longitude});

    out body;
    """

    data = await query_overpass(query)

    return parse_charging_stations(data)


# ============================================================
# Query One Bounding Box Tile
# ============================================================

async def query_bbox_tile(
    south: float,
    west: float,
    north: float,
    east: float,
):
    """
    Query one small bounding-box tile.
    """

    query = f"""
    [out:json][timeout:30];

    node["amenity"="charging_station"]
      ({south},{west},{north},{east});

    out body;
    """

    data = await query_overpass(query)

    return parse_charging_stations(data)


# ============================================================
# Charging Stations Inside Bounding Box
# ============================================================

async def get_charging_stations_in_bbox(
    south: float,
    west: float,
    north: float,
    east: float,
):
    """
    Find charging stations inside a bounding box.

    Large areas are split into smaller tiles to reduce
    Overpass timeout and load problems.
    """

    # Approximately 20 km x 20 km tiles
    tile_size = 0.20

    all_stations = []

    current_south = south

    while current_south < north:

        current_north = min(
            current_south + tile_size,
            north,
        )

        current_west = west

        while current_west < east:

            current_east = min(
                current_west + tile_size,
                east,
            )

            print(
                f"Querying tile: "
                f"{current_south},"
                f"{current_west},"
                f"{current_north},"
                f"{current_east}"
            )

            try:

                stations = await query_bbox_tile(
                    south=current_south,
                    west=current_west,
                    north=current_north,
                    east=current_east,
                )

                print(
                    f"Found {len(stations)} stations"
                )

                all_stations.extend(stations)

            except Exception as e:

                print(
                    f"Tile failed: {e}"
                )

            # Avoid sending requests too quickly
            await asyncio.sleep(1)

            current_west = current_east

        current_south = current_north

    # ========================================================
    # Remove Duplicate OSM Records
    # ========================================================

    unique_stations = {}

    for station in all_stations:

        osm_id = station.get("osm_id")

        if osm_id is not None:
            unique_stations[osm_id] = station

    print(
        f"Total unique charging stations: "
        f"{len(unique_stations)}"
    )

    return list(unique_stations.values())