#!/usr/bin/env python3
"""
Scrape strictly 4-bedroom off-campus housing listings near Ohio State University
from https://offcampus.osu.edu/myoffcampus/search-housing.aspx
and save normalized JSON to data/raw_osu.json.
"""

from __future__ import annotations

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://offcampus.osu.edu/myoffcampus/search-housing.aspx"
BASE_DIR_URL = "https://offcampus.osu.edu/myoffcampus/"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

MAX_WORKERS = 5
REQUEST_TIMEOUT = 25
MAX_REASONABLE_RENT = 15000  # Filter out obvious typos like $27,602,860


def clean_ws(text: str | None) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()


def clean_multiline(text: str | None) -> str:
    if not text:
        return ""
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    return "\n".join(lines)


def parse_yes_no(val: str | None) -> bool | None:
    if not val:
        return None
    v = val.strip().lower()
    if v in ("yes", "true", "y"):
        return True
    if v in ("no", "false", "n"):
        return False
    return None


def parse_bathrooms(val: str | None) -> float | None:
    if not val:
        return None
    full_m = re.search(r"(\d+)\s*full", val, re.I)
    half_m = re.search(r"(\d+)\s*half", val, re.I)
    if full_m or half_m:
        full = int(full_m.group(1)) if full_m else 0
        half = int(half_m.group(1)) if half_m else 0
        total = full + 0.5 * half
        return total if total > 0 else None
    num_m = re.search(r"(\d+(?:\.\d+)?)", val)
    if num_m:
        return float(num_m.group(1))
    return None


def parse_rent_total(
    rent_str: str | None,
    card_rent_str: str | None = None,
    bathrooms: float | None = None,
    description: str = "",
) -> int | None:
    """
    Parse OSU rent string into total monthly rent for the 4BR unit.
    OSU commonly formats 4BR rents as:
      - "$495.00 - $1,980.00" (per-person - total)
      - "$3,200.00" (total)
      - "$650.00" (per-person -> multiply by 4)
      - "$2,400.00 - $2,800.00" (total range -> use low)
    Returns None if missing, <= 0, or clearly bogus (> MAX_REASONABLE_RENT).
    """
    def extract_nums(s: str | None) -> list[float]:
        if not s:
            return []
        raw = re.findall(r"\$?\s*([\d,]+(?:\.\d+)?)", s)
        nums = []
        for token in raw:
            try:
                v = float(token.replace(",", ""))
                if v > 0:
                    nums.append(v)
            except ValueError:
                pass
        return nums

    nums = extract_nums(rent_str)
    if not nums:
        nums = extract_nums(card_rent_str)
    if not nums:
        return None

    # Filter out obvious typos (e.g., $27,602,860)
    valid = [n for n in nums if n <= MAX_REASONABLE_RENT]
    if not valid:
        return None

    per_person_hint = bool(
        re.search(r"\b(per\s+person|per\s+bed|/\s*person|/\s*bed)\b", rent_str or "", re.I)
    )

    if len(valid) == 1:
        val = valid[0]
        # Per-person if < $1,100, explicitly labeled per-person/bed, or a 4BR/4BA tower priced < $1,500
        if val < 1100 or (per_person_hint and val < 2000) or (bathrooms is not None and bathrooms >= 4.0 and val < 1500):
            total = round(val * 4)
        else:
            total = round(val)
    else:
        low, high = valid[0], valid[-1]
        if low < 1100 and high >= 1100:
            # Classic OSU format: "$per_person - $total" where high ~= 4 * low
            if 3.2 * low <= high <= 4.8 * low:
                total = round(high)
            else:
                # Wide multi-unit range like "$490 - $5,000"; estimate 4BR from per-person low
                total = round(low * 4)
        elif low >= 1100:
            # Both numbers are total monthly rents (unless per-person luxury tower)
            if (per_person_hint and low < 2000) or (bathrooms is not None and bathrooms >= 4.0 and low < 1500):
                total = round(low * 4)
            else:
                total = round(low)
        else:
            # Both numbers are per-person (< 1100)
            total = round(low * 4)

    if total <= 0 or total > MAX_REASONABLE_RENT:
        return None
    return total


