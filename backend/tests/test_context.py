from services.trip_context import TripContextStore


def test_store_roundtrip():
    store = TripContextStore()
    created = store.create()
    created.reserve_percent = 20
    store.save(created)
    loaded = store.get(created.session_id)
    assert loaded.session_id == created.session_id
    assert loaded.reserve_percent == 20
