"""Wikidata'dan futbolcu havuzunu oluşturur -> data/players.json

Kapsam (config.yaml): dünyanın tüm zamanlardaki en bilinen N futbolcusu +
Süper Lig'de oynamışların en bilinen M'si. Bilinirlik = Wikidata sitelink
sayısı. Oyuncular S/A/B/C (dünya sırası) ve SL (yalnızca Süper Lig) tier'larına ayrılır.

Çalıştırma:  python -m src.build_players
"""

from __future__ import annotations

import csv
import json
import random
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import requests
import yaml

from src.matcher import normalize, tokenize_term

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "cache"
OUT = ROOT / "data" / "players.json"
MANUAL = ROOT / "data" / "manual_players.csv"
MANUAL_ALIASES = ROOT / "data" / "manual_aliases.csv"
COMMON_WORDS = ROOT / "data" / "common_words_tr.txt"

SPARQL_URL = "https://query.wikidata.org/sparql"
HEADERS = {
    "User-Agent": "turkce-rap-futbolcu/0.1 (https://github.com/osmangazi7hub/turkce_rap_futbolcu)",
    "Accept": "application/sparql-results+json",
}
TURKEY = "Q43"

session = requests.Session()
session.headers.update(HEADERS)


# --------------------------------------------------------------------------- #
# SPARQL
# --------------------------------------------------------------------------- #

def sparql(query: str, retries: int = 6) -> list[dict]:
    """SPARQL sorgusu; 429/5xx/timeout durumunda üstel bekleme ile tekrar dener."""
    for attempt in range(retries):
        try:
            r = session.post(SPARQL_URL, data={"query": query}, timeout=90)
            if r.status_code == 200:
                rows = r.json()["results"]["bindings"]
                out = []
                for row in rows:
                    d = {k: v["value"] for k, v in row.items()}
                    d.update({f"{k}@lang": v["xml:lang"] for k, v in row.items() if "xml:lang" in v})
                    out.append(d)
                return out
            if r.status_code in (429, 500, 502, 503, 504):
                wait = int(r.headers.get("Retry-After", 0)) or 2 ** (attempt + 1)
                print(f"   SPARQL {r.status_code}, {wait}s bekleniyor...", file=sys.stderr)
                time.sleep(wait)
                continue
            r.raise_for_status()
        except (requests.Timeout, requests.ConnectionError, ValueError) as e:
            wait = 2 ** (attempt + 1)
            print(f"   SPARQL hata ({type(e).__name__}), {wait}s bekleniyor...", file=sys.stderr)
            time.sleep(wait)
    raise RuntimeError("SPARQL sorgusu tekrar denemelere rağmen başarısız")


def qid(uri: str) -> str:
    return uri.rsplit("/", 1)[-1]


def values(ids) -> str:
    return " ".join(f"wd:{i}" for i in ids)


def chunks(seq, n):
    seq = list(seq)
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def league_clubs(league_qid: str) -> set[str]:
    """Lige bağlı kulüpler: P118 (geçmiş kayıtlar dahil) + lig sezonu katılımcıları."""
    rows = sparql(f"""
        SELECT DISTINCT ?club WHERE {{
          {{ ?club p:P118/ps:P118 wd:{league_qid} }}
          UNION {{ ?season wdt:P3450 wd:{league_qid} ; wdt:P1923 ?club }}
          FILTER NOT EXISTS {{ ?club wdt:P31 wd:Q5 }}
        }}""")
    return {qid(r["club"]) for r in rows}


def club_players(clubs: list[str], min_sitelinks: int) -> list[dict]:
    """Kulüplerin oyuncuları + kulüp kaydının başlangıç/bitiş tarihleri."""
    sl_filter = f"FILTER(?sl >= {min_sitelinks})" if min_sitelinks > 0 else ""
    rows = sparql(f"""
        SELECT ?p ?sl ?start ?end ?birth WHERE {{
          VALUES ?club {{ {values(clubs)} }}
          ?p p:P54 ?st . ?st ps:P54 ?club .
          ?p wdt:P31 wd:Q5 ; wikibase:sitelinks ?sl .
          {sl_filter}
          OPTIONAL {{ ?st pq:P580 ?start }}
          OPTIONAL {{ ?st pq:P582 ?end }}
          OPTIONAL {{ ?p wdt:P569 ?birth }}
        }}""")
    return rows


