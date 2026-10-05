from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, field
from threading import Lock
from typing import Any, Optional
from uuid import uuid4


@dataclass
class PlaceContext:
    name: str
    display_name: str
    latitude: float
    longitude: float
    role: str = "stop"


@dataclass
class VehicleContext:
    make: Optional[str] = None
    model: Optional[str] = None
    max_range_km: Optional[float] = None
    battery_capacity_kwh: Optional[float] = None
    current_battery_percent: Optional[float] = None
    source: str = "user_declared"

    def has_core_range_context(self) -> bool:
        return (
            self.max_range_km is not None
            and self.current_battery_percent is not None
        )


@dataclass
class TripContext:
    session_id: str
    stops: list[PlaceContext] = field(default_factory=list)
    vehicle: Optional[VehicleContext] = None
    reserve_percent: float = 15.0
    target_charge_percent: float = 80.0
    corridor_km: float = 5.0
    route: Optional[dict[str, Any]] = None
    chargers: list[dict[str, Any]] = field(default_factory=list)
    pois: list[dict[str, Any]] = field(default_factory=list)
    ev_plan: Optional[dict[str, Any]] = None
    last_action: Optional[dict[str, Any]] = None
    turn_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def trip_names(self) -> list[str]:
        return [stop.name for stop in self.stops]

    @property
    def has_route(self) -> bool:
        return bool(self.route and self.route.get("geometry"))

    def clear_derived(self) -> None:
        self.route = None
        self.chargers = []
        self.pois = []
        self.ev_plan = None


class TripContextStore:
    """Thread-safe in-memory conversation store for local/single-instance use."""

    def __init__(self) -> None:
        self._contexts: dict[str, TripContext] = {}
        self._lock = Lock()

    def create(self) -> TripContext:
        session_id = str(uuid4())
        context = TripContext(session_id=session_id)
        with self._lock:
            self._contexts[session_id] = context
        return deepcopy(context)

    def get(self, session_id: str) -> TripContext:
        with self._lock:
            context = self._contexts.get(session_id)
            if context is None:
                context = TripContext(session_id=session_id)
                self._contexts[session_id] = context
            return deepcopy(context)

    def save(self, context: TripContext) -> TripContext:
        with self._lock:
            self._contexts[context.session_id] = deepcopy(context)
        return deepcopy(context)

    def delete(self, session_id: str) -> bool:
        with self._lock:
            return self._contexts.pop(session_id, None) is not None

    def size(self) -> int:
        with self._lock:
            return len(self._contexts)