def parse_lat_lng(html: str) -> tuple[float | None, float | None]:
    # Google Maps link: https://www.google.com/maps/place/39.996870,-83.002501
    m = re.search(
        r"google\.com/maps/place/(-?\d+\.\d+)\s*,\s*(-?\d+\.\d+)", html, re.I
    )
    if not m:
        m = re.search(
            r"staticmap\?center=(-?\d+\.\d+)\s*,\s*(-?\d+\.\d+)", html, re.I
        )
    if m:
        try:
            lat = float(m.group(1))
            lng = float(m.group(2))
            # Sanity check: Columbus OH area roughly 39.5..40.5, -83.5..-82.5
            if 39.0 <= lat <= 41.0 and -84.0 <= lng <= -82.0:
                return lat, lng
        except ValueError:
            pass
    return None, None


def extract_sections(container: BeautifulSoup) -> tuple[dict[str, dict[str, str]], str]:
    """
    Parse <h2>Section</h2> followed by <ul><li><strong>Key:</strong> Value</li></ul>
    and <p> under Comments.
    """
    sections: dict[str, dict[str, str]] = {}
    comments_parts: list[str] = []
    current_section: str | None = None

    for child in container.children:
        if not getattr(child, "name", None):
            continue
        tag = child.name.lower()
        if tag == "h2":
            current_section = clean_ws(child.get_text(" ", strip=True))
            sections.setdefault(current_section, {})
        elif tag == "ul" and current_section:
            for li in child.find_all("li", recursive=False):
                strong = li.find("strong")
                if not strong:
                    continue
                key = clean_ws(strong.get_text(" ", strip=True)).rstrip(":")
                # Extract value by removing strong text from li text
                li_copy = BeautifulSoup(str(li), "lxml").find("li")
                if li_copy and li_copy.find("strong"):
                    li_copy.find("strong").decompose()
                    raw_val = li_copy.get_text("\n", strip=True)
                else:
                    raw_val = li.get_text(" ", strip=True)
                val = clean_multiline(raw_val) if key.lower() == "other amenities" else clean_ws(raw_val)
                sections[current_section][key] = val
        elif tag == "p" and current_section and current_section.lower() == "comments":
            txt = clean_multiline(child.get_text("\n", strip=True))
            if txt:
                comments_parts.append(txt)

    return sections, "\n".join(comments_parts)


def extract_photos(soup: BeautifulSoup) -> list[str]:
    photos: list[str] = []
    seen: set[str] = set()

    # Prefer full-size photo links (posts/vendors/properties/...)
    for a in soup.find_all("a", href=re.compile(r"posts/vendors/properties/", re.I)):
        href = a.get("href", "").strip()
        if not href:
            continue
        full_url = urljoin(BASE_DIR_URL, href)
        if full_url not in seen:
            seen.add(full_url)
            photos.append(full_url)

    # Fallback to -big images if no <a> links found
    if not photos:
        for img in soup.find_all("img", src=re.compile(r"posts/vendors/properties/", re.I)):
            src = img.get("src", "").strip()
            if not src or "-thumbnail" in src.lower():
                continue
            full_url = urljoin(BASE_DIR_URL, src)
            if full_url not in seen:
                seen.add(full_url)
                photos.append(full_url)

    return photos


