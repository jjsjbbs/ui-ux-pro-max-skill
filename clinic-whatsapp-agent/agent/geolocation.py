"""
Geolocation utilities: parse WhatsApp location messages and find nearest clinic.
"""
import math
import os
from typing import Optional
import httpx

from .clinic_config import ClinicLocation


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return great-circle distance in kilometers."""
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def find_nearest_clinics(
    lat: float,
    lon: float,
    locations: list[ClinicLocation],
    max_results: int = 3,
    max_distance_km: float = 50.0,
) -> list[tuple[ClinicLocation, float]]:
    """Return (location, distance_km) sorted by proximity."""
    ranked = []
    for loc in locations:
        dist = haversine_km(lat, lon, loc.latitude, loc.longitude)
        if dist <= max_distance_km:
            ranked.append((loc, round(dist, 1)))
    ranked.sort(key=lambda x: x[1])
    return ranked[:max_results]


async def reverse_geocode(lat: float, lon: float) -> Optional[str]:
    """Return a human-readable city/neighborhood string via Nominatim (free, no key)."""
    try:
        url = "https://nominatim.openstreetmap.org/reverse"
        params = {"lat": lat, "lon": lon, "format": "json", "zoom": 10}
        headers = {"User-Agent": "ClinicWhatsAppAgent/1.0"}
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(url, params=params, headers=headers)
            data = r.json()
            addr = data.get("address", {})
            city = addr.get("city") or addr.get("town") or addr.get("municipality") or addr.get("county", "")
            state = addr.get("state", "")
            return f"{city}, {state}".strip(", ")
    except Exception:
        return None


def parse_whatsapp_location(body: str, latitude: Optional[str], longitude: Optional[str]) -> Optional[tuple[float, float]]:
    """
    Twilio passes latitude/longitude as separate query params for WhatsApp location messages.
    Also attempts to extract from text like '19.4326,-99.1332'.
    """
    if latitude and longitude:
        try:
            return float(latitude), float(longitude)
        except ValueError:
            pass

    # Try to extract coordinates from plain text
    import re
    match = re.search(r"(-?\d+\.\d+)[,\s]+(-?\d+\.\d+)", body or "")
    if match:
        return float(match.group(1)), float(match.group(2))

    return None
