"""Sanatçıların şarkı listesini Deezer'dan, sözlerini LRCLIB'den çeker.

    python -m src.fetch_lyrics              # data/artists.txt içindeki herkes
    python -m src.fetch_lyrics Ceza Ezhel   # sadece verilen sanatçılar

Sözler data/lyrics/<sanatçı>/<şarkı>.json olarak saklanır (git'e girmez).
Daha önce indirilen şarkılar tekrar indirilmez; geçici hatalar kaydedilmez,
sonraki çalıştırmada yeniden denenir. Kapsama özeti: results/lyrics_coverage.csv
"""

from __future__ import annotations

import csv
import json
import re
import sys
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

from src.matcher import normalize

ROOT = Path(__file__).resolve().parent.parent
ARTISTS = ROOT / "data" / "artists.txt"
LYRICS = ROOT / "data" / "lyrics"
COVERAGE = ROOT / "results" / "lyrics_coverage.csv"
UA = {"User-Agent": "turkce-rap-futbolcu/0.1 (https://github.com/osmangazi7hub/turkce_rap_futbolcu)"}
WORKERS = 6

session = requests.Session()
session.headers.update(UA)


def get_json(url: str, params: dict | None = None, retries: int = 5):
    """GET + JSON; 404 -> None, 429/5xx/ağ hatası -> üstel bekleme ile tekrar."""
    for attempt in range(retries):
        try:
            r = session.get(url, params=params, timeout=30)
            if r.status_code == 404:
                return None
            if r.status_code == 200:
                data = r.json()
                # Deezer kota hatasını 200 ile döndürür
                if isinstance(data, dict) and data.get("error", {}).get("code") == 4:
                    raise requests.ConnectionError("Deezer kota")
                return data
        except (requests.RequestException, ValueError):
            pass
        time.sleep(2 ** (attempt + 1))
    raise RuntimeError(f"İstek başarısız: {url} {params}")


def slug(text: str) -> str:
    s = unicodedata.normalize("NFKD", normalize(text))
    return re.sub(r"[^a-z0-9]+", "_", s.encode("ascii", "ignore").decode()).strip("_")[:80] or "_"


def load_artists() -> list[tuple[str, int]]:
    out = []
    for line in ARTISTS.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name, _, did = (x.strip() for x in line.partition("|"))
        out.append((name, int(did)))
    return out


def deezer_tracks(artist_id: int) -> list[dict]:
    """Sanatçının albüm/EP/single'larındaki şarkılar (başlığa göre tekrarsız)."""
    tracks, seen = [], set()
    url, params = f"https://api.deezer.com/artist/{artist_id}/albums", {"limit": 100}
    while url:
        page = get_json(url, params) or {}
        params = None
        for album in page.get("data", []):
            t_page = get_json(f"https://api.deezer.com/album/{album['id']}/tracks", {"limit": 300}) or {}
            for t in t_page.get("data", []):
                key = normalize(re.sub(r"\s*[(\[].*?[)\]]", "", t["title"])).strip()
                if key in seen:
                    continue
                seen.add(key)
                tracks.append({
                    "title": t["title"], "title_short": t.get("title_short") or t["title"],
                    "album": album["title"], "release_date": album.get("release_date"),
                    "duration": t.get("duration"), "deezer_track_id": t["id"],
                    "track_artist": t.get("artist", {}).get("name"),
                })
        url = page.get("next")
    return tracks


def lrclib_lyrics(artist: str, track: dict) -> dict | None:
    params = {"artist_name": artist, "track_name": track["title_short"],
              "album_name": track["album"], "duration": track["duration"]}
    hit = get_json("https://lrclib.net/api/get", params)
    if not (hit and hit.get("plainLyrics")):
        res = get_json("https://lrclib.net/api/search",
                       {"artist_name": artist, "track_name": track["title_short"]}) or []
        hit = next((h for h in res if h.get("plainLyrics")
                    and normalize(artist) in normalize(h.get("artistName", ""))), None)
    return hit


def fetch_song(artist: str, artist_id: int, track: dict) -> str:
    path = LYRICS / slug(artist) / f"{slug(track['title'])}.json"
    if path.exists():
        return "found" if json.loads(path.read_text(encoding="utf-8"))["lyrics"] else "missing"
    try:
        hit = lrclib_lyrics(artist, track)
    except RuntimeError:
        return "error"          # kaydetme; sonra tekrar denensin
    rec = {"artist": artist, "deezer_artist_id": artist_id, **track,
           "lyrics": hit.get("plainLyrics") if hit else None,
           "instrumental": bool(hit and hit.get("instrumental")),
           "lrclib_id": hit.get("id") if hit else None, "source": "lrclib" if hit else None}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    return "found" if rec["lyrics"] else "missing"


def main() -> None:
    wanted = {normalize(a) for a in sys.argv[1:]}
    artists = [a for a in load_artists() if not wanted or normalize(a[0]) in wanted]
    rows = []
    if COVERAGE.exists():
        with open(COVERAGE, encoding="utf-8") as f:
            rows = [r for r in csv.DictReader(f) if normalize(r["artist"]) not in
                    {normalize(a) for a, _ in artists}]

    for name, did in artists:
        tracks = deezer_tracks(did)
        with ThreadPoolExecutor(WORKERS) as ex:
            results = list(ex.map(lambda t: fetch_song(name, did, t), tracks))
        found, missing, err = (results.count(k) for k in ("found", "missing", "error"))
        print(f"{name:<15} şarkı={len(tracks):<4} sözü bulunan={found:<4} "
              f"bulunamayan={missing:<4} hata={err}", flush=True)
        rows.append({"artist": name, "deezer_id": did, "tracks": len(tracks),
                     "lyrics_found": found, "lyrics_missing": missing, "errors": err})

    COVERAGE.parent.mkdir(exist_ok=True)
    with open(COVERAGE, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["artist", "deezer_id", "tracks", "lyrics_found",
                                          "lyrics_missing", "errors"])
        w.writeheader()
        w.writerows(rows)
    tot = sum(int(r["tracks"]) for r in rows), sum(int(r["lyrics_found"]) for r in rows)
    print(f"\nToplam {tot[0]} şarkı, {tot[1]} tanesinin sözü bulundu -> {COVERAGE.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
