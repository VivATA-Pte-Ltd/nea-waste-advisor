#!/usr/bin/env python3
"""Discover the latest official NEA COPEH PDF, extract rates/rules, and publish standards.json.

Strict by design: any missing/ambiguous clause aborts without replacing the last-known-good manifest.
"""
from __future__ import annotations

import argparse
import hashlib
import html.parser
import json
import re
import sys
import tempfile
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import fitz

DISCOVERY_URL = "https://www.nea.gov.sg/corporate-functions/resources/practices-and-guidelines/guidelines/practices"
OFFICIAL_ORIGIN = "https://www.nea.gov.sg"
USER_AGENT = "VivATA-NEA-Standards-Monitor/1.0 (+GitHub Actions; official-document checker)"

RATE_SPECS = [
    ("Office / Classroom", r"Office\s*/\s*classroom", "area", "L per 100 sqm GFA", r"per\s+100\s+sq\s+m\s+gross\s+floor\s+area"),
    ("Hotel / Dormitory / Store / Industrial", r"Hotel\s*/\s*dormitory\s*/\s*store\s*/\s*industrial\s+premises", "area", "L per 100 sqm GFA", r"per\s+100\s+sq\s+m\s+gross\s+floor\s+area"),
    ("Retail Shop / Trade Premises", r"Retail\s+shop\s*/\s*trade\s+premises", "area", "L per 100 sqm GFA", r"per\s+100\s+sq\s+m\s+gross\s+floor\s+area"),
    ("Supermarket / Market / Department Store", r"Supermarket\s*/\s*market\s*/\s*department\s+store", "area", "L per 100 sqm GFA", r"per\s+100\s+sq\s+m\s+gross\s+floor\s+area"),
    ("Restaurant / Eating House / Food Centre / Canteen / Pantry / Food Shop / Food Processing Establishment", r"Restaurant\s*/\s*eating\s+house\s*/\s*food\s+centre\s*/\s*canteen\s*/\s*pantry\s*/\s*food\s+shop\s*/\s*food\s+processing\s+establishment", "area", "L per 100 sqm GFA", r"per\s+100\s+sq\s+m\s+gross\s+floor\s+area"),
    ("Residential Premises", r"Residential\s+premises", "units", "L per dwelling premises", r"per\s+dwelling\s+premises"),
    ("Petrol Station", r"Petrol\s+station", "units", "L per premises", r"per\s+premises"),
]

MONTHS = {name.lower(): index for index, name in enumerate(
    ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"], 1
)}


class PdfLinkParser(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        href = dict(attrs).get("href")
        if href and re.search(r"copeh[-_ ]?\d{4}[^?#]*\.pdf", href, re.I):
            self.links.append(urllib.parse.urljoin(OFFICIAL_ORIGIN, href))


def fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    with urllib.request.urlopen(request, timeout=60) as response:
        final = urllib.parse.urlparse(response.geturl())
        if final.scheme != "https" or final.hostname != "www.nea.gov.sg":
            raise RuntimeError(f"Refused non-official redirect: {response.geturl()}")
        return response.read()


def discover_latest_pdf() -> tuple[str, int]:
    page = fetch(DISCOVERY_URL).decode("utf-8", errors="replace")
    parser = PdfLinkParser()
    parser.feed(page)
    candidates: list[tuple[int, str]] = []
    for link in set(parser.links):
        match = re.search(r"copeh[-_ ]?(\d{4})", link, re.I)
        if match:
            candidates.append((int(match.group(1)), link))
    if not candidates:
        raise RuntimeError("No editioned COPEH PDF link found on the official NEA practices page")
    edition, url = max(candidates)
    return url, edition


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def unique_number(text: str, pattern: str, label: str, flags: int = re.I) -> float:
    matches = re.findall(pattern, text, flags)
    if not matches:
        raise RuntimeError(f"Expected at least one {label} match, found none")
    values = [float(str(item[0] if isinstance(item, tuple) else item).replace(",", "")) for item in matches]
    if len(set(values)) != 1:
        raise RuntimeError(f"Conflicting {label} values found: {sorted(set(values))}")
    return values[0]


def number_word_or_digits(word: str, digits: str) -> int:
    words = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7}
    value = int(digits)
    if word.lower() in words and words[word.lower()] != value:
        raise RuntimeError(f"Number wording mismatch: {word} ({digits})")
    return value


