"""data/lyrics/ altındaki sözlerde futbolcu isimlerini tarar.

    python -m src.scan

Çıktılar:
  results/matches.csv  her eşleşen satır (kesin + elle kontrol edilecek)
  results/summary.md   özet: en çok anılan futbolcular, sanatçı bazında dağılım
"""

from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

from src.matcher import Matcher

ROOT = Path(__file__).resolve().parent.parent
LYRICS = ROOT / "data" / "lyrics"
PLAYERS = ROOT / "data" / "players.json"
OUT_CSV = ROOT / "results" / "matches.csv"
OUT_MD = ROOT / "results" / "summary.md"

FIELDS = ["artist", "song", "album", "release_date", "player", "wikidata_id", "tier",
          "term", "ambiguous", "line"]


def scan() -> tuple[list[dict], Counter]:
    matcher = Matcher.from_file(PLAYERS, include_ambiguous=True)
    players = json.loads(PLAYERS.read_text(encoding="utf-8"))
    tiers = {p["wikidata_id"]: p["tier"] for p in players}

    rows, songs = [], Counter()
    for path in sorted(LYRICS.glob("*/*.json")):
        rec = json.loads(path.read_text(encoding="utf-8"))
        if not rec.get("lyrics"):
            continue
        songs[rec["artist"]] += 1
        seen = set()
        for line in rec["lyrics"].splitlines():
            line = line.strip()
            for m in matcher.find(line):
                key = (m.wikidata_id, line.rstrip(",.!? ").lower())
                if key in seen:          # nakarat tekrarları bir kez sayılır
                    continue
                seen.add(key)
                rows.append({
                    "artist": rec["artist"], "song": rec["title"], "album": rec.get("album"),
                    "release_date": rec.get("release_date"), "player": m.name,
                    "wikidata_id": m.wikidata_id, "tier": tiers.get(m.wikidata_id),
                    "term": m.term, "ambiguous": "evet" if m.ambiguous else "hayir",
                    "line": line,
                })
    return rows, songs


def write_summary(rows: list[dict], songs: Counter) -> None:
    sure = [r for r in rows if r["ambiguous"] == "hayir"]
    by_player = defaultdict(set)
    for r in sure:
        by_player[(r["player"], r["tier"])].add((r["artist"], r["song"]))
    by_artist = defaultdict(set)
    for r in sure:
        by_artist[r["artist"]].add(r["player"])

    md = ["# Türkçe Rapte Futbolcular — Sonuçlar", "",
          f"Taranan: **{len(songs)} sanatçı, {sum(songs.values())} şarkı**. "
          f"Kesin eşleşme: **{len(sure)} satır, {len(by_player)} farklı futbolcu**.", "",
          "## En çok anılan futbolcular", "",
          "| # | Futbolcu | Tier | Şarkı sayısı | Sanatçılar |", "|---|---|---|---|---|"]
    ranked = sorted(by_player.items(), key=lambda x: (-len(x[1]), x[0][0]))
    for i, ((name, tier), hits) in enumerate(ranked, 1):
        artists = Counter(a for a, _ in hits)
        md.append(f"| {i} | {name} | {tier} | {len(hits)} | "
                  + ", ".join(f"{a} ({n})" for a, n in artists.most_common()) + " |")

    md += ["", "## Sanatçı bazında", "",
           "| Sanatçı | Taranan şarkı | Farklı futbolcu | Futbolcular |", "|---|---|---|---|"]
    for artist, n in sorted(songs.items(), key=lambda x: -len(by_artist.get(x[0], ()))):
        ps = sorted(by_artist.get(artist, ()))
        md.append(f"| {artist} | {n} | {len(ps)} | {', '.join(ps)} |")

    amb = [r for r in rows if r["ambiguous"] == "evet"]
    md += ["", f"## Elle kontrol edilecekler ({len(amb)})", "",
           "Bu terimler gündelik kelimelerle ya da başka oyuncularla karışabilir "
           "(ör. *kaka*, *salah*). Tamamı `results/matches.csv` içinde `ambiguous=evet`.", "",
           "| Terim | Olası futbolcu | Satır sayısı |", "|---|---|---|"]
    for (term, player), n in Counter((r["term"], r["player"]) for r in amb).most_common(40):
        md.append(f"| {term} | {player} | {n} |")
    OUT_MD.write_text("\n".join(md) + "\n", encoding="utf-8")


def main() -> None:
    rows, songs = scan()
    OUT_CSV.parent.mkdir(exist_ok=True)
    with open(OUT_CSV, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    write_summary(rows, songs)
    sure = sum(r["ambiguous"] == "hayir" for r in rows)
    print(f"{len(songs)} sanatçı, {sum(songs.values())} şarkı tarandı: "
          f"{sure} kesin, {len(rows) - sure} kontrol edilecek eşleşme -> results/")


if __name__ == "__main__":
    main()