def build_parking(parking_sec: dict[str, str]) -> str | None:
    has_parking = parse_yes_no(parking_sec.get("Parking"))
    if has_parking is False:
        return "None"

    parts: list[str] = []
    if parse_yes_no(parking_sec.get("Off-street Parking")):
        spaces = parking_sec.get("Number of Parking Spaces", "").strip()
        monthly = re.sub(r"\$+", "$", parking_sec.get("Off-street Monthly", "").strip())
        label = "Off-street"
        if spaces and spaces.isdigit() and int(spaces) > 0:
            label += f" ({spaces} spaces)"
        if monthly and monthly.lower() not in ("n/a", "0", "$0", "$0.00"):
            label += f" ({monthly}/mo)"
        parts.append(label)
    if parse_yes_no(parking_sec.get("Garage Parking")):
        monthly = re.sub(r"\$+", "$", parking_sec.get("Garage Monthly", "").strip())
        label = "Garage"
        if monthly and monthly.lower() not in ("n/a", "0", "$0", "$0.00"):
            label += f" ({monthly}/mo)"
        parts.append(label)
    if parse_yes_no(parking_sec.get("On-street Parking")):
        permit = parse_yes_no(parking_sec.get("On-street Permit Required"))
        if permit is True:
            parts.append("On-street (permit required)")
        else:
            parts.append("On-street")

    if parts:
        return ", ".join(parts)
    if has_parking is True:
        return "Available"
    return None


def build_pet_info(pet_sec: dict[str, str]) -> tuple[bool | None, str | None]:
    pets_allowed = parse_yes_no(pet_sec.get("Pets Allowed"))
    dogs = parse_yes_no(pet_sec.get("Dogs Allowed"))
    cats = parse_yes_no(pet_sec.get("Cats Allowed"))

    if pets_allowed is None:
        if dogs is True or cats is True:
            pets_allowed = True
        elif dogs is False and cats is False:
            pets_allowed = False

    if pets_allowed is False:
        return False, "No pets allowed"

    parts: list[str] = []
    if dogs is True and cats is True:
        parts.append("Dogs & Cats allowed")
    elif dogs is True:
        parts.append("Dogs allowed")
    elif cats is True:
        parts.append("Cats allowed")
    elif pets_allowed is True:
        parts.append("Pets allowed")

    for label, key in [
        ("Deposit", "Pet Deposit"),
        ("Pet rent", "Additional Pet Rent"),
        ("Dog rent", "Additional Dog Rent"),
        ("Cat rent", "Additional Cat Rent"),
    ]:
        val = pet_sec.get(key, "").strip()
        if val and val not in ("$0", "$0.00", "0", "n/a", "N/A"):
            parts.append(f"{label}: {val}")

    policy = "; ".join(parts) if parts else None
    return pets_allowed, policy


def build_amenities(
    details_sec: dict[str, str],
    amenities_sec: dict[str, str],
    utilities_sec: dict[str, str],
    listing_sec: dict[str, str],
) -> list[str]:
    items: list[str] = []

    ac = amenities_sec.get("Air Conditioning", "").strip()
    if ac and ac.lower() not in ("no", "none", "n/a"):
        items.append(ac)

    laundry = details_sec.get("Laundry", "").strip()
    if laundry and laundry.lower() not in ("no", "none", "n/a"):
        items.append(laundry)

    bool_fields = [
        (amenities_sec, "Dishwasher", "Dishwasher"),
        (amenities_sec, "Stove", "Stove"),
        (amenities_sec, "Refrigerator", "Refrigerator"),
        (amenities_sec, "Furnished", "Furnished"),
        (amenities_sec, "Fireplace", "Fireplace"),
        (amenities_sec, "Security System", "Security System"),
        (amenities_sec, "Backyard", "Backyard"),
        (amenities_sec, "Deck Or Porch", "Deck/Porch"),
        (details_sec, "Basement", "Basement"),
        (details_sec, "Wheel Chair Access", "Wheelchair Accessible"),
        (utilities_sec, "Water Included", "Water Included"),
        (utilities_sec, "Electric Included", "Electric Included"),
        (utilities_sec, "Gas Included", "Gas Included"),
        (listing_sec, "Sublease Permitted", "Sublease Permitted"),
    ]
    for sec, key, label in bool_fields:
        if parse_yes_no(sec.get(key)) is True:
            items.append(label)

    # Deduplicate preserving order
    return list(dict.fromkeys(items))