def parse_date(text: str, pattern: str, label: str) -> str:
    matches = re.findall(pattern, text, re.I)
    if not matches:
        raise RuntimeError(f"Could not extract {label}")
    unique = set(matches)
    if len(unique) != 1:
        raise RuntimeError(f"Ambiguous {label}: {sorted(unique)}")
    day, month, year = next(iter(unique))
    month_number = MONTHS.get(month.lower())
    if not month_number:
        raise RuntimeError(f"Unknown month in {label}: {month}")
    return f"{int(year):04d}-{month_number:02d}-{int(day):02d}"


def extract(pdf_bytes: bytes, source_url: str, link_edition: int) -> dict:
    document = fitz.open(stream=pdf_bytes, filetype="pdf")
    pages = [page.get_text("text") for page in document]
    full = normalize("\n".join(pages))
    page_one = next((normalize(text) for text in pages if re.search(r"1\.2\s+Refuse Output", text, re.I)), None)
    if not page_one:
        raise RuntimeError("Section 1.2 was not found in the PDF")
    section_match = re.search(r"1\.2\s+Refuse Output(.*?)1\.3\s+Refuse Chute", page_one, re.I)
    if not section_match:
        raise RuntimeError("Could not isolate Section 1.2 table")
    section = section_match.group(1)

    edition_matches = {int(x) for x in re.findall(r"Code of Practice on Environmental Health\s*\((\d{4}) Edition\)", full, re.I)}
    if edition_matches != {link_edition}:
        raise RuntimeError(f"PDF edition {sorted(edition_matches)} does not match discovered link edition {link_edition}")

    rates: dict[str, dict] = {}
    for category, category_pattern, unit_type, label, unit_pattern in RATE_SPECS:
        pattern = rf"{category_pattern}\s+(\d+(?:\.\d+)?)\s+{unit_pattern}"
        value = unique_number(section, pattern, f"rate for {category}")
        rates[category] = {"rate": int(value) if value.is_integer() else value, "unitType": unit_type, "label": label}

    bin_centre = unique_number(full, r"bin centre shall be provided if refuse output exceeds\s+([\d,]+)\s+litres/day", "bin-centre threshold")
    enclosed = unique_number(full, r"daily refuse output of the premises is\s+([\d,]+)\s+litres or more", "enclosed-system threshold")
    bin_capacity = unique_number(full, r"refuse bin shall have a maximum capacity of\s+([\d,]+)\s+litres", "wheeled-bin capacity")
    pwcs_units = unique_number(full, r"properties with\s+([\d,]+)\s+or more residential dwelling units", "PWCS unit threshold")
    food_area = unique_number(full, r"Operation area\s*>\s*([\d,]+)\s+sq m", "large food manufacturer area")

    storage_matches = re.findall(r"at least\s+(two)\s*\((\d+)\)\s+days of refuse output", full, re.I)
    if not storage_matches:
        raise RuntimeError("Two-day refuse storage clause not found")
    storage_days = number_word_or_digits(*storage_matches[0])
    if any(number_word_or_digits(*item) != storage_days for item in storage_matches):
        raise RuntimeError("Inconsistent storage-day clauses")

    recycle_match = re.search(r"additional\s+([\d.]+)\s*%\s+by volume.*?or\s+([\d,]+)\s+L/d", full, re.I)
    if not recycle_match:
        raise RuntimeError("Recyclables output formula not found")
    recycle_fraction = float(recycle_match.group(1)) / 100
    recycle_minimum = int(recycle_match.group(2).replace(",", ""))

    storey_match = re.search(r"taller than\s+(four)\s*\((\d+)\)\s+storeys", full, re.I)
    if not storey_match:
        raise RuntimeError("Residential chute storey threshold not found")
    chute_storeys = number_word_or_digits(*storey_match.groups())

    pwcs_date = parse_date(full, r"500 or more residential dwelling units.*?submitted to URA from\s+(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", "PWCS application date")
    recycling_date = parse_date(full, r"recyclables chute system.*?submitted to URA from\s+(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", "recyclables-chute application date")
    food_date = parse_date(full, r"All new commercial and industrial premises.*?requirements shall apply to new development applications submitted to URA from\s+(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", "food-waste application date")

    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    sha = hashlib.sha256(pdf_bytes).hexdigest()
    manifest = {
        "schemaVersion": 1,
        "generatedAt": now,
        "code": {
            "title": "NEA Code of Practice on Environmental Health",
            "edition": f"{link_edition} Edition",
            "sourceUrl": source_url,
            "sourceDiscoveryUrl": DISCOVERY_URL,
            "pdfSha256": sha,
            "fetchedAt": now,
        },
        "rates": rates,
        "rules": {
            "binCentreAboveLitresPerDay": int(bin_centre),
            "enclosedSystemAtOrAboveLitresPerDay": int(enclosed),
            "storageDays": storage_days,
            "wheeledBinCapacityLitres": int(bin_capacity),
            "pwcsResidentialUnits": int(pwcs_units),
            "recyclablesFraction": recycle_fraction,
            "recyclablesMinimumLitresPerDay": recycle_minimum,
            "largeFoodManufacturerOperationAreaSqm": int(food_area),
            "residentialChuteStoreysAbove": chute_storeys,
            "pwcsUraApplicationFrom": pwcs_date,
            "recyclablesChuteUraApplicationFrom": recycling_date,
            "foodWasteUraApplicationFrom": food_date,
        },
        "extraction": {
            "status": "validated",
            "engine": f"PyMuPDF {fitz.version[0]} + strict clause parser v1",
            "sourcePageCount": len(pages),
            "rateCategoryCount": len(rates),
            "warnings": [],
        },
    }
    validate(manifest)
    return manifest