def female_ids(ids: list[str]) -> list[str]:
    rows = sparql(f"""
        SELECT ?p WHERE {{ VALUES ?p {{ {values(ids)} }} ?p wdt:P21 wd:Q6581072 . }}""")
    return [qid(r["p"]) for r in rows]


def player_details(ids: list[str], label_langs: list[str], alias_langs: list[str]) -> list[dict]:
    langs = ", ".join(f'"{l}"' for l in label_langs)
    alangs = ", ".join(f'"{l}"' for l in alias_langs)
    return sparql(f"""
        SELECT ?p ?kind ?name WHERE {{
          VALUES ?p {{ {values(ids)} }}
          {{ ?p rdfs:label ?name . FILTER(LANG(?name) IN ({langs})) BIND("label" AS ?kind) }}
          UNION {{ ?p skos:altLabel ?name . FILTER(LANG(?name) IN ({alangs})) BIND("alias" AS ?kind) }}
          UNION {{ ?p wdt:P734 ?f . ?f rdfs:label ?name . FILTER(LANG(?name) IN ("mul", "en", "tr"))
                   BIND("surname" AS ?kind) }}
          UNION {{ ?p wdt:P27 wd:{TURKEY} . BIND("TR" AS ?name) BIND("citizen" AS ?kind) }}
        }}""")


# --------------------------------------------------------------------------- #
# İsim varyantları ve eşleşme kuralları
# --------------------------------------------------------------------------- #

PHONETIC_RULES = [
    ("sch", "s"), ("sh", "s"), ("ou", "u"), ("ck", "k"), ("qu", "k"), ("q", "k"),
    ("ph", "f"), ("th", "t"), ("eij", "ay"), ("ij", "ay"), ("w", "v"), ("x", "ks"),
    ("ee", "i"), ("oo", "u"), ("aa", "a"),
]


def turkish_phonetic(name: str) -> str:
    """Yabancı ismin Türkçe okunuşa yakın yazımı: Aboubakar->abubakar,
    Koulibaly->kulibali, Carrasco->karasko, Sneijder->snayder."""
    s = normalize(name).replace("'", "")
    for a, b in PHONETIC_RULES:
        s = s.replace(a, b)
    s = re.sub(r"c(?=[aou])", "k", s)
    s = re.sub(r"([b-df-hj-np-tv-z])\1", r"\1", s)    # çift ünsüz -> tek
    s = re.sub(r"e?y\b", "i", s)                        # sondaki (e)y -> i
    return s


def clean_alias(a: str) -> str | None:
    a = re.sub(r"\s*\(.*?\)\s*", " ", a).strip()
    if len(normalize(a).replace(" ", "")) < 3 or a.isdigit():
        return None
    return a


def load_wordlist(url: str) -> set[str]:
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / "turkish_words.txt"
    if not path.exists():
        print("Türkçe kelime listesi indiriliyor...")
        r = session.get(url, timeout=60)
        r.raise_for_status()
        path.write_text(r.text, encoding="utf-8")
    words = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        w = line.strip()
        if w and " " not in w:
            words.add(normalize(w).replace("'", ""))
    return words


FREQ_URL = "https://raw.githubusercontent.com/hermitdave/FrequencyWords/master/content/2018/{lang}/{lang}_50k.txt"


def load_frequency(lang: str, top: int) -> dict[str, int]:
    """OpenSubtitles kelime sıklığı listesi (çekimli halleriyle): kelime -> sıra."""
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f"freq_{lang}.txt"
    if not path.exists():
        r = session.get(FREQ_URL.format(lang=lang), timeout=60)
        r.raise_for_status()
        path.write_text(r.text, encoding="utf-8")
    ranks = {}
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines()[:top], 1):
        w = normalize(line.split(" ", 1)[0]).replace("'", "")
        ranks.setdefault(w, i)
    return ranks


def build_record(pid: str, info: dict, leagues: set[str], sitelinks: int) -> dict | None:
    labels: dict[str, str] = info["labels"]
    full_name = next((labels[l] for l in ("tr", "en", "mul") if l in labels), None) \
        or next(iter(labels.values()), None)
    if not full_name:
        return None
    known_as = []
    for n in list(labels.values()) + info["aliases"]:
        n = clean_alias(n)
        if n and n != full_name and normalize(n) != normalize(full_name) \
                and normalize(n) not in {normalize(k) for k in known_as}:
            known_as.append(n)
    surname = info["surname"]
    if not surname and len(tokenize_term(full_name)) >= 2:
        surname = full_name.split()[-1]
    return {
        "wikidata_id": pid,
        "full_name": full_name,
        "known_as": known_as,
        "surname": surname,
        "leagues": sorted(leagues),
        "sitelinks": sitelinks,
        "turkish": info["turkish"],
        # Etiket olarak tek kelimelik isimler (Ronaldinho, Pelé) "lakap" sayılır.
        "_mononyms": {normalize(v).replace("'", "") for v in labels.values()
                      if len(tokenize_term(v)) == 1},
    }


def apply_rules(players: list[dict], words: set[str], min_surname_len: int,
                dominance_ratio: float = 1.8, dominance_min_sitelinks: int = 30,
                foreign: dict[str, int] | None = None, foreign_top: int = 15000,
                foreign_top_famous: int = 2000, famous_sitelinks: int = 80) -> None:
    """search_terms / ambiguous_terms / variants / ambiguous alanlarını doldurur.

    words:   Türkçe kelimeler (TDK + sık kullanılan çekimli haller) -> tek başına aranmaz.
    foreign: yabancı dillerde kelime -> en iyi sıklık sırası. İlk `foreign_top`
             kelimeden biriyse aranmaz; çok ünlü oyuncularda sınır `foreign_top_famous`
             ("messi" İtalyanca'da 2839. kelime ama Messi aranır; "best" aranmaz).
    """
    foreign = foreign or {}

    def is_word(form: str, famous: bool) -> bool:
        if form in words:
            return True
        rank = foreign.get(form)
        return rank is not None and rank <= (foreign_top_famous if famous else foreign_top)

    def single_tokens(p):
        out = set()
        if p["surname"]:
            out.add(" ".join(tokenize_term(p["surname"])))
        for k in p["known_as"]:
            if len(tokenize_term(k)) == 1:
                out.add(" ".join(tokenize_term(k)))
        return out

    # Tek kelimelik isimlerin havuzdaki kullanım sayısı (benzersizlik için).
    # Ön adlar da sayılır: "Yusuf" bir oyuncunun soyadı olsa bile başkalarının
    # adı olduğu için tek başına aranmaz.
    counts = Counter()
    holders: dict[str, list[int]] = defaultdict(list)
    for p in players:
        tokens = single_tokens(p) | p["_mononyms"]
        for name in [p["full_name"], *p["known_as"]]:
            toks = tokenize_term(name)
            if len(toks) >= 2:
                tokens.add(toks[0])
        for t in tokens:
            counts[t] += 1
            holders[t].append(p["sitelinks"] or 0)

    def dominant(t: str, p: dict) -> bool:
        """Aynı ismi taşıyanlar arasında açık ara en ünlü olan bu oyuncu mu?
        (Messi vs. Mbida Messi, Maradona vs. Hugo Maradona)"""
        mine = p["sitelinks"] or 0
        others = sorted(holders[t], reverse=True)
        others.remove(mine)
        return mine >= dominance_min_sitelinks and mine >= dominance_ratio * (others[0] if others else 0)

    def term_forms(name: str, turkish: bool) -> list[str]:
        forms = [" ".join(tokenize_term(name))]
        if not turkish:
            ph = turkish_phonetic(name)
            ph = " ".join(re.findall(r"[a-z0-9]+", ph))
            if ph and ph not in forms:
                forms.append(ph)
        return forms

    for p in players:
        tr = p["turkish"]
        search, ambiguous, variants = [], [], []

        def add(lst, name):
            for f in term_forms(name, tr):
                if f and f not in search and f not in lst:
                    lst.append(f)

        # 1) Tam ad ve çok kelimeli takma adlar: her zaman
        if len(tokenize_term(p["full_name"])) >= 2:
            add(search, p["full_name"])
        for k in p["known_as"]:
            if len(tokenize_term(k)) >= 2:
                add(search, k)

        # 2) Tek kelimelik isimler
        surname_norm = " ".join(tokenize_term(p["surname"])) if p["surname"] else None
        singles = [k for k in [p["full_name"], *p["known_as"]] if len(tokenize_term(k)) == 1]
        if p["surname"] and p["surname"] not in singles:
            singles.append(p["surname"])
        famous = (p["sitelinks"] or 0) >= famous_sitelinks
        for name in singles:
            t = " ".join(tokenize_term(name))
            is_mononym = t in p["_mononyms"] and t != surname_norm
            if is_mononym:
                ok = not is_word(t, famous) and len(t) >= 3           # Ronaldinho, Kaká
            else:
                ok = (not is_word(t, famous) and len(t) >= min_surname_len
                      and (counts[t] == 1 or dominant(t, p)))
            # Türkçe okunuş varyantı ayrıca kontrol edilir: Bounou -> "bunu",
            # Vardy -> "vardi" kelime olduğu için yalnızca orijinal yazım aranır.
            for j, f in enumerate(term_forms(name, tr)):
                # Kısa isimlerin okunuş varyantı kelimeye çok benziyor (Isco -> "isko" -> işkolik)
                phonetic_ok = j == 0 or len(f) >= 6
                target = search if ok and phonetic_ok and not is_word(f, famous) else ambiguous
                if f and f not in search and f not in target:
                    target.append(f)

        # 3) Elle zorunlu kılınan takma adlar (Tanju, Rüştü, Alex)
        for name in p.get("_forced", []):
            add(search, name)

        for name in [p["full_name"], *p["known_as"], *([p["surname"]] if p["surname"] else [])]:
            for v in (name, normalize(name).replace("'", ""), *([] if tr else [turkish_phonetic(name)])):
                if v and v not in variants:
                    variants.append(v)

        p["search_terms"] = search
        p["ambiguous_terms"] = [a for a in ambiguous if a not in search]
        p["variants"] = variants
        p["ambiguous"] = bool(p["ambiguous_terms"])
        del p["_mononyms"]
        p.pop("_forced", None)


