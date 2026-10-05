from services.overpass_pois import parse_pois


def test_parse_node_and_way():
    data = {
        "elements": [
            {"type": "node", "id": 1, "lat": 12.3, "lon": 77.5, "tags": {"name": "Cafe A", "amenity": "cafe"}},
            {"type": "way", "id": 2, "center": {"lat": 12.4, "lon": 77.6}, "tags": {"name": "Hotel B", "tourism": "hotel"}},
        ]
    }
    rows = parse_pois(data)
    assert len(rows) == 2
    assert {row["category"] for row in rows} == {"cafe", "hotel"}
