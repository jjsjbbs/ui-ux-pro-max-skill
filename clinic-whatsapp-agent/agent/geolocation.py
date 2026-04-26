"""
Geolocation: Google Maps API (primary) with Nominatim fallback.
Set GOOGLE_MAPS_API_KEY in .env to enable Google Maps precision.
"""
import math
import os
import re
from typing import Optional
import httpx

from .clinic_config import ClinicLocation

GOOGLE_MAPS_KEY = os.getenv("GOOGLE_MAPS_API_KEY", "")


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return round(R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a)), 1)


def find_nearest_clinics(
    lat: float,
    lon: float,
    locations: list[ClinicLocation],
    max_results: int = 3,
    max_distance_km: float = 100.0,
) -> list[tuple[ClinicLocation, float]]:
    ranked = [
        (loc, haversine_km(lat, lon, loc.latitude, loc.longitude))
        for loc in locations
    ]
    ranked = [(loc, d) for loc, d in ranked if d <= max_distance_km]
    ranked.sort(key=lambda x: x[1])
    return ranked[:max_results]


async def geocode_address(address: str) -> Optional[tuple[float, float]]:
    """Convert a text address (city, neighborhood, postal code) to coordinates."""
    if GOOGLE_MAPS_KEY:
        return await _geocode_google(address)
    return await _geocode_nominatim(address)


async def reverse_geocode(lat: float, lon: float) -> Optional[str]:
    """Convert coordinates to a readable location string."""
    if GOOGLE_MAPS_KEY:
        return await _reverse_google(lat, lon)
    return await _reverse_nominatim(lat, lon)


# ── Google Maps ───────────────────────────────────────────────────────────────

async def _geocode_google(address: str) -> Optional[tuple[float, float]]:
    try:
        url = "https://maps.googleapis.com/maps/api/geocode/json"
        params = {"address": address, "key": GOOGLE_MAPS_KEY, "region": "es", "language": "es"}
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(url, params=params)
            data = r.json()
            if data.get("status") == "OK":
                loc = data["results"][0]["geometry"]["location"]
                return loc["lat"], loc["lng"]
    except Exception:
        pass
    return await _geocode_nominatim(address)  # fallback


async def _reverse_google(lat: float, lon: float) -> Optional[str]:
    try:
        url = "https://maps.googleapis.com/maps/api/geocode/json"
        params = {"latlng": f"{lat},{lon}", "key": GOOGLE_MAPS_KEY, "language": "es", "result_type": "locality|administrative_area_level_2"}
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(url, params=params)
            data = r.json()
            if data.get("status") == "OK" and data["results"]:
                components = data["results"][0].get("address_components", [])
                locality = next((c["long_name"] for c in components if "locality" in c["types"]), None)
                province = next((c["long_name"] for c in components if "administrative_area_level_2" in c["types"]), None)
                parts = [p for p in [locality, province] if p]
                return ", ".join(parts) if parts else None
    except Exception:
        pass
    return await _reverse_nominatim(lat, lon)


# ── Nominatim fallback (free, no key needed) ──────────────────────────────────

async def _geocode_nominatim(address: str) -> Optional[tuple[float, float]]:
    try:
        url = "https://nominatim.openstreetmap.org/search"
        params = {"q": address, "format": "json", "limit": 1, "countrycodes": "es"}
        headers = {"User-Agent": "ClinicBotAgente/1.0"}
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(url, params=params, headers=headers)
            results = r.json()
            if results:
                return float(results[0]["lat"]), float(results[0]["lon"])
    except Exception:
        pass
    return None


async def _reverse_nominatim(lat: float, lon: float) -> Optional[str]:
    try:
        url = "https://nominatim.openstreetmap.org/reverse"
        params = {"lat": lat, "lon": lon, "format": "json", "zoom": 10}
        headers = {"User-Agent": "ClinicBotAgente/1.0"}
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(url, params=params, headers=headers)
            data = r.json()
            addr = data.get("address", {})
            city = addr.get("city") or addr.get("town") or addr.get("municipality") or addr.get("county", "")
            province = addr.get("state", "")
            parts = [p for p in [city, province] if p]
            return ", ".join(parts) if parts else None
    except Exception:
        return None


def parse_whatsapp_location(body: str, latitude: Optional[str], longitude: Optional[str]) -> Optional[tuple[float, float]]:
    """Parse coordinates from Twilio WhatsApp location message or plain text."""
    if latitude and longitude:
        try:
            return float(latitude), float(longitude)
        except ValueError:
            pass
    match = re.search(r"(-?\d{1,3}\.\d+)[,\s]+(-?\d{1,3}\.\d+)", body or "")
    if match:
        return float(match.group(1)), float(match.group(2))
    return None


def get_google_maps_link(lat: float, lon: float, label: str = "") -> str:
    """Generate a Google Maps link for a location."""
    if label:
        return f"https://maps.google.com/?q={lat},{lon}&label={label.replace(' ', '+')}"
    return f"https://maps.google.com/?q={lat},{lon}"


def get_directions_link(dest_lat: float, dest_lon: float) -> str:
    """Generate a Google Maps directions link."""
    return f"https://maps.google.com/maps?daddr={dest_lat},{dest_lon}"