def validate(data: dict) -> None:
    if len(data["rates"]) != len(RATE_SPECS):
        raise RuntimeError("Unexpected rate category count")
    expected_units = {spec[0]: spec[2] for spec in RATE_SPECS}
    for category, item in data["rates"].items():
        if category not in expected_units or item["unitType"] != expected_units[category]:
            raise RuntimeError(f"Unexpected category/unit combination: {category}")
        if not (0 < float(item["rate"]) <= 5000):
            raise RuntimeError(f"Out-of-range refuse rate: {category}")
    rules = data["rules"]
    if not (0 < rules["binCentreAboveLitresPerDay"] < rules["enclosedSystemAtOrAboveLitresPerDay"] <= 100000):
        raise RuntimeError("Infrastructure threshold validation failed")
    if not (1 <= rules["storageDays"] <= 14 and 1 <= rules["wheeledBinCapacityLitres"] <= 5000):
        raise RuntimeError("Storage/bin validation failed")
    if not (0 < rules["recyclablesFraction"] <= 1 and 1 <= rules["recyclablesMinimumLitresPerDay"] <= 10000):
        raise RuntimeError("Recyclables validation failed")
    if data["extraction"]["rateCategoryCount"] != 7:
        raise RuntimeError("Extractor did not obtain all seven expected categories")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="standards.json")
    parser.add_argument("--pdf-copy", default="data/latest-copeh.pdf")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--source-url", help="Test override; must still be on www.nea.gov.sg")
    args = parser.parse_args()

    source_url, edition = discover_latest_pdf() if not args.source_url else (args.source_url, int(re.search(r"(\d{4})", args.source_url).group(1)))
    pdf_bytes = fetch(source_url)
    if not pdf_bytes.startswith(b"%PDF-"):
        raise RuntimeError("Official source did not return a PDF")
    manifest = extract(pdf_bytes, source_url, edition)

    output = Path(args.output)
    if output.exists() and not args.force:
        previous = json.loads(output.read_text(encoding="utf-8"))
        if previous.get("code", {}).get("pdfSha256") == manifest["code"]["pdfSha256"]:
            print(f"UNCHANGED {manifest['code']['edition']} {manifest['code']['pdfSha256']}")
            return 0

    output.parent.mkdir(parents=True, exist_ok=True)
    Path(args.pdf_copy).parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=output.parent, suffix=".tmp") as handle:
        json.dump(manifest, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
        temp_manifest = Path(handle.name)
    temp_manifest.replace(output)
    Path(args.pdf_copy).write_bytes(pdf_bytes)
    print(f"UPDATED {manifest['code']['edition']} {manifest['code']['pdfSha256']}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise
