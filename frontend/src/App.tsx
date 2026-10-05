import { useEffect, useMemo, useRef, useState } from "react";
import type { KeyboardEvent } from "react";
import {
  LngLatBounds,
  Map as MapLibreMap,
  Marker,
  NavigationControl,
  Popup,
} from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import "./App.css";

const BACKEND_URL = import.meta.env.VITE_BACKEND_URL || "http://localhost:8000";
const SESSION_KEY = "geopilot-session-id";

type Place = {
  name: string;
  display_name: string;
  latitude: number;
  longitude: number;
  role: string;
};

type Vehicle = {
  make?: string | null;
  model?: string | null;
  max_range_km?: number | null;
  battery_capacity_kwh?: number | null;
  current_battery_percent?: number | null;
  source?: string;
};

type Charger = {
  id?: string;
  name?: string;
  city?: string;
  state?: string;
  address?: string;
  latitude: number;
  longitude: number;
  chargerType?: string;
  cpoName?: string;
  customerCategory?: string;
  megaChargers?: string;
  distance_from_route_km?: number;
  route_position_percent?: number;
  socket_type?: string;
  charging_speed?: string;
  estimated_power_kw?: number | null;
  brand_key?: string;
  source?: string;
};

type POI = {
  osm_id?: number;
  osm_type?: string;
  name: string;
  category: string;
  latitude: number;
  longitude: number;
  operator?: string | null;
  cuisine?: string | null;
  website?: string | null;
  phone?: string | null;
  opening_hours?: string | null;
  address?: string | null;
  distance_from_route_km?: number;
  route_position_percent?: number;
  distance_from_reference_km?: number;
  source?: string;
};

type ChargingStop = {
  charger: Charger;
  distance_from_previous_stop_km: number;
  distance_from_start_km: number;
  route_position_percent: number;
  battery_arrival_percent: number;
  battery_departure_percent: number;
  charge_added_percent: number;
  time_to_reach_minutes?: number | null;
  energy_to_target_kwh?: number | null;
  estimated_charging_time_minutes?: number | null;
};

type EVPlan = {
  trip_possible: boolean;
  requires_charging?: boolean;
  route_distance_km: number;
  total_battery_required_percent?: number;
  starting_battery_percent: number;
  destination_battery_percent?: number;
  charging_stops: ChargingStop[];
  message?: string;
  failure_reason?: string;
};

type Route = {
  distance_km: number;
  duration_minutes: number;
  geometry: { type: "LineString"; coordinates: [number, number][] };
  legs?: Array<{
    from_stop_index: number;
    to_stop_index: number;
    distance_km: number;
    duration_minutes: number;
  }>;
  stop_positions?: Array<{
    stop_index: number;
    name: string;
    latitude: number;
    longitude: number;
    distance_from_start_km: number;
    route_position_percent: number;
  }>;
  waypoint_count?: number;
};

type Context = {
  session_id: string;
  stops: Place[];
  vehicle?: Vehicle | null;
  reserve_percent: number;
  target_charge_percent: number;
  corridor_km: number;
  route?: Route | null;
  chargers: Charger[];
  pois: POI[];
  ev_plan?: EVPlan | null;
  turn_count: number;
};

type ChatMessage = {
  role: "user" | "assistant";
  text: string;
};

type ChatResponse = {
  session_id: string;
  reply: string;
  result: Record<string, unknown>;
  context: Context;
};

function formatNumber(value: unknown, digits = 1) {
  const number = Number(value);
  return Number.isFinite(number) ? number.toFixed(digits) : "—";
}

function formatMinutes(value: unknown) {
  const minutes = Number(value);
  if (!Number.isFinite(minutes)) return "—";
  if (minutes < 60) return `${Math.round(minutes)} min`;
  const hours = Math.floor(minutes / 60);
  const mins = Math.round(minutes % 60);
  return mins ? `${hours}h ${mins}m` : `${hours}h`;
}

function batteryEnergyPercent(vehicle: Vehicle | null | undefined, percent: number | null | undefined) {
  const capacity = Number(vehicle?.battery_capacity_kwh);
  const value = Number(percent);
  if (!Number.isFinite(capacity) || !Number.isFinite(value)) return null;
  return capacity * value / 100;
}

function brandLogoPath(charger: Charger) {
  return `/icons/${charger.brand_key || "generic-ev"}.png`;
}