def collect_listing_ids(session: requests.Session) -> list[dict[str, str]]:
    """
    Crawl all paginated search result pages for beds=4&campus=1 (Columbus).
    Returns list of dicts with property_id, card_title, card_rent.
    """
    listings: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    page = 0
    max_pages = 50  # safety bound

    while page < max_pages:
        params = {
            "page": page,
            "pricefrom": 0,
            "beds": 4,
            "campus": 1,
            "sort": 1,
            "alllandlords": 0,
        }
        resp = session.get(BASE_URL, params=params, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        cards = soup.select(".c-propertycard")
        if not cards:
            break

        new_on_page = 0
        for card in cards:
            a = card.find("a", href=re.compile(r"property=(\d+)", re.I))
            if not a:
                continue
            m = re.search(r"property=(\d+)", a["href"], re.I)
            if not m:
                continue
            pid = m.group(1)
            if pid in seen_ids:
                continue

            # Pre-check card bedrooms text if available
            dds = [clean_ws(dd.get_text(" ", strip=True)) for dd in card.find_all("dd")]
            card_rent = dds[0] if len(dds) > 0 else ""
            card_beds = dds[1] if len(dds) > 1 else ""
            bed_m = re.search(r"(\d+)\s*bed", card_beds, re.I)
            if bed_m and int(bed_m.group(1)) != 4:
                continue

            seen_ids.add(pid)
            new_on_page += 1
            h2 = card.find("h2")
            listings.append(
                {
                    "property_id": pid,
                    "card_title": clean_ws(h2.get_text(" ", strip=True)) if h2 else "",
                    "card_rent": card_rent,
                }
            )

        print(f"[Page {page}] Found {len(cards)} cards ({new_on_page} new 4BR IDs)")

        # Check if there is a Next link
        next_link = soup.find("a", string=re.compile(r"Next", re.I))
        if not next_link or new_on_page == 0:
            break
        page += 1
        time.sleep(0.25)

    return listings


def fetch_and_parse_detail(item: dict[str, str]) -> dict[str, Any] | None:
    pid = item["property_id"]
    url = f"{BASE_URL}?property={pid}"

    session = requests.Session()
    session.headers.update(HEADERS)

    for attempt in range(3):
        try:
            resp = session.get(url, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            break
        except requests.RequestException as exc:
            if attempt == 2:
                print(f"  [WARN] Failed to fetch property {pid}: {exc}")
                return None
            time.sleep(1.0 * (attempt + 1))

    html = resp.text
    soup = BeautifulSoup(html, "lxml")

    h1 = soup.find("h1")
    if not h1:
        print(f"  [WARN] No <h1> on property {pid}, skipping")
        return None

    container = h1.parent
    sections, comments = extract_sections(container)

    listing_sec = sections.get("Listing Information", {})
    details_sec = sections.get("Property Details", {})
    parking_sec = sections.get("Parking Information", {})
    amenities_sec = sections.get("Amenities", {})
    pet_sec = sections.get("Pet Information", {})
    utilities_sec = sections.get("Utilities", {})

    # Strictly enforce 4 bedrooms
    beds_str = details_sec.get("Bedrooms", "")
    bed_m = re.search(r"(\d+)", beds_str)
    if not bed_m or int(bed_m.group(1)) != 4:
        print(f"  [SKIP] Property {pid} bedrooms={beds_str!r} != 4")
        return None

    bathrooms = parse_bathrooms(details_sec.get("Bathrooms"))

    desc_parts = []
    other_am = amenities_sec.get("Other Amenities", "").strip()
    if other_am:
        desc_parts.append(other_am)
    if comments:
        desc_parts.append(comments)
    description = "\n\n".join(desc_parts)

    # Parse rent (skip listings without a valid positive rent)
    rent_total = parse_rent_total(
        listing_sec.get("Monthly Rent"),
        item.get("card_rent"),
        bathrooms=bathrooms,
        description=description,
    )
    if rent_total is None:
        print(
            f"  [SKIP] Property {pid} invalid/missing rent: "
            f"detail={listing_sec.get('Monthly Rent')!r}, card={item.get('card_rent')!r}"
        )
        return None

    title = clean_ws(h1.get_text(" ", strip=True)) or item.get("card_title") or f"OSU Property {pid}"

    # Build clean full street address
    city_raw = details_sec.get("City", "")
    city = re.sub(r"\s*,\s*", ", ", clean_ws(city_raw))
    if not city:
        city = "Columbus, OH"
    if "columbus" in title.lower() or re.search(r",\s*OH\b", title, re.I):
        address = title
    else:
        address = f"{title}, {city}"

    neighborhood = details_sec.get("Location Sector") or None
    if neighborhood:
        neighborhood = clean_ws(neighborhood)

    lat, lng = parse_lat_lng(html)

    # Sqft is rarely listed on OSU; check details_sec or description
    sqft: int | None = None
    sqft_raw = details_sec.get("Square Feet") or details_sec.get("Sq Ft") or ""
    sqft_m = re.search(r"([\d,]+)", sqft_raw)
    if sqft_m:
        try:
            sqft = int(sqft_m.group(1).replace(",", ""))
        except ValueError:
            sqft = None

    available_date = listing_sec.get("Move In Date") or None
    if available_date and available_date.lower() in ("n/a", "none"):
        available_date = None

    lease_term = listing_sec.get("Lease Term") or None
    if lease_term and lease_term.lower() in ("n/a", "none"):
        lease_term = None

    landlord = listing_sec.get("Property Owner") or "OSU Off-Campus Landlord"
    landlord = clean_ws(landlord) or "OSU Off-Campus Landlord"

    parking = build_parking(parking_sec)
    pets_allowed, pet_policy = build_pet_info(pet_sec)
    amenities = build_amenities(details_sec, amenities_sec, utilities_sec, listing_sec)

    photos = extract_photos(soup)

    return {
        "id": f"osu-{pid}",
        "source": "OSU Off-Campus",
        "title": title,
        "address": address,
        "neighborhood": neighborhood,
        "lat": lat,
        "lng": lng,
        "rentTotal": rent_total,
        "rentPerPerson": round(rent_total / 4),
        "bedrooms": 4,
        "bathrooms": bathrooms,
        "sqft": sqft,
        "availableDate": available_date,
        "leaseTerm": lease_term,
        "landlord": landlord,
        "parking": parking,
        "petsAllowed": pets_allowed,
        "petPolicy": pet_policy,
        "amenities": amenities,
        "description": description,
        "photos": photos,
        "url": url,
    }


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    out_path = root / "data" / "raw_osu.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    session.headers.update(HEADERS)

    print("Collecting 4-bedroom listing IDs from offcampus.osu.edu...")
    items = collect_listing_ids(session)
    print(f"Total unique 4BR candidate IDs collected: {len(items)}")

    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(fetch_and_parse_detail, item): item for item in items}
        completed = 0
        for future in as_completed(futures):
            completed += 1
            record = future.result()
            if record is not None:
                results.append(record)
            if completed % 20 == 0 or completed == len(items):
                print(f"  Processed {completed}/{len(items)} detail pages ({len(results)} valid 4BR)")

    # Sort deterministically by rentTotal ascending, then id
    results.sort(key=lambda r: (r["rentTotal"], r["id"]))

    with out_path.open("w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print(f"\nSaved {len(results)} strictly 4-bedroom listings to {out_path}")
    if results:
        rents = [r["rentTotal"] for r in results]
        with_coords = sum(1 for r in results if r["lat"] is not None and r["lng"] is not None)
        with_photos = sum(1 for r in results if r["photos"])
        print(f"Rent total range: ${min(rents):,} - ${max(rents):,}/mo")
        print(f"Rent per person range: ${min(r['rentPerPerson'] for r in results):,} - ${max(r['rentPerPerson'] for r in results):,}/mo")
        print(f"With lat/lng: {with_coords}/{len(results)} | With photos: {with_photos}/{len(results)}")


if __name__ == "__main__":
    main()