def apply_manual_aliases(players: list[dict]) -> None:
    """data/manual_aliases.csv: lakap ekle (her zaman aranır) / hatalı takma adı sil."""
    if not MANUAL_ALIASES.exists():
        return
    by_id = {p["wikidata_id"]: p for p in players}
    by_name = defaultdict(list)
    for p in players:
        by_name[normalize(p["full_name"])].append(p)
    with open(MANUAL_ALIASES, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            key = row["player"].strip()
            targets = [by_id[key]] if key in by_id else by_name.get(normalize(key), [])
            if not targets:
                print(f"   manual_aliases: '{key}' havuzda bulunamadı", file=sys.stderr)
                continue
            # Aynı isimde birden çok oyuncu varsa en ünlüsü
            p = max(targets, key=lambda x: x["sitelinks"] or 0)
            add = [a.strip() for a in row["add"].split("|") if a.strip()]
            remove = {normalize(r.strip()) for r in row["remove"].split("|") if r.strip()}
            p["known_as"] = [k for k in p["known_as"] if normalize(k) not in remove]
            for a in add:
                if a not in p["known_as"]:
                    p["known_as"].append(a)
            p["_forced"] = add


def load_manual() -> list[dict]:
    """1970 öncesi efsaneler vb. elle eklenen oyuncular."""
    if not MANUAL.exists():
        return []
    out = []
    with open(MANUAL, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            labels = {"tr": row["full_name"]}
            known = [k.strip() for k in row["known_as"].split("|") if k.strip()]
            mononyms = {" ".join(tokenize_term(k)) for k in known if len(tokenize_term(k)) == 1
                        and row.get("mononym") == "evet"}
            out.append({
                "wikidata_id": row["wikidata_id"] or "manual:" + normalize(row["full_name"]).replace(" ", "_"),
                "full_name": row["full_name"],
                "known_as": known,
                "surname": row["surname"] or None,
                "leagues": [l for l in row["leagues"].split("|") if l],
                "sitelinks": None,
                "turkish": row["turkish"] == "evet",
                "_mononyms": mononyms,
                "_labels": labels,
            })
    return out


# --------------------------------------------------------------------------- #

def cached(name: str, fn):
    """Wikidata sonuçlarını data/cache/ altında saklar; --refresh ile yenilenir."""
    path = CACHE / f"{name}.json"
    if path.exists() and "--refresh" not in sys.argv:
        return json.loads(path.read_text(encoding="utf-8"))
    data = fn()
    CACHE.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return data


def world_top(n: int, min_sitelinks: int, min_clubs: int) -> list[dict]:
    """Tüm zamanların en bilinen futbolcuları (sitelink sayısına göre).
    En az `min_clubs` kulüp kaydı şartı, futbol oynamış ama asıl ünü başka
    alanda olanları (Camus, Niels Bohr, Sean Connery) eler."""
    rows = sparql(f"""
        SELECT ?p ?sl WHERE {{
          ?p wdt:P106 wd:Q937857 ; wikibase:sitelinks ?sl . FILTER(?sl >= {min_sitelinks})
          ?p wdt:P21 wd:Q6581097 ; p:P54 ?st .
        }} GROUP BY ?p ?sl HAVING (COUNT(?st) >= {min_clubs})
        ORDER BY DESC(?sl) LIMIT {n}""")
    return [{"p": qid(r["p"]), "sl": int(r["sl"])} for r in rows]


def tier_of(rank: int | None) -> str:
    if rank is None:
        return "SL"            # yalnızca Süper Lig listesinden gelenler
    return "S" if rank <= 100 else "A" if rank <= 300 else "B" if rank <= 600 else "C"


def main() -> None:
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    default_th = cfg["sitelink_threshold"]
    wcfg, scfg = cfg["world_top"], cfg["super_lig_top"]

    # 1) Lig üyelikleri (yalnızca "leagues" alanı ve Süper Lig listesi için)
    player_leagues: dict[str, set[str]] = defaultdict(set)
    sitelinks: dict[str, int] = {}
    for key, lg in cfg["leagues"].items():
        th = lg.get("sitelink_threshold", default_th)

        def fetch():
            clubs = league_clubs(lg["qid"]) | set((cfg.get("extra_clubs") or {}).get(key, []))
            print(f"[{lg['name']}] {len(clubs)} kulüp, sitelink eşiği {th}")
            rows = []
            for part in chunks(sorted(clubs), cfg["clubs_per_query"]):
                rows += club_players(part, th)
                time.sleep(0.5)
            return rows

        for row in cached(f"league_{key}_{th}", fetch):
            pid = qid(row["p"])
            player_leagues[pid].add(key)
            sitelinks[pid] = int(row["sl"])

    # 2) Dünya top N (tüm dönemler, tüm ligler)
    world = cached(f"world_top_{wcfg['n']}",
                   lambda: world_top(wcfg["n"], wcfg["min_sitelinks"], wcfg["min_clubs"]))
    world_rank = {r["p"]: i for i, r in enumerate(world, 1)}
    for r in world:
        sitelinks[r["p"]] = r["sl"]

    # 3) Süper Lig'in en bilinen M oyuncusu (tüm dönemler, kadınlar hariç)
    super_lig = [pid for pid, lgs in player_leagues.items() if "super_lig" in lgs]
    females = set(cached("female_ids_super_lig", lambda: [
        f for part in chunks(sorted(super_lig), 1000) for f in female_ids(part)]))
    super_lig = sorted((p for p in super_lig if p not in females),
                       key=lambda p: -sitelinks[p])[:scfg["n"]]
    sl_rank = {p: i for i, p in enumerate(super_lig, 1)}

    # Futbol oynamış ama futbolcu olarak anılmayanlar elle çıkarılır (config: exclude_ids)
    ids = sorted((set(world_rank) | set(sl_rank)) - set(cfg.get("exclude_ids") or []))
    print(f"Dünya top {len(world_rank)} + Süper Lig top {len(sl_rank)} = {len(ids)} oyuncu; "
          "isimler çekiliyor...")

    info = defaultdict(lambda: {"labels": {}, "aliases": [], "surname": None, "turkish": False})
    details_path = CACHE / "details.json"
    details = {}
    if details_path.exists() and "--refresh" not in sys.argv:
        details = json.loads(details_path.read_text(encoding="utf-8"))
    missing = [i for i in ids if i not in details]
    for n, part in enumerate(chunks(missing, cfg["players_per_query"]), 1):
        rows = player_details(part, cfg["label_languages"], cfg["alias_languages"])
        for i in part:
            details[i] = []
        for row in rows:
            details[qid(row["p"])].append(row)
        time.sleep(0.3)
    if missing:
        details_path.write_text(json.dumps(details, ensure_ascii=False), encoding="utf-8")

    for pid in ids:
        for row in details[pid]:
            d = info[pid]
            if row["kind"] == "label":
                d["labels"].setdefault(row.get("name@lang", ""), row["name"])
            elif row["kind"] == "alias":
                if row["name"] not in d["aliases"]:
                    d["aliases"].append(row["name"])
            elif row["kind"] == "surname":
                d["surname"] = d["surname"] or row["name"]
            elif row["kind"] == "citizen":
                d["turkish"] = True

    players = []
    for pid in ids:
        rec = build_record(pid, info[pid], player_leagues.get(pid, set()), sitelinks[pid])
        if rec:
            rec["world_rank"] = world_rank.get(pid)
            rec["super_lig_rank"] = sl_rank.get(pid)
            rec["tier"] = tier_of(rec["world_rank"])
            players.append(rec)

    # Elle eklenenler: aynı isimde ÜNLÜ biri zaten varsa atla
    # (aynı adlı az bilinen biri yüzünden gerçek Pelé'nin atlanmaması için).
    existing = {normalize(p["full_name"]) for p in players if (p["sitelinks"] or 0) >= 40}
    for m in load_manual():
        if normalize(m["full_name"]) not in existing:
            m.pop("_labels")
            m.update(world_rank=None, super_lig_rank=None, tier="M")
            players.append(m)

    apply_manual_aliases(players)
    wf = cfg["word_filter"]
    tr_freq = load_frequency("tr", wf["turkish_top"])
    words = load_wordlist(cfg["turkish_wordlist_url"]) | set(tr_freq)
    foreign: dict[str, int] = {}
    for lang in wf["foreign_languages"]:
        for w, r in load_frequency(lang, wf["foreign_top"]).items():
            foreign[w] = min(r, foreign.get(w, r))
    blocked = {" ".join(tokenize_term(t)) for t in wf.get("blocked_terms", [])}
    words |= blocked
    apply_rules(players, words, cfg["min_surname_length"],
                cfg["dominance_ratio"], cfg["dominance_min_sitelinks"],
                foreign, wf["foreign_top"], wf["foreign_top_famous"], wf["famous_sitelinks"])
    # Eşleştiricinin ek soymayacağı yaygın Türkçe kelimeler ("melodi" != Melo + di)
    COMMON_WORDS.write_text("\n".join(sorted(load_frequency("tr", 50000))) + "\n",
                            encoding="utf-8")
    players.sort(key=lambda p: (-(p["sitelinks"] or 0), p["full_name"]))
    OUT.write_text(json.dumps(players, ensure_ascii=False, indent=1), encoding="utf-8")
    report(players, cfg)


def report(players: list[dict], cfg: dict) -> None:
    print(f"\n=== {OUT.relative_to(ROOT)} ===")
    print(f"Toplam oyuncu: {len(players)}")
    print("Tier dağılımı:", dict(sorted(Counter(p["tier"] for p in players).items())))
    print(f"Süper Lig top listesinden: {sum(1 for p in players if p.get('super_lig_rank'))}")
    dist = Counter(l for p in players for l in p["leagues"])
    print("Lig dağılımı (bir oyuncu birden çok ligde sayılabilir):")
    for key, lg in cfg["leagues"].items():
        print(f"   {lg['name']:<32} {dist.get(key, 0)}")
    print(f"Ambiguous (soyadı tek başına aranmayan): {sum(p['ambiguous'] for p in players)}")
    print("\nRastgele 30 örnek:")
    for p in random.Random(42).sample(players, min(30, len(players))):
        print(f"   [{p['tier']:<2}] {p['full_name']:<30} sl={p['sitelinks']!s:<4} "
              f"ara={p['search_terms'][:4]} belirsiz={p['ambiguous_terms'][:3]}")


if __name__ == "__main__":
    main()