function categoryIconPath(category: string) {
  const key = category.replaceAll(" ", "_").toLowerCase();
  const map: Record<string, string> = {
    restaurant: "/category-icons/restaurant.svg",
    cafe: "/category-icons/cafe.svg",
    hotel: "/category-icons/hotel.svg",
    hospital: "/category-icons/hospital.svg",
    pharmacy: "/category-icons/pharmacy.svg",
    fuel: "/category-icons/fuel.svg",
    supermarket: "/category-icons/supermarket.svg",
    convenience: "/category-icons/convenience.svg",
    tourist_attraction: "/category-icons/tourist.svg",
    parking: "/category-icons/parking.svg",
    ev_charging: "/favicon.svg",
  };
  return map[key] || "/category-icons/place.svg";
}

function chargerSpeed(charger: Charger) {
  if (charger.charging_speed) return charger.charging_speed;
  const socket = String(charger.socket_type || charger.chargerType || "").toUpperCase();
  const power = Number(charger.estimated_power_kw);
  if (socket.includes("CCS") || socket.includes("CHADEMO") || (Number.isFinite(power) && power >= 25)) return "DC Fast";
  if (socket.includes("AC") || socket.includes("TYPE 2") || (Number.isFinite(power) && power > 0)) return "AC / Regular";
  return "Charger type not listed";
}

function estimatedChargeMinutes(charger: Charger, energyKwh: number | null) {
  if (energyKwh == null) return null;
  const power = Number(charger.estimated_power_kw);
  if (!Number.isFinite(power) || power <= 0) return null;
  return (energyKwh / power) * 60;
}

function totalEstimatedChargingMinutes(plan: EVPlan | null | undefined) {
  return (plan?.charging_stops || []).reduce((sum, stop) => {
    const value = Number(stop.estimated_charging_time_minutes);
    return sum + (Number.isFinite(value) ? value : 0);
  }, 0);
}

function poiEmoji(category: string) {
  const icons: Record<string, string> = {
    restaurant: "🍴",
    cafe: "☕",
    hotel: "🏨",
    hospital: "🏥",
    pharmacy: "💊",
    fuel: "⛽",
    supermarket: "🛒",
    convenience: "🏪",
    tourist_attraction: "📍",
    parking: "🅿️",
    ev_charging: "⚡",
  };
  return icons[category] || "•";
}

function escapeHtml(value: string) {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function App() {
  const mapContainerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const markersRef = useRef<Marker[]>([]);

  const [sessionId, setSessionId] = useState(() => localStorage.getItem(SESSION_KEY) || "");
  const sessionIdRef = useRef(sessionId);
  const [context, setContext] = useState<Context | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      role: "assistant",
      text: "Hi — I’m GeoPilot AI. Ask me to plan a trip, add stops, find restaurants or hotels, or run an EV battery what-if.",
    },
  ]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [thinkingIndex, setThinkingIndex] = useState(0);
  const [backendStatus, setBackendStatus] = useState<"checking" | "online" | "offline">("checking");
  const [showPlanner, setShowPlanner] = useState(false);
  const [origin, setOrigin] = useState("Bengaluru");
  const [destination, setDestination] = useState("Mysuru");
  const [waypoints, setWaypoints] = useState<string[]>([]);
  const [vehicleModel, setVehicleModel] = useState("Tata Nexon EV");
  const [vehicleRange, setVehicleRange] = useState("400");
  const [battery, setBattery] = useState("90");
  const [batteryPack, setBatteryPack] = useState("50");
  const [reserve, setReserve] = useState("15");
  const [targetCharge, setTargetCharge] = useState("80");
  const [corridor, setCorridor] = useState("5");
  const [selectedPOI, setSelectedPOI] = useState<POI | null>(null);
  const [contextExpanded, setContextExpanded] = useState(false);

  const canSend = input.trim().length > 0 && !loading;
  const thinkingMessages = [
    "Understanding your request…",
    "Checking trip context…",
    "Calculating route and EV feasibility…",
    "Querying verified spatial data…",
    "Preparing the map and answer…",
  ];

  useEffect(() => {
    if (!loading) {
      setThinkingIndex(0);
      return;
    }
    const timer = window.setInterval(() => setThinkingIndex((value) => (value + 1) % thinkingMessages.length), 1250);
    return () => window.clearInterval(timer);
  }, [loading]);

  const summary = useMemo(() => {
    if (!context) return null;
    return {
      trip: context.stops.map((s) => s.name).join(" → "),
      distance: context.route ? `${formatNumber(context.route.distance_km, 0)} km` : "—",
      duration: context.route ? `${formatNumber(context.route.duration_minutes, 0)} min` : "—",
      charging: context.ev_plan ? context.ev_plan.charging_stops.length : 0,
      pois: context.pois.length,
    };
  }, [context]);

  useEffect(() => {
    const map = new MapLibreMap({
      container: mapContainerRef.current!,
      style: {
        version: 8,
        sources: {
          osm: {
            type: "raster",
            tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
            tileSize: 256,
            attribution: "© OpenStreetMap contributors",
          },
        },
        layers: [{ id: "osm", type: "raster", source: "osm" }],
      },
      center: [78.9629, 20.5937],
      zoom: 4.8,
    });
    map.addControl(new NavigationControl(), "bottom-right");
    mapRef.current = map;

    map.on("load", () => checkBackend());
    return () => {
      markersRef.current.forEach((marker) => marker.remove());
      markersRef.current = [];
      map.remove();
      mapRef.current = null;
    };
  }, []);

  useEffect(() => {
    sessionIdRef.current = sessionId;
    if (!sessionId) return;
    localStorage.setItem(SESSION_KEY, sessionId);
    void loadSession(sessionId);
  }, [sessionId]);

  useEffect(() => {
    drawContext(context);
  }, [context]);

  async function checkBackend() {
    try {
      const response = await fetch(`${BACKEND_URL}/health`);
      setBackendStatus(response.ok ? "online" : "offline");
    } catch {
      setBackendStatus("offline");
    }
  }

  async function loadSession(id: string) {
    try {
      const response = await fetch(`${BACKEND_URL}/session/${encodeURIComponent(id)}`);
      if (!response.ok) return;
      const data = (await response.json()) as Context;
      setContext(data);
    } catch {
      // Keep the local chat usable when the session has expired.
    }
  }

  function clearMarkers() {
    markersRef.current.forEach((marker) => marker.remove());
    markersRef.current = [];
  }

  function addMarker(
    longitude: number,
    latitude: number,
    html: string,
    popupHtml?: string,
  ) {
    const marker = new Marker({ element: markerElement(html) })
      .setLngLat([longitude, latitude])
      .addTo(mapRef.current!);
    if (popupHtml) {
      marker.setPopup(new Popup({ offset: 18, maxWidth: "340px" }).setHTML(popupHtml));
    }
    markersRef.current.push(marker);
  }

  function markerElement(text: string) {
    const el = document.createElement("div");
    el.className = "geo-marker";
    el.innerHTML = text;
    return el;
  }

  function drawContext(current: Context | null) {
    const map = mapRef.current;
    if (!map || !current) return;

    const ready = map.loaded();
    if (!ready) {
      map.once("load", () => drawContext(current));
      return;
    }

    clearMarkers();

    if (map.getLayer("trip-route")) map.removeLayer("trip-route");
    if (map.getLayer("trip-route-outline")) map.removeLayer("trip-route-outline");
    if (map.getSource("trip-route")) map.removeSource("trip-route");

    const route = current.route;
    const routeCoordinates = route?.geometry?.coordinates;
    if (route && routeCoordinates && routeCoordinates.length > 1) {
      map.addSource("trip-route", {
        type: "geojson",
        data: { type: "Feature", properties: {}, geometry: route.geometry },
      });
      map.addLayer({
        id: "trip-route-outline",
        type: "line",
        source: "trip-route",
        paint: { "line-color": "#ffffff", "line-width": 8, "line-opacity": 0.9 },
      });
      map.addLayer({
        id: "trip-route",
        type: "line",
        source: "trip-route",
        paint: { "line-color": "#2563eb", "line-width": 5, "line-opacity": 0.86 },
      });

      const bounds = new LngLatBounds();
      routeCoordinates.forEach((coordinate) => bounds.extend(coordinate));
      map.fitBounds(bounds, { padding: { top: 80, bottom: 70, left: 470, right: 70 }, duration: 650, maxZoom: 12 });
    }

    current.stops.forEach((stop, index) => {
      const label = index === 0 ? "A" : index === current.stops.length - 1 ? "B" : String(index);
      addMarker(
        stop.longitude,
        stop.latitude,
        `<div class="route-marker ${index === 0 ? "origin" : index === current.stops.length - 1 ? "destination" : "waypoint"}">${label}</div>`,
        `<div class="map-popup"><strong>${escapeHtml(stop.name)}</strong><div>${escapeHtml(stop.display_name)}</div></div>`,
      );
    });

    const plannedChargingStops = current.ev_plan?.charging_stops || [];
    const plannedIds = new Set(plannedChargingStops.map((stop) => String(stop.charger.id)));
    const nextChargingId = plannedChargingStops.length > 0 ? String(plannedChargingStops[0].charger.id) : null;
    const plannedById = new Map(plannedChargingStops.map((stop, index) => [String(stop.charger.id), { stop, index }]));

    current.chargers.forEach((charger) => {
      const chargerId = String(charger.id);
      const planned = plannedById.get(chargerId);
      const recommended = chargerId === nextChargingId;
      if (!planned && current.chargers.length > 120) return;
      const stop = planned?.stop;
      const energy = stop?.energy_to_target_kwh ?? null;
      const chargeMinutes = stop?.estimated_charging_time_minutes ?? estimatedChargeMinutes(charger, energy);
      const reachMinutes = stop?.time_to_reach_minutes ?? null;
      const popup = `
        <div class="map-popup charger-popup">
          <div class="popup-brand-row"><img src="${brandLogoPath(charger)}" alt="" class="popup-logo" /><div><strong>${escapeHtml(charger.name || "EV charging station")}</strong><span>${escapeHtml(charger.cpoName || "Operator not listed")}</span></div></div>
          <div class="popup-source"><img src="/geopilot-ev.svg" alt="" /> GeoPilot EV Charging Dataset</div>
          <div class="popup-grid">
            <span>Socket</span><b>${escapeHtml(charger.socket_type || charger.chargerType || "Not specified")}</b>
            <span>Type</span><b>${escapeHtml(chargerSpeed(charger))}</b>
            <span>Est. power</span><b>${charger.estimated_power_kw ? `${formatNumber(charger.estimated_power_kw, 0)} kW` : "Not listed"}</b>
            <span>Off route</span><b>${formatNumber(charger.distance_from_route_km, 2)} km</b>
            ${reachMinutes != null ? `<span>Time to reach</span><b>${formatMinutes(reachMinutes)}</b>` : ""}
            ${stop ? `<span>Battery arrival</span><b>${formatNumber(stop.battery_arrival_percent, 0)}%</b>` : ""}
            ${stop ? `<span>Charge to</span><b>${formatNumber(stop.battery_departure_percent, 0)}%</b>` : ""}
            ${energy != null ? `<span>Energy needed</span><b>${formatNumber(energy, 1)} kWh</b>` : ""}
            ${chargeMinutes != null ? `<span>Est. charge time</span><b>${formatMinutes(chargeMinutes)}</b>` : ""}
          </div>
          ${charger.address ? `<div class="popup-address">${escapeHtml(charger.address)}</div>` : ""}
          ${planned ? `<div class="popup-stop">Charging stop #${planned.index + 1}</div>` : ""}
          ${recommended ? `<div class="popup-badge">Next recommended charging stop</div>` : ""}
          ${chargeMinutes != null ? `<div class="popup-note">Charging time is an estimate using the dataset's reference power; actual time depends on vehicle and charger conditions.</div>` : ""}
        </div>`;
      addMarker(
        charger.longitude,
        charger.latitude,
        `<div class="charge-marker ${recommended ? "recommended" : planned ? "planned" : ""}">${planned ? `<img src="/geopilot-ev.svg" alt="" /><span>${planned.index + 1}</span>` : `<img src="${brandLogoPath(charger)}" alt="" />`}</div>`,
        popup,
      );
    });

    current.pois.slice(0, 120).forEach((poi) => {
      const popup = `
        <div class="map-popup">
          <strong>${escapeHtml(poi.name)}</strong>
          <div>${poiEmoji(poi.category)} ${escapeHtml(poi.category.replaceAll("_", " "))}</div>
          ${poi.distance_from_route_km != null ? `<div>${formatNumber(poi.distance_from_route_km, 2)} km from route</div>` : ""}
          ${poi.distance_from_reference_km != null ? `<div>${formatNumber(poi.distance_from_reference_km, 2)} km from reference</div>` : ""}
          ${poi.address ? `<div>${escapeHtml(poi.address)}</div>` : ""}
          ${poi.opening_hours ? `<div>${escapeHtml(poi.opening_hours)}</div>` : ""}
        </div>`;
      addMarker(poi.longitude, poi.latitude, `<div class="poi-marker"><img src="${categoryIconPath(poi.category)}" alt="" /></div>`, popup);
    });
  }

  async function sendMessage(text?: string) {
    const message = (text ?? input).trim();
    if (!message || loading) return;

    setMessages((previous) => [...previous, { role: "user", text: message }]);
    setInput("");
    setLoading(true);

    try {
      const response = await fetch(`${BACKEND_URL}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionIdRef.current || null, message }),
      });
      const data = (await response.json()) as ChatResponse | { detail?: string };
      if (!response.ok) throw new Error("detail" in data && data.detail ? data.detail : "GeoPilot request failed.");
      const result = data as ChatResponse;
      sessionIdRef.current = result.session_id;
      setSessionId(result.session_id);
      setContext(result.context);
      setMessages((previous) => [...previous, { role: "assistant", text: result.reply }]);
    } catch (error) {
      setMessages((previous) => [
        ...previous,
        { role: "assistant", text: error instanceof Error ? error.message : "Unable to reach GeoPilot." },
      ]);
    } finally {
      setLoading(false);
    }
  }

  async function resetConversation() {
    if (sessionId) {
      try {
        await fetch(`${BACKEND_URL}/session/${encodeURIComponent(sessionId)}`, { method: "DELETE" });
      } catch {
        // local reset still works
      }
    }
    localStorage.removeItem(SESSION_KEY);
    sessionIdRef.current = "";
    setSessionId("");
    setContext(null);
    setSelectedPOI(null);
    setMessages([{ role: "assistant", text: "New GeoPilot session started. Where are you going?" }]);
    clearMarkers();
  }

  async function quickPlan() {
    const orderedStops = [origin.trim(), ...waypoints.map((item) => item.trim()).filter(Boolean), destination.trim()].filter(Boolean);
    if (orderedStops.length < 2) return;
    const [start, end, ...middle] = orderedStops;
    const via = middle.length ? ` via ${middle.join(", ")}` : "";
    const compound = `Plan an EV trip from ${start} to ${end}${via}. I’m driving a ${vehicleModel} with a declared range of ${vehicleRange} km, ${batteryPack} kWh battery capacity, and ${battery}% battery currently. Use a ${reserve}% reserve and charge up to ${targetCharge}%.`;
    await sendMessage(compound);
  }

  function addWaypointField() {
    setWaypoints((previous) => [...previous, ""]);
  }

  function updateWaypoint(index: number, value: string) {
    setWaypoints((previous) => previous.map((item, i) => (i === index ? value : item)));
  }

  function removeWaypoint(index: number) {
    setWaypoints((previous) => previous.filter((_, i) => i !== index));
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void sendMessage();
    }
  }

  return (
    <div className="app-shell">
      <aside className="side-panel">
        <div className="brand-row">
          <div>
            <div className="brand-title">GeoPilot AI</div>
            <div className="brand-subtitle">Conversational geospatial trip planner</div>
          </div>
          <button className="icon-button" onClick={() => void resetConversation()} title="New session">＋</button>
        </div>

        <div className="status-row">
          <span className={`status-dot ${backendStatus}`} />
          <span>{backendStatus === "online" ? "Backend online" : backendStatus === "offline" ? "Backend offline" : "Checking backend…"}</span>
          <span className="session-pill">{sessionId ? "Context active" : "New session"}</span>
        </div>

        <button className="planner-toggle" onClick={() => setShowPlanner((value) => !value)}>
          <span>Quick Planner</span><span>{showPlanner ? "⌃" : "⌄"}</span>
        </button>

        {showPlanner && (
          <section className="planner-card">
            <div className="section-title">Trip stops</div>
            <label>Origin<input value={origin} onChange={(e) => setOrigin(e.target.value)} /></label>
            {waypoints.map((value, index) => (
              <div className="waypoint-row" key={`${index}-${value}`}>
                <label className="grow">Stop {index + 1}<input value={value} onChange={(e) => updateWaypoint(index, e.target.value)} placeholder="e.g. Coorg" /></label>
                <button className="remove-btn" onClick={() => removeWaypoint(index)}>×</button>
              </div>
            ))}
            <label>Destination<input value={destination} onChange={(e) => setDestination(e.target.value)} /></label>
            <button className="link-button" onClick={addWaypointField}>+ Add stop</button>

            <div className="section-title sub">Vehicle context</div>
            <label>Vehicle<input value={vehicleModel} onChange={(e) => setVehicleModel(e.target.value)} /></label>
            <div className="grid-2">
              <label>Range (km)<input inputMode="decimal" value={vehicleRange} onChange={(e) => setVehicleRange(e.target.value)} /></label>
              <label>Battery now (%)<input inputMode="decimal" value={battery} onChange={(e) => setBattery(e.target.value)} /></label>
            </div>
            <div className="grid-3">
              <label>Pack kWh<input inputMode="decimal" value={batteryPack} onChange={(e) => setBatteryPack(e.target.value)} /></label>
              <label>Reserve %<input inputMode="decimal" value={reserve} onChange={(e) => setReserve(e.target.value)} /></label>
              <label>Target %<input inputMode="decimal" value={targetCharge} onChange={(e) => setTargetCharge(e.target.value)} /></label>
            </div>
            <label>Route corridor (km)<input inputMode="decimal" value={corridor} onChange={(e) => setCorridor(e.target.value)} /></label>
            <button className="primary-button" onClick={() => void quickPlan()} disabled={loading}>Plan this trip</button>
          </section>
        )}

        {context && (
          <section className={`context-card ${contextExpanded ? "expanded" : "collapsed"}`}>
            <div className="context-heading">
              <div className="context-heading-left"><span>Active Trip Context</span><span>{context.turn_count} turns</span></div>
              <button className="context-toggle" onClick={() => setContextExpanded((value) => !value)} aria-expanded={contextExpanded}>
                {contextExpanded ? "Collapse" : "Expand"}
              </button>
            </div>
            <div className="trip-line">{summary?.trip || "No trip yet"}</div>
            {!contextExpanded ? (
              <div className="context-collapsed-summary">
                <span>{summary?.distance || "—"}</span>
                <span>{summary?.duration || "—"}</span>
                <span>{summary?.charging ?? 0} charges</span>
                {context.vehicle?.current_battery_percent != null ? <span>{context.vehicle.current_battery_percent}% battery</span> : null}
              </div>
            ) : (
            <>
            <div className="metric-row">
              <MiniMetric label="Distance" value={summary?.distance || "—"} />
              <MiniMetric label="Drive time" value={summary?.duration || "—"} />
              <MiniMetric label="Charges" value={String(summary?.charging ?? 0)} />
            </div>
            <div className="context-tags">
              <span>Reserve {context.reserve_percent}%</span>
              <span>Target {context.target_charge_percent}%</span>
              <span>Corridor {context.corridor_km} km</span>
            </div>

            {context.vehicle && (
              <div className="vehicle-box rich">
                <div className="vehicle-head">
                  <div className="vehicle-logo-wrap"><img src="/vehicle/tata.svg" alt="Tata" className="vehicle-logo-img" /><span>TATA</span></div>
                  <div>
                    <div className="vehicle-name">{[context.vehicle.make, context.vehicle.model].filter(Boolean).join(" ") || "Vehicle"}</div>
                    <div className="vehicle-source">User-declared vehicle context</div>
                  </div>
                </div>
                <div className="vehicle-stats">
                  <div><span>Battery now</span><strong>{context.vehicle.current_battery_percent ?? "—"}%</strong></div>
                  <div><span>Energy now</span><strong>{formatNumber(batteryEnergyPercent(context.vehicle, context.vehicle.current_battery_percent), 1)} kWh</strong></div>
                  <div><span>Declared range</span><strong>{context.vehicle.max_range_km ?? "—"} km</strong></div>
                  <div><span>Battery pack</span><strong>{context.vehicle.battery_capacity_kwh ?? "—"} kWh</strong></div>
                </div>
              </div>
            )}

            {context.ev_plan && (
              <div className={`ev-card ${context.ev_plan.trip_possible ? "good" : "bad"}`}>
                <div className="ev-card-head">
                  <div>
                    <div className="ev-kicker"><img src="/geopilot-ev.svg" alt="" /> GeoPilot EV Planner</div>
                    <strong>{context.ev_plan.trip_possible ? "EV plan feasible" : "EV plan needs adjustment"}</strong>
                  </div>
                  <span className="ev-count">{context.ev_plan.charging_stops.length} stops</span>
                </div>
                <div className="ev-vehicle-line">
                  <strong>{[context.vehicle?.make, context.vehicle?.model].filter(Boolean).join(" ") || "EV"}</strong>
                  <span>{context.vehicle?.battery_capacity_kwh ?? "—"} kWh pack · {context.vehicle?.max_range_km ?? "—"} km declared range · {formatNumber(context.vehicle?.current_battery_percent, 0)}% now</span>
                </div>
                <div className="battery-bar"><span style={{ width: `${Math.max(0, Math.min(100, Number(context.ev_plan.starting_battery_percent || 0)))}%` }} /></div>
                <div className="ev-grid">
                  <div><span>Start battery</span><strong>{formatNumber(context.ev_plan.starting_battery_percent, 0)}%</strong></div>
                  <div><span>Reserve</span><strong>{context.reserve_percent}%</strong></div>
                  <div><span>Target</span><strong>{context.target_charge_percent}%</strong></div>
                  <div><span>Destination</span><strong>{formatNumber(context.ev_plan.destination_battery_percent, 0)}%</strong></div>
                  <div><span>Route energy need</span><strong>{formatNumber(context.ev_plan.total_battery_required_percent, 0)}%</strong></div>
                  <div><span>Energy required</span><strong>{context.vehicle?.battery_capacity_kwh && context.ev_plan.total_battery_required_percent != null ? `${formatNumber(Number(context.vehicle.battery_capacity_kwh) * Number(context.ev_plan.total_battery_required_percent) / 100, 1)} kWh` : "—"}</strong></div>
                  <div><span>Start usable range</span><strong>{context.vehicle?.max_range_km != null ? `${formatNumber(Number(context.vehicle.max_range_km) * Math.max(Number(context.ev_plan.starting_battery_percent) - Number(context.reserve_percent), 0) / 100, 0)} km` : "—"}</strong></div>
                  <div><span>Charging stops</span><strong>{context.ev_plan.charging_stops.length}</strong></div>
                  <div><span>Charge time total</span><strong>{formatMinutes(totalEstimatedChargingMinutes(context.ev_plan))}</strong></div>
                  <div><span>Total trip est.</span><strong>{formatMinutes(Number(context.route?.duration_minutes || 0) + totalEstimatedChargingMinutes(context.ev_plan))}</strong></div>
                </div>

                {context.ev_plan.charging_stops.length > 0 && (
                  <div className="charging-timeline">
                    <div className="timeline-title">Charging plan</div>
                    {context.ev_plan.charging_stops.map((stop, index) => {
                      const charger = stop.charger;
                      return (
                        <button className={`charge-row ${index === 0 ? "next" : ""}`} key={`${charger.id}-${index}`} onClick={() => mapRef.current?.flyTo({ center: [charger.longitude, charger.latitude], zoom: 15, duration: 650 })}>
                          <div className="charge-row-logo"><img src={brandLogoPath(charger)} alt="" /></div>
                          <div className="charge-row-main">
                            <strong>#{index + 1} {charger.name || "EV charging station"}</strong>
                            <small>{charger.cpoName || "Operator not listed"} · {charger.socket_type || charger.chargerType || "Socket not listed"} · {chargerSpeed(charger)} · {charger.estimated_power_kw ? `${formatNumber(charger.estimated_power_kw, 0)} kW` : "power n/a"}</small>
                            <small>{formatNumber(stop.distance_from_start_km, 0)} km into trip · {formatNumber(charger.distance_from_route_km, 2)} km off route · reach in {formatMinutes(stop.time_to_reach_minutes)}</small>
                            <small>{formatMinutes(stop.estimated_charging_time_minutes)} to {formatNumber(stop.battery_departure_percent, 0)}% · {formatNumber(stop.energy_to_target_kwh, 1)} kWh added</small>
                          </div>
                          <div className="charge-row-battery"><b>{formatNumber(stop.battery_arrival_percent, 0)}%</b><span>→ {formatNumber(stop.battery_departure_percent, 0)}%</span></div>
                          <div className="charge-row-time">{formatMinutes(stop.estimated_charging_time_minutes)}<small>to target</small></div>
                        </button>
                      );
                    })}
                  </div>
                )}
              </div>
            )}

            {context.pois.length > 0 && (
              <div className="poi-summary"><img src={categoryIconPath(context.pois[0]?.category || "place")} alt="" /> Showing {context.pois.length} mapped POIs</div>
            )}
            </>
            )}
          </section>
        )}

        <div className="chat-area">
          <div className="quick-row">
            <QuickButton label="Plan EV trip" onClick={() => void sendMessage("Plan an EV trip from Bengaluru to Mysuru")} />
            <QuickButton label="Restaurants" onClick={() => void sendMessage("Find restaurants along the route")} />
            <QuickButton label="Hotels" onClick={() => void sendMessage("Find hotels around my destination")} />
          </div>

          <div className="chat-log">
            {messages.map((message, index) => (
              <div className={`chat-bubble ${message.role}`} key={`${index}-${message.text.slice(0, 12)}`}>
                {message.text}
              </div>
            ))}
            {loading && (
              <div className="chat-bubble assistant thinking thinking-bubble">
                <span className="thinking-orb"><i /><i /><i /></span>
                <span>{thinkingMessages[thinkingIndex]}</span>
              </div>
            )}
          </div>

          <div className="composer">
            <textarea
              value={input}
              onChange={(event) => setInput(event.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Try: Add Coorg · What if I start with 60%? · Find a restaurant near my first charging stop"
              rows={3}
            />
            <div className="composer-footer">
              <span>Enter to send · Shift+Enter for a new line</span>
              <button className="send-button" onClick={() => void sendMessage()} disabled={!canSend}>{loading ? "…" : "Send"}</button>
            </div>
          </div>
        </div>
      </aside>

      <main className="map-panel">
        <div ref={mapContainerRef} className="map" />
        <div className="map-overlay top-left">
          <div className="overlay-title">Live Geo View</div>
          <div className="overlay-subtitle">OSRM route · Tata charger dataset · OSM/Overpass POIs</div>
        </div>
        {context?.ev_plan && (
          <div className="map-overlay trip-chip">
            <span className={context.ev_plan.trip_possible ? "dot-good" : "dot-bad"} />
            {context.ev_plan.trip_possible ? "EV route feasible" : "EV plan requires attention"}
            <span>· {context.ev_plan.charging_stops.length} charge stop(s)</span>
          </div>
        )}
        {context && context.pois.length > 0 && (
          <div className="poi-drawer">
            <div className="drawer-header"><strong>{context.pois.length} POIs</strong><span>{context.pois[0]?.source || (context.pois[0]?.category === "ev_charging" ? "GeoPilot EV Charging Dataset" : "OpenStreetMap")}</span></div>
            <div className="poi-list">
              {context.pois.slice(0, 10).map((poi, index) => (
                <button className="poi-item" key={`${poi.osm_type}-${poi.osm_id}-${index}`} onClick={() => {
                  setSelectedPOI(poi);
                  mapRef.current?.flyTo({ center: [poi.longitude, poi.latitude], zoom: 15, duration: 600 });
                }}>
                  <span className="poi-icon"><img src={categoryIconPath(poi.category)} alt="" /></span>
                  <span className="poi-copy"><strong>{poi.name}</strong><small>{poi.category.replaceAll("_", " ")}{poi.distance_from_route_km != null ? ` · ${formatNumber(poi.distance_from_route_km, 1)} km off route` : ""}</small></span>
                </button>
              ))}
            </div>
          </div>
        )}
        {selectedPOI && (
          <div className="selected-card">
            <button onClick={() => setSelectedPOI(null)}>×</button>
            <div className="selected-title"><img src={categoryIconPath(selectedPOI.category)} alt="" /> {selectedPOI.name}</div>
            <div>{selectedPOI.category.replaceAll("_", " ")}</div>
            {selectedPOI.address ? <div>{selectedPOI.address}</div> : null}
          </div>
        )}
      </main>
    </div>
  );
}

function MiniMetric({ label, value }: { label: string; value: string }) {
  return <div className="mini-metric"><span>{label}</span><strong>{value}</strong></div>;
}

function QuickButton({ label, onClick }: { label: string; onClick: () => void }) {
  return <button className="quick-button" onClick={onClick}>{label}</button>;
}

export default App;
