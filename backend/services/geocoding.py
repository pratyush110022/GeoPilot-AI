from __future__ import annotations

import os

import httpx

from services.http_utils import request


NOMINATIM_URL = os.getenv("NOMINATIM_URL", "https://nominatim.openstreetmap.org/search")
HEADERS = {
    "User-Agent": "GeoPilot-AI/2.0 (portfolio project)",
    "Accept": "application/json",
}


async def search_places(query: str, limit: int = 5):
    query = query.strip()
    if not query:
        return []

    params = {
        "q": query,
        "format": "jsonv2",
        "limit": max(1, min(limit, 20)),
        "addressdetails": 1,
    }
    response = await request(
        "GET",
        NOMINATIM_URL,
        timeout=15.0,
        headers=HEADERS,
        params=params,
    )
    if response.status_code != 200:
        raise RuntimeError(f"Nominatim returned {response.status_code}: {response.text[:500]}")
    data = response.json()

    results = []
    for item in data:
        address = item.get("address", {})
        results.append({
            "display_name": item.get("display_name", ""),
            "latitude": float(item["lat"]),
            "longitude": float(item["lon"]),
            "type": item.get("type"),
            "city": address.get("city") or address.get("town") or address.get("municipality") or address.get("village"),
            "state": address.get("state"),
            "country": address.get("country"),
        })
    return results
