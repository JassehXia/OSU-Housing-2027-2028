#!/usr/bin/env python3
"""
Geospatial pipeline and dataset builder for the OSU 4-Bedroom Housing Map.

Reads raw scraped listings from:
  - data/raw_osu.json
  - data/raw_landlords.json

Produces:
  - public/data/listings.json
  - public/data/isochrone.geojson (via --isochrone or --all)
  - data/geocode_cache.json (persistent geocoding cache)

Usage:
  python scraper/build_dataset.py                 # Build public/data/listings.json
  python scraper/build_dataset.py --isochrone     # Generate public/data/isochrone.geojson
  python scraper/build_dataset.py --all           # Generate both isochrone and listings
  python scraper/build_dataset.py --dry-run       # Run pipeline without writing listings.json
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
PUBLIC_DATA_DIR = ROOT_DIR / "public" / "data"

RAW_OSU_PATH = DATA_DIR / "raw_osu.json"
RAW_LANDLORDS_PATH = DATA_DIR / "raw_landlords.json"
RAW_COLUMBUS_PATH = DATA_DIR / "raw_columbus.json"
GEOCODE_CACHE_PATH = DATA_DIR / "geocode_cache.json"
LISTINGS_OUT_PATH = PUBLIC_DATA_DIR / "listings.json"
ISOCHRONE_OUT_PATH = PUBLIC_DATA_DIR / "isochrone.geojson"

OSU_CENTER_LAT = 40.0000
OSU_CENTER_LNG = -83.0145
OSU_CENTER_NAME = "Ohio State University (The Oval)"

MAX_DRIVE_MINUTES = 20
FALLBACK_MAX_MILES = 15.0

OSRM_TABLE_URL = "https://router.project-osrm.org/table/v1/driving"
CENSUS_BATCH_URL = "https://geocoding.geo.census.gov/geocoder/locations/addressbatch"
NOMINATIM_SEARCH_URL = "https://nominatim.openstreetmap.org/search"

USER_AGENT = "OSU-4BR-Housing-Map/1.0 (Ohio State off-campus housing research)"

# Central Ohio sanity bounding box for geocoding validation
OHIO_LAT_MIN, OHIO_LAT_MAX = 39.50, 40.50
OHIO_LNG_MIN, OHIO_LNG_MAX = -83.60, -82.40

EARTH_RADIUS_MILES = 3958.7613


# ---------------------------------------------------------------------------
# Geodesic helpers
# ---------------------------------------------------------------------------

def haversine_miles(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance in statute miles between two WGS84 points."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = (
        math.sin(dphi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    )
    return 2.0 * EARTH_RADIUS_MILES * math.asin(math.sqrt(min(1.0, a)))


def destination_point(
    lat: float, lng: float, bearing_deg: float, distance_miles: float
) -> tuple[float, float]:
    """Compute (lat, lng) at `distance_miles` along `bearing_deg` (0=N, 90=E)."""
    ang_dist = distance_miles / EARTH_RADIUS_MILES
    bearing = math.radians(bearing_deg)
    lat1 = math.radians(lat)
    lng1 = math.radians(lng)

    sin_lat2 = (
        math.sin(lat1) * math.cos(ang_dist)
        + math.cos(lat1) * math.sin(ang_dist) * math.cos(bearing)
    )
    lat2 = math.asin(max(-1.0, min(1.0, sin_lat2)))
    lng2 = lng1 + math.atan2(
        math.sin(bearing) * math.sin(ang_dist) * math.cos(lat1),
        math.cos(ang_dist) - math.sin(lat1) * math.sin(lat2),
    )
    return (math.degrees(lat2), math.degrees(lng2))


def is_valid_central_ohio_coord(lat: Any, lng: Any) -> bool:
    try:
        la = float(lat)
        lo = float(lng)
    except (TypeError, ValueError):
        return False
    if math.isnan(la) or math.isnan(lo):
        return False
    return (OHIO_LAT_MIN <= la <= OHIO_LAT_MAX) and (OHIO_LNG_MIN <= lo <= OHIO_LNG_MAX)


# ---------------------------------------------------------------------------
# OSRM helpers
# ---------------------------------------------------------------------------

def osrm_table_durations(
    coords_lat_lng: list[tuple[float, float]],
    *,
    sources: str | None = None,
    destinations: str | None = None,
    timeout: int = 30,
    retries: int = 3,
) -> list[list[float | None]]:
    """
    Query the public OSRM Table API.
    `coords_lat_lng` is a list of (lat, lng) tuples; OSRM expects `lng,lat`.
    Returns the `durations` 2D matrix in seconds.
    """
    coord_str = ";".join(f"{lng:.6f},{lat:.6f}" for lat, lng in coords_lat_lng)
    url = f"{OSRM_TABLE_URL}/{coord_str}"
    params: dict[str, str] = {"annotations": "duration"}
    if sources is not None:
        params["sources"] = sources
    if destinations is not None:
        params["destinations"] = destinations

    headers = {"User-Agent": USER_AGENT}
    last_err: Exception | None = None

    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=timeout)
            if resp.status_code == 429:
                wait = 2.0 * attempt
                print(f"  OSRM rate-limited (429), retrying in {wait:.1f}s...")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            data = resp.json()
            if data.get("code") != "Ok":
                raise RuntimeError(f"OSRM error: {data.get('code')} - {data.get('message')}")
            return data["durations"]
        except Exception as exc:
            last_err = exc
            if attempt < retries:
                time.sleep(1.5 * attempt)

    raise RuntimeError(f"OSRM table request failed after {retries} attempts: {last_err}")


# ---------------------------------------------------------------------------
# Task 1: Isochrone generation (20-min drive boundary around OSU Oval)
# ---------------------------------------------------------------------------

def generate_isochrone(
    output_path: Path = ISOCHRONE_OUT_PATH,
    target_minutes: int = MAX_DRIVE_MINUTES,
    num_bearings: int = 36,
    sample_distances: tuple[float, ...] = (3, 5, 7, 9, 11, 13, 15, 17, 19, 22),
) -> dict[str, Any]:
    """
    Sample 36 compass bearings (every 10 degrees) at multiple radial distances
    from OSU Oval via the public OSRM Table API, and interpolate the exact
    `target_minutes` driving contour along each ray.
    """
    target_seconds = target_minutes * 60.0
    bearings = [i * (360.0 / num_bearings) for i in range(num_bearings)]

    # Build all (bearing_idx, dist_miles, lat, lng) sample points
    samples: list[tuple[int, float, float, float]] = []
    for b_idx, bearing in enumerate(bearings):
        for dist in sample_distances:
            lat, lng = destination_point(OSU_CENTER_LAT, OSU_CENTER_LNG, bearing, dist)
            samples.append((b_idx, dist, lat, lng))

    print(
        f"Generating {target_minutes}-min drive isochrone around OSU Oval "
        f"({num_bearings} bearings x {len(sample_distances)} rings = {len(samples)} points)..."
    )

    # Query OSRM in batches of 90 destinations (+1 source = 91 coords per request)
    batch_size = 90
    ray_durations: dict[int, list[tuple[float, float]]] = {i: [] for i in range(num_bearings)}

    for start in range(0, len(samples), batch_size):
        chunk = samples[start : start + batch_size]
        coords = [(OSU_CENTER_LAT, OSU_CENTER_LNG)] + [(pt[2], pt[3]) for pt in chunk]
        # destinations=0 gives durations[1..N][0] from each sample point to OSU Oval
        # (matching the listing-to-OSU commute direction used in build_dataset)
        durations_matrix = osrm_table_durations(coords, destinations="0")
        for idx, (b_idx, dist, _lat, _lng) in enumerate(chunk):
            dur = durations_matrix[idx + 1][0]
            if dur is not None:
                ray_durations[b_idx].append((dist, float(dur)))
        if start + batch_size < len(samples):
            time.sleep(0.35)

    # Interpolate the exact target_seconds crossing along each bearing
    boundary_miles: list[float] = []
    ring_coords_ccw: list[list[float]] = []

    # Iterate bearings in reverse (350, 340, ..., 0) for RFC 7946 CCW exterior ring
    # First compute distance per bearing index 0..num_bearings-1
    dist_by_bearing: list[float] = []
    for b_idx, bearing in enumerate(bearings):
        pts = sorted(ray_durations[b_idx], key=lambda x: x[0])
        if not pts:
            dist_by_bearing.append(12.0)
            continue

        # Find the outermost point with duration <= target_seconds and interpolate
        # to the next point with duration > target_seconds.
        interp_dist: float | None = None
        last_under_idx: int | None = None
        for i, (d, t) in enumerate(pts):
            if t <= target_seconds:
                last_under_idx = i

        if last_under_idx is None:
            # Even the closest ring exceeded target_seconds; extrapolate inward
            d0, t0 = pts[0]
            interp_dist = max(1.0, d0 * (target_seconds / max(t0, 1.0)))
        elif last_under_idx == len(pts) - 1:
            # Still under target_seconds at outermost ring; extrapolate outward modestly
            d_prev, t_prev = pts[-2] if len(pts) >= 2 else (0.0, 0.0)
            d_last, t_last = pts[-1]
            if t_last > t_prev:
                slope = (d_last - d_prev) / (t_last - t_prev)
                interp_dist = d_last + slope * (target_seconds - t_last)
            else:
                interp_dist = d_last
            interp_dist = min(interp_dist, sample_distances[-1] + 4.0)
        else:
            d1, t1 = pts[last_under_idx]
            d2, t2 = pts[last_under_idx + 1]
            if t2 > t1:
                frac = (target_seconds - t1) / (t2 - t1)
                interp_dist = d1 + frac * (d2 - d1)
            else:
                interp_dist = d1

        dist_by_bearing.append(interp_dist)
        boundary_miles.append(interp_dist)

    # Construct CCW GeoJSON ring: decreasing bearings (360 -> 0) goes N -> W -> S -> E -> N
    for b_idx in range(num_bearings - 1, -1, -1):
        bearing = bearings[b_idx]
        dist = dist_by_bearing[b_idx]
        lat, lng = destination_point(OSU_CENTER_LAT, OSU_CENTER_LNG, bearing, dist)
        ring_coords_ccw.append([round(lng, 6), round(lat, 6)])

    # Close polygon ring
    ring_coords_ccw.append(ring_coords_ccw[0])

    min_mi = round(min(boundary_miles), 2)
    max_mi = round(max(boundary_miles), 2)
    avg_mi = round(sum(boundary_miles) / len(boundary_miles), 2)

    geojson: dict[str, Any] = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {
                    "center": [OSU_CENTER_LAT, OSU_CENTER_LNG],
                    "driveMinutes": target_minutes,
                    "label": f"{target_minutes}-min drive from OSU",
                    "minRadiusMiles": min_mi,
                    "maxRadiusMiles": max_mi,
                    "avgRadiusMiles": avg_mi,
                    "generatedAt": datetime.now(timezone.utc).isoformat(),
                },
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [ring_coords_ccw],
                },
            }
        ],
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(geojson, f, indent=2)

    print(
        f"Saved isochrone to {output_path} "
        f"(radial range: {min_mi}–{max_mi} mi, avg {avg_mi} mi, {len(ring_coords_ccw)} vertices)."
    )
    return geojson


# ---------------------------------------------------------------------------
# Address normalization & deduplication
# ---------------------------------------------------------------------------

DIRECTION_MAP = {
    "north": "n",
    "south": "s",
    "east": "e",
    "west": "w",
    "northeast": "ne",
    "northwest": "nw",
    "southeast": "se",
    "southwest": "sw",
}

STREET_TYPE_MAP = {
    "avenue": "ave",
    "ave": "ave",
    "street": "st",
    "st": "st",
    "road": "rd",
    "rd": "rd",
    "drive": "dr",
    "dr": "dr",
    "lane": "ln",
    "ln": "ln",
    "court": "ct",
    "ct": "ct",
    "place": "pl",
    "pl": "pl",
    "boulevard": "blvd",
    "blvd": "blvd",
    "circle": "cir",
    "cir": "cir",
    "terrace": "ter",
    "ter": "ter",
    "parkway": "pkwy",
    "pkwy": "pkwy",
    "alley": "aly",
    "aly": "aly",
    "way": "way",
}

UNIT_WORDS = {"apt", "apartment", "unit", "suite", "ste", "fl", "floor", "rm", "room"}


def normalize_street_address(raw_address: str) -> str:
    """
    Canonicalize a street address for deduplication:
    - lowercase
    - strip trailing ', Columbus, OH 43201' city/state/zip if present
    - strip punctuation
    - abbreviate directions and street suffixes
    - standardize unit markers
    """
    if not raw_address:
        return ""

    addr = raw_address.strip().lower()
    # Strip trailing city/state/zip portion if comma-separated
    addr = re.split(r",\s*(?:columbus|ohio|oh\b|\d{5})", addr, maxsplit=1)[0]
    # Also strip trailing 'columbus oh 43201' without comma
    addr = re.sub(r"\bcolumbus\s+oh(?:io)?(?:\s+\d{5}(?:-\d{4})?)?$", "", addr).strip()

    # Replace `#` with ` unit ` so '#B' and 'Apt B' normalize identically
    addr = re.sub(r"#\s*", " unit ", addr)
    # Remove remaining punctuation except hyphens between unit/house numbers
    addr = re.sub(r"[.,;/()'\"]+", " ", addr)
    addr = re.sub(r"\s*-\s*", "-", addr)

    tokens = addr.split()
    out: list[str] = []
    for tok in tokens:
        if tok in DIRECTION_MAP:
            out.append(DIRECTION_MAP[tok])
        elif tok in STREET_TYPE_MAP:
            out.append(STREET_TYPE_MAP[tok])
        elif tok in UNIT_WORDS:
            if not out or out[-1] != "unit":
                out.append("unit")
        else:
            out.append(tok)

    return " ".join(out).strip()


# ---------------------------------------------------------------------------
# Field parsing & validation
# ---------------------------------------------------------------------------

def parse_number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        if math.isnan(value) or math.isinf(value):
            return None
        return float(value)
    if isinstance(value, str):
        cleaned = value.strip().replace(",", "").replace("$", "")
        if not cleaned:
            return None
        m = re.match(r"^-?\d+(?:\.\d+)?$", cleaned)
        if m:
            return float(cleaned)
    return None


def parse_strict_bedrooms(raw: dict[str, Any]) -> int | None:
    val = raw.get("bedrooms")
    if val is None:
        val = raw.get("beds")
    num = parse_number(val)
    if num is None:
        return None
    if num != int(num):
        return None
    return int(num)


def parse_rent_total(raw: dict[str, Any]) -> int | None:
    for key in ("rentTotal", "rent", "price", "monthlyRent"):
        if key in raw and raw[key] is not None:
            num = parse_number(raw[key])
            if num is not None and num > 0:
                return int(round(num))
    return None


def extract_zip(raw: dict[str, Any], address: str) -> str | None:
    for key in ("zip", "zipCode", "postalCode"):
        val = raw.get(key)
        if val:
            m = re.search(r"\b(\d{5})\b", str(val))
            if m:
                return m.group(1)
    m = re.search(r"\b(43\d{3})\b", address or "")
    return m.group(1) if m else None


def normalize_raw_listing(raw: dict[str, Any], default_source: str) -> dict[str, Any] | None:
    """Validate strict 4-bedroom + positive rent and normalize schema."""
    bedrooms = parse_strict_bedrooms(raw)
    if bedrooms != 4:
        return None

    rent_total = parse_rent_total(raw)
    if rent_total is None or rent_total <= 0:
        return None

    address = str(raw.get("address") or raw.get("streetAddress") or raw.get("title") or "").strip()
    if not address:
        return None

    city = str(raw.get("city") or "Columbus").strip() or "Columbus"
    state = str(raw.get("state") or "OH").strip() or "OH"
    zip_code = extract_zip(raw, address)

    lat = parse_number(raw.get("lat") if raw.get("lat") is not None else raw.get("latitude"))
    lng = parse_number(
        raw.get("lng")
        if raw.get("lng") is not None
        else (raw.get("lon") if raw.get("lon") is not None else raw.get("longitude"))
    )
    if not is_valid_central_ohio_coord(lat, lng):
        lat, lng = None, None

    baths = parse_number(raw.get("bathrooms") if raw.get("bathrooms") is not None else raw.get("baths"))
    sqft = parse_number(raw.get("sqft") if raw.get("sqft") is not None else raw.get("squareFeet"))

    photos_raw = raw.get("photos") or raw.get("images") or []
    if isinstance(photos_raw, str):
        photos = [photos_raw] if photos_raw.strip() else []
    elif isinstance(photos_raw, list):
        photos = [str(p).strip() for p in photos_raw if isinstance(p, str) and p.strip()]
    else:
        photos = []

    amenities_raw = raw.get("amenities") or raw.get("features") or []
    if isinstance(amenities_raw, list):
        amenities = [str(a).strip() for a in amenities_raw if str(a).strip()]
    else:
        amenities = []

    source = str(raw.get("source") or default_source).strip() or default_source
    url = str(raw.get("url") or raw.get("listingUrl") or "").strip() or None
    landlord = str(raw.get("landlord") or raw.get("managementCompany") or "").strip() or None
    title = str(raw.get("title") or address).strip()
    description = str(raw.get("description") or "").strip() or None
    available_date = str(raw.get("availableDate") or raw.get("available") or "").strip() or None
    neighborhood = str(raw.get("neighborhood") or "").strip() or None

    norm_key = normalize_street_address(address)
    listing_id = str(raw.get("id") or "").strip()
    if not listing_id:
        digest = hashlib.sha1(f"{norm_key}|{zip_code or ''}".encode("utf-8")).hexdigest()[:12]
        listing_id = f"osu4br-{digest}"

    record: dict[str, Any] = {
        "id": listing_id,
        "title": title,
        "address": address,
        "city": city,
        "state": state,
        "zip": zip_code,
        "neighborhood": neighborhood,
        "bedrooms": 4,
        "bathrooms": round(baths, 1) if baths is not None else None,
        "sqft": int(round(sqft)) if sqft is not None and sqft > 0 else None,
        "rentTotal": rent_total,
        "rentPerPerson": round(rent_total / 4),
        "availableDate": available_date,
        "lat": round(lat, 6) if lat is not None else None,
        "lng": round(lng, 6) if lng is not None else None,
        "url": url,
        "source": source,
        "sources": [source],
        "landlord": landlord,
        "photos": photos,
        "description": description,
        "amenities": amenities,
        "_normAddress": norm_key,
    }

    # Preserve optional boolean/string attributes if present
    for opt_key in ("petsAllowed", "petFriendly", "parking", "laundry", "utilitiesIncluded", "propertyType"):
        if opt_key in raw and raw[opt_key] is not None:
            record[opt_key] = raw[opt_key]

    return record


# ---------------------------------------------------------------------------
# Deduplication & merging
# ---------------------------------------------------------------------------

def is_osu_portal_url(url: str | None) -> bool:
    if not url:
        return False
    return "offcampus.osu.edu" in url.lower()


def richness_score(rec: dict[str, Any]) -> tuple[int, int, int, int, int]:
    """Higher tuple wins as primary record during merge."""
    direct_url = 1 if (rec.get("url") and not is_osu_portal_url(rec.get("url"))) else 0
    has_coords = 1 if (rec.get("lat") is not None and rec.get("lng") is not None) else 0
    photo_count = len(rec.get("photos") or [])
    desc_len = len(rec.get("description") or "")
    extras = sum(
        1
        for k in ("bathrooms", "sqft", "availableDate", "landlord", "neighborhood")
        if rec.get(k) is not None
    )
    return (direct_url, has_coords, min(photo_count, 10), desc_len, extras)


def merge_records(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    """Merge two normalized records for the same property, keeping the richer one."""
    primary, secondary = (a, b) if richness_score(a) >= richness_score(b) else (b, a)
    merged = dict(primary)

    # Combine sources preserving order
    sources: list[str] = []
    for s in (primary.get("sources") or []) + (secondary.get("sources") or []):
        if s and s not in sources:
            sources.append(s)
    merged["sources"] = sources

    # Prefer direct landlord URL over OSU portal URL
    if (not merged.get("url") or is_osu_portal_url(merged.get("url"))) and (
        secondary.get("url") and not is_osu_portal_url(secondary.get("url"))
    ):
        merged["url"] = secondary["url"]
        merged["source"] = secondary["source"]

    # Fill missing scalar fields from secondary
    for key in (
        "lat",
        "lng",
        "zip",
        "neighborhood",
        "bathrooms",
        "sqft",
        "availableDate",
        "landlord",
        "petsAllowed",
        "petFriendly",
        "parking",
        "laundry",
        "utilitiesIncluded",
        "propertyType",
    ):
        if merged.get(key) is None and secondary.get(key) is not None:
            merged[key] = secondary[key]

    # Prefer longer description
    if len(secondary.get("description") or "") > len(merged.get("description") or ""):
        merged["description"] = secondary["description"]

    # Union photos preserving order
    photos = list(merged.get("photos") or [])
    seen_photos = set(photos)
    for p in secondary.get("photos") or []:
        if p not in seen_photos:
            photos.append(p)
            seen_photos.add(p)
    merged["photos"] = photos

    # Union amenities (case-insensitive dedup)
    amenities = list(merged.get("amenities") or [])
    seen_am = {am.lower() for am in amenities}
    for am in secondary.get("amenities") or []:
        if am.lower() not in seen_am:
            amenities.append(am)
            seen_am.add(am.lower())
    merged["amenities"] = amenities

    return merged


def deduplicate_listings(listings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_addr: dict[str, dict[str, Any]] = {}
    for rec in listings:
        key = rec["_normAddress"]
        if not key:
            continue
        if key in by_addr:
            by_addr[key] = merge_records(by_addr[key], rec)
        else:
            by_addr[key] = rec
    return list(by_addr.values())


# ---------------------------------------------------------------------------
# Geocoding (Cache -> US Census Batch -> Nominatim fallback)
# ---------------------------------------------------------------------------

def load_geocode_cache(path: Path = GEOCODE_CACHE_PATH) -> dict[str, dict[str, float] | None]:
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except Exception as exc:
        print(f"Warning: could not read geocode cache {path}: {exc}")
    return {}


def save_geocode_cache(
    cache: dict[str, dict[str, float] | None], path: Path = GEOCODE_CACHE_PATH
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2, sort_keys=True)


def make_geocode_key(rec: dict[str, Any]) -> str:
    street = rec["_normAddress"]
    city = (rec.get("city") or "Columbus").strip().lower()
    state = (rec.get("state") or "OH").strip().lower()
    zip_code = (rec.get("zip") or "").strip()
    return f"{street}|{city}|{state}|{zip_code}"


def clean_street_for_geocoding(address: str) -> str:
    """Strip city/state/zip and unit suffix so Census/Nominatim match the building."""
    street = re.split(r",\s*(?:columbus|ohio|oh\b|\d{5})", address.strip(), flags=re.I)[0]
    street = re.sub(
        r"\s+(?:apt|apartment|unit|suite|ste|#)\s*[a-z0-9-]+$", "", street, flags=re.I
    )
    return street.strip()


def census_batch_geocode(
    items: list[tuple[str, str, str, str, str]],
) -> dict[str, tuple[float, float]]:
    """
    Batch geocode via US Census Geocoder API.
    `items`: list of (key, street, city, state, zip_code).
    Returns dict mapping key -> (lat, lng).
    """
    results: dict[str, tuple[float, float]] = {}
    batch_size = 500

    for start in range(0, len(items), batch_size):
        chunk = items[start : start + batch_size]
        buf = io.StringIO()
        writer = csv.writer(buf)
        for idx, (_key, street, city, state, zip_code) in enumerate(chunk):
            writer.writerow([str(idx), street, city, state, zip_code])

        files = {"addressFile": ("addresses.csv", buf.getvalue().encode("utf-8"), "text/csv")}
        data = {"benchmark": "Public_AR_Current"}
        headers = {"User-Agent": USER_AGENT}

        try:
            resp = requests.post(
                CENSUS_BATCH_URL, data=data, files=files, headers=headers, timeout=60
            )
            resp.raise_for_status()
            reader = csv.reader(io.StringIO(resp.text))
            for row in reader:
                if len(row) < 6:
                    continue
                try:
                    idx = int(row[0].strip())
                except ValueError:
                    continue
                match_status = row[2].strip().lower()
                coords_str = row[5].strip()
                if match_status == "match" and "," in coords_str:
                    lng_s, lat_s = coords_str.split(",", 1)
                    lat, lng = float(lat_s), float(lng_s)
                    if is_valid_central_ohio_coord(lat, lng):
                        key = chunk[idx][0]
                        results[key] = (round(lat, 6), round(lng, 6))
        except Exception as exc:
            print(f"  Warning: Census batch geocode error: {exc}")

    return results


def nominatim_geocode(
    street: str, city: str, state: str, zip_code: str
) -> tuple[float, float] | None:
    query = f"{street}, {city}, {state}" + (f" {zip_code}" if zip_code else "")
    params = {
        "q": query,
        "format": "json",
        "limit": 1,
        "countrycodes": "us",
    }
    headers = {"User-Agent": USER_AGENT}
    try:
        resp = requests.get(NOMINATIM_SEARCH_URL, params=params, headers=headers, timeout=15)
        resp.raise_for_status()
        rows = resp.json()
        if rows:
            lat = float(rows[0]["lat"])
            lng = float(rows[0]["lon"])
            if is_valid_central_ohio_coord(lat, lng):
                return (round(lat, 6), round(lng, 6))
    except Exception as exc:
        print(f"  Warning: Nominatim geocode error for '{query}': {exc}")
    return None


def geocode_missing_listings(
    listings: list[dict[str, Any]],
    *,
    dry_run: bool = False,
) -> None:
    """Populate lat/lng for any listing missing coordinates, using cache -> Census -> Nominatim."""
    cache = load_geocode_cache()
    cache_dirty = False

    missing_items: dict[str, tuple[str, str, str, str, str]] = {}
    for rec in listings:
        if rec.get("lat") is not None and rec.get("lng") is not None:
            continue
        key = make_geocode_key(rec)
        if key in cache:
            cached = cache[key]
            if isinstance(cached, dict) and is_valid_central_ohio_coord(
                cached.get("lat"), cached.get("lng")
            ):
                rec["lat"] = cached["lat"]
                rec["lng"] = cached["lng"]
            continue
        street = clean_street_for_geocoding(rec["address"])
        city = rec.get("city") or "Columbus"
        state = rec.get("state") or "OH"
        zip_code = rec.get("zip") or ""
        missing_items[key] = (key, street, city, state, zip_code)

    if not missing_items:
        return

    print(f"Geocoding {len(missing_items)} uncached addresses via US Census Batch API...")
    census_hits = census_batch_geocode(list(missing_items.values()))
    print(f"  Census matched {len(census_hits)}/{len(missing_items)} addresses.")

    for key, (lat, lng) in census_hits.items():
        cache[key] = {"lat": lat, "lng": lng}
        cache_dirty = True

    remaining = [v for k, v in missing_items.items() if k not in census_hits]
    if remaining:
        print(f"Falling back to Nominatim for {len(remaining)} remaining addresses...")
        for idx, (key, street, city, state, zip_code) in enumerate(remaining):
            if idx > 0:
                time.sleep(1.1)
            hit = nominatim_geocode(street, city, state, zip_code)
            if hit is not None:
                cache[key] = {"lat": hit[0], "lng": hit[1]}
            else:
                cache[key] = None
            cache_dirty = True

    # Apply geocoded results back to listings
    for rec in listings:
        if rec.get("lat") is not None and rec.get("lng") is not None:
            continue
        key = make_geocode_key(rec)
        cached = cache.get(key)
        if isinstance(cached, dict) and is_valid_central_ohio_coord(
            cached.get("lat"), cached.get("lng")
        ):
            rec["lat"] = cached["lat"]
            rec["lng"] = cached["lng"]

    if cache_dirty and not dry_run:
        save_geocode_cache(cache)


# ---------------------------------------------------------------------------
# Drive & walk time computation (OSRM Table API + haversine)
# ---------------------------------------------------------------------------

def compute_travel_times(listings: list[dict[str, Any]]) -> None:
    """
    Compute distanceMiles, walkMinutes, and real OSRM driveMinutes
    from each listing to OSU Oval (in batches of 80 coordinates).
    """
    with_coords = [
        rec for rec in listings if rec.get("lat") is not None and rec.get("lng") is not None
    ]
    if not with_coords:
        return

    for rec in with_coords:
        dist = haversine_miles(rec["lat"], rec["lng"], OSU_CENTER_LAT, OSU_CENTER_LNG)
        rec["distanceMiles"] = round(dist, 2)
        # 3.0 mph walking speed with 1.25 street-grid factor => 25 min/mile
        rec["walkMinutes"] = max(1, int(round(dist * 25.0)))

    batch_size = 80
    print(f"Computing OSRM drive times to OSU Oval for {len(with_coords)} listings...")
    for start in range(0, len(with_coords), batch_size):
        chunk = with_coords[start : start + batch_size]
        coords = [(OSU_CENTER_LAT, OSU_CENTER_LNG)] + [(r["lat"], r["lng"]) for r in chunk]
        try:
            # destinations=0 gives durations[i][0] from each listing i to OSU Oval
            durations = osrm_table_durations(coords, destinations="0")
            for idx, rec in enumerate(chunk):
                dur_sec = durations[idx + 1][0]
                if dur_sec is not None:
                    rec["driveMinutes"] = round(float(dur_sec) / 60.0, 1)
                else:
                    rec["driveMinutes"] = None
        except Exception as exc:
            print(f"  Warning: OSRM drive-time batch failed: {exc}")
            for rec in chunk:
                rec["driveMinutes"] = None

        if start + batch_size < len(with_coords):
            time.sleep(0.35)


# ---------------------------------------------------------------------------
# Neighborhood inference
# ---------------------------------------------------------------------------

ZIP_NEIGHBORHOOD_HINTS = {
    "43201": "University District",
    "43202": "Old North",
    "43210": "University District",
    "43212": "Grandview Heights",
    "43214": "Clintonville",
    "43215": "Downtown",
    "43220": "Upper Arlington",
    "43221": "Upper Arlington",
    "43211": "Linden",
    "43209": "Bexley",
    "43206": "German Village",
    "43205": "Olde Towne East",
    "43213": "Whitehall",
    "43085": "Worthington",
    "43016": "Dublin",
    "43017": "Dublin",
    "43081": "Westerville",
    "43082": "Westerville",
    "43230": "Gahanna",
    "43026": "Hilliard",
    "43123": "Grove City",
}


def infer_neighborhood(lat: float, lng: float, zip_code: str | None) -> str:
    """Infer Columbus neighborhood from coordinates first, then ZIP code."""
    # Core inner-ring Columbus neighborhoods around OSU (checked tightest-first)
    if 39.988 <= lat <= 40.014 and -83.020 <= lng <= -82.996:
        return "University District"
    if 40.014 < lat <= 40.026 and -83.022 <= lng <= -82.996:
        return "Old North"
    if 39.984 <= lat < 39.996 and -83.005 <= lng <= -82.990:
        return "Weinland Park"
    if 39.973 <= lat < 39.986 and -83.004 <= lng <= -82.991:
        return "Italian Village"
    if 39.974 <= lat < 39.988 and -83.018 <= lng < -83.004:
        return "Victorian Village"
    if 39.970 <= lat < 39.986 and -83.006 <= lng <= -83.000:
        return "Short North"
    if 39.976 <= lat < 39.990 and -83.026 <= lng < -83.016:
        return "Harrison West"
    if 39.970 <= lat <= 40.000 and -83.065 <= lng < -83.024:
        return "Grandview Heights"
    if 39.998 <= lat <= 40.065 and -83.095 <= lng < -83.030:
        return "Upper Arlington"
    if 40.026 < lat <= 40.072 and -83.035 <= lng <= -82.990:
        return "Clintonville"
    if 40.005 <= lat <= 40.055 and -82.990 < lng <= -82.950:
        return "Linden"
    if 39.955 <= lat < 39.973 and -83.012 <= lng <= -82.988:
        return "Downtown"
    if 39.938 <= lat < 39.955 and -83.002 <= lng <= -82.985:
        return "German Village"
    if 39.948 <= lat < 39.973 and -83.040 <= lng < -83.012:
        return "Franklinton"
    if 39.955 <= lat < 39.975 and -82.988 < lng <= -82.955:
        return "Olde Towne East"
    if 39.955 <= lat <= 39.985 and -82.955 < lng <= -82.920:
        return "Bexley"
    if 40.072 < lat <= 40.115 and -83.045 <= lng <= -82.990:
        return "Worthington"

    if zip_code and zip_code in ZIP_NEIGHBORHOOD_HINTS:
        return ZIP_NEIGHBORHOOD_HINTS[zip_code]

    return "Columbus"


# ---------------------------------------------------------------------------
# Dataset build pipeline
# ---------------------------------------------------------------------------

def load_raw_file(path: Path, default_source: str) -> list[dict[str, Any]]:
    if not path.exists():
        print(f"Info: {path} not found — skipping.")
        return []
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as exc:
        print(f"Warning: failed to read {path}: {exc}")
        return []

    if isinstance(data, list):
        items = data
    elif isinstance(data, dict) and isinstance(data.get("listings"), list):
        items = data["listings"]
    else:
        print(f"Warning: unexpected JSON structure in {path} — skipping.")
        return []

    normalized: list[dict[str, Any]] = []
    for raw in items:
        if not isinstance(raw, dict):
            continue
        rec = normalize_raw_listing(raw, default_source)
        if rec is not None:
            normalized.append(rec)

    print(f"Loaded {len(items)} raw records from {path.name} -> {len(normalized)} valid 4BR listings.")
    return normalized


def build_dataset(*, dry_run: bool = False) -> dict[str, Any]:
    raw_osu = load_raw_file(RAW_OSU_PATH, "osu_offcampus")
    raw_landlords = load_raw_file(RAW_LANDLORDS_PATH, "landlord")
    raw_columbus = load_raw_file(RAW_COLUMBUS_PATH, "columbus")
    combined = raw_osu + raw_landlords + raw_columbus

    deduped = deduplicate_listings(combined)
    print(f"Deduplicated {len(combined)} -> {len(deduped)} unique 4BR properties.")

    geocode_missing_listings(deduped, dry_run=dry_run)
    compute_travel_times(deduped)

    # Filter to valid coordinates within 20-minute drive radius (or 15-mi fallback)
    filtered: list[dict[str, Any]] = []
    dropped_no_coords = 0
    dropped_too_far = 0

    for rec in deduped:
        if rec.get("lat") is None or rec.get("lng") is None:
            dropped_no_coords += 1
            continue

        drive_min = rec.get("driveMinutes")
        dist_mi = rec.get("distanceMiles", 999.0)
        if drive_min is not None:
            if drive_min > MAX_DRIVE_MINUTES:
                dropped_too_far += 1
                continue
        else:
            if dist_mi > FALLBACK_MAX_MILES:
                dropped_too_far += 1
                continue
            rec["driveMinutes"] = round(dist_mi * 2.2, 1)

        if not rec.get("neighborhood"):
            rec["neighborhood"] = infer_neighborhood(rec["lat"], rec["lng"], rec.get("zip"))

        # Remove internal normalization key before output
        rec.pop("_normAddress", None)
        filtered.append(rec)

    if dropped_no_coords or dropped_too_far:
        print(
            f"Filtered out {dropped_no_coords} ungeocodable and "
            f"{dropped_too_far} listings beyond {MAX_DRIVE_MINUTES}-min drive."
        )

    # Sort by rentTotal ascending, then driveMinutes ascending, then address
    filtered.sort(
        key=lambda r: (
            r["rentTotal"],
            r.get("driveMinutes") if r.get("driveMinutes") is not None else 999.0,
            r.get("address") or "",
        )
    )

    payload: dict[str, Any] = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "center": {
            "lat": OSU_CENTER_LAT,
            "lng": OSU_CENTER_LNG,
            "name": OSU_CENTER_NAME,
        },
        "maxDriveMinutes": MAX_DRIVE_MINUTES,
        "count": len(filtered),
        "listings": filtered,
    }

    if dry_run:
        print(f"[dry-run] Would write {len(filtered)} listings to {LISTINGS_OUT_PATH}.")
    else:
        LISTINGS_OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LISTINGS_OUT_PATH.open("w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        print(f"Wrote {len(filtered)} listings to {LISTINGS_OUT_PATH}.")

    return payload


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build OSU 4-bedroom housing dataset and 20-minute drive isochrone."
    )
    parser.add_argument(
        "--isochrone",
        action="store_true",
        help="Generate public/data/isochrone.geojson only.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Generate both public/data/isochrone.geojson and public/data/listings.json.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run dataset pipeline without writing public/data/listings.json or geocode cache.",
    )
    args = parser.parse_args(argv)

    if args.isochrone:
        generate_isochrone()
        return 0

    if args.all:
        generate_isochrone()
        build_dataset(dry_run=args.dry_run)
        return 0

    build_dataset(dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
