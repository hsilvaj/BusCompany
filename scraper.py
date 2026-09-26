import csv
import json
import os
import re
import time
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.buscaonibus.com.br/en/bus-companies"
LOGOS_DIR = Path("logos")
CSV_OUTPUT = Path("bus_companies.csv")
JSON_OUTPUT = Path("bus_companies.json")
COUNTRY = "Brazil"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}


def fetch_page(url: str) -> BeautifulSoup:
    print(f"Fetching {url} ...")
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "html.parser")


def normalize_logo_url(src: str) -> str:
    if src.startswith("//"):
        return "https:" + src
    return src


def slug_from_url(url: str) -> str:
    path = urlparse(url).path
    filename = path.rstrip("/").split("/")[-1]
    # sanitize for filesystem
    return re.sub(r"[^\w.\-]", "_", filename)


def download_logo(url: str, dest: Path) -> bool:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        dest.write_bytes(resp.content)
        return True
    except Exception as e:
        print(f"  [warn] Could not download {url}: {e}")
        return False


def parse_companies(soup: BeautifulSoup) -> list[dict]:
    seen_names: set[str] = set()
    companies: list[dict] = []
    id_counter = 1

    LOGOS_DIR.mkdir(exist_ok=True)

    imgs = soup.select('img[src*="/viacoes/"]')
    print(f"Found {len(imgs)} company images.")

    for img in imgs:
        # name is on the parent <a> tag, not on the <img>
        parent_a = img.find_parent("a")
        name = (
            (parent_a.get("title") if parent_a else None)
            or img.get("title")
            or img.get("alt")
            or ""
        ).strip()
        if not name:
            print("  [skip] Image with no company name, skipping.")
            continue

        key = name.lower()
        if key in seen_names:
            print(f"  [dup]  Skipping duplicate: {name}")
            continue
        seen_names.add(key)

        src = img.get("src", "")
        logo_file = ""
        if src:
            logo_url = normalize_logo_url(src)
            slug = slug_from_url(logo_url)
            dest = LOGOS_DIR / slug
            if download_logo(logo_url, dest):
                logo_file = slug
                print(f"  [{id_counter:03d}] {name} -> logos/{slug}")
            else:
                print(f"  [{id_counter:03d}] {name} -> logo download failed")
        else:
            print(f"  [{id_counter:03d}] {name} -> no logo URL")

        companies.append({
            "id": id_counter,
            "operator": name,
            "country": COUNTRY,
            "state": "",
            "logo_file": logo_file,
        })
        id_counter += 1

    return companies


def save_csv(companies: list[dict], path: Path) -> None:
    fields = ["id", "operator", "country", "state", "logo_file"]
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(companies)
    print(f"Saved {path} ({len(companies)} rows)")


def save_json(companies: list[dict], path: Path) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(companies, f, ensure_ascii=False, indent=2)
    print(f"Saved {path} ({len(companies)} entries)")


def main() -> None:
    soup = fetch_page(BASE_URL)
    companies = parse_companies(soup)

    if not companies:
        print("No companies found. Check if the page structure changed.")
        return

    save_csv(companies, CSV_OUTPUT)
    save_json(companies, JSON_OUTPUT)

    logos_downloaded = sum(1 for c in companies if c["logo_file"])
    print(
        f"\nDone. {len(companies)} companies collected, "
        f"{logos_downloaded} logos downloaded."
    )


if __name__ == "__main__":
    main()
