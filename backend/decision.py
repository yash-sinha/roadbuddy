import hashlib
import math
from .synthetic_data import GARAGES, POSTCODE_LOOKUP

# Mock taxi providers (demo only — no real geo).
TAXI_PROVIDERS = [
    {"name": "CityRide London", "eta_minutes": 8},
    {"name": "QuickCab West",   "eta_minutes": 11},
    {"name": "BlackCab North",  "eta_minutes": 9},
    {"name": "RiverRide South", "eta_minutes": 12},
    {"name": "Eastside Cabs",   "eta_minutes": 10},
]

# Mock rental car depots (demo only — no real geo).
RENTAL_DEPOTS = [
    {"name": "Enterprise Rent-A-Car — City", "address": "12 Moorgate, EC2R 6DA",      "eta_minutes": 30},
    {"name": "Hertz — Waterloo",             "address": "Station Approach, SE1 8SW",  "eta_minutes": 35},
    {"name": "Sixt — Marble Arch",           "address": "Park Lane, W1K 1QA",         "eta_minutes": 32},
    {"name": "Avis — King's Cross",          "address": "Pancras Road, N1C 4TB",      "eta_minutes": 28},
]


def get_action(issue_type: str, *, transcript: str = "", damage_severity: str | None = None) -> str:
    transcript_lc = transcript.lower()
    if issue_type in ("engine_failure", "accident"):
        return "tow_truck"
    if issue_type in ("flat_tyre", "battery"):
        if issue_type == "flat_tyre":
            tow_indicators = (
                "no spare",
                "don't have a spare",
                "do not have a spare",
                "no spare tyre",
                "no spare tire",
                "spare is flat",
                "spare is damaged",
                "spare is unusable",
                "spare isn't roadworthy",
                "spare is not roadworthy",
            )
            if any(indicator in transcript_lc for indicator in tow_indicators):
                return "tow_truck"
        if issue_type == "battery":
            tow_indicators = ("electrical fault", "burning smell", "smoke")
            if damage_severity == "severe" or any(indicator in transcript_lc for indicator in tow_indicators):
                return "tow_truck"
        return "repair_truck"
    return "tow_truck"


def _stable_pick(providers: list[dict], key: str) -> dict:
    """Deterministic pseudo-random pick — same key always returns same provider.
    Just a demo mock; no real geo lookup."""
    if not key:
        return providers[0]
    digest = hashlib.md5(key.lower().strip().encode()).digest()
    return providers[digest[0] % len(providers)]


def get_taxi(location: str) -> dict:
    """Mock taxi dispatch — picks deterministically from the provider list."""
    provider = _stable_pick(TAXI_PROVIDERS, location or "")
    return {
        "name": provider["name"],
        "eta_minutes": provider["eta_minutes"],
        "pickup": location or "Your current location",
    }


def get_rental(severity: str, location: str = "") -> dict | None:
    """Return rental option only for severe or moderate damage."""
    if severity not in ("severe", "moderate"):
        return None
    depot = _stable_pick(RENTAL_DEPOTS, location or "")
    return {
        "name": depot["name"],
        "address": depot["address"],
        "eta_minutes": depot["eta_minutes"],
    }


def _haversine(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _resolve_location(location: str) -> tuple[float, float]:
    loc_upper = location.upper().strip()
    for postcode, coords in POSTCODE_LOOKUP.items():
        if postcode in loc_upper or loc_upper in postcode:
            return coords
    # Default to central London
    return (51.5074, -0.1278)


def get_nearest_garage(location: str, action_type: str) -> dict:
    lat, lng = _resolve_location(location)
    speciality_needed = "tow" if action_type == "tow_truck" else "repair"

    candidates = [g for g in GARAGES if g["speciality"] in (speciality_needed, "both")]
    if not candidates:
        candidates = GARAGES

    candidates_with_dist = [
        (g, _haversine(lat, lng, g["lat"], g["lng"]))
        for g in candidates
    ]
    candidates_with_dist.sort(key=lambda x: x[1])
    garage, dist_km = candidates_with_dist[0]

    eta = max(10, int(dist_km * 6))  # rough: 10 km/h average in London traffic
    return {
        "name": garage["name"],
        "lat": garage["lat"],
        "lng": garage["lng"],
        "speciality": garage["speciality"],
        "distance_km": round(dist_km, 1),
        "eta_minutes": eta,
    }
