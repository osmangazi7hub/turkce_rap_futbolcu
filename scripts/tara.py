"""Türkçe rap şarkı sözlerinde futbolcu isimlerini tarar.

Akış:
  1. data/sanatcilar.txt içindeki her sanatçının şarkı listesi Deezer API'den çekilir.
  2. Her şarkının sözü LRCLIB'den (anahtar gerektirmez) alınır; bulunamazsa ve
     GENIUS_TOKEN tanımlıysa Genius'a bakılır.
  3. Sözler data/futbolcular.csv havuzundaki arama terimleriyle eşleştirilir.

Sözler cache/sozler/ altında önbelleğe alınır (depoya eklenmez).
Sonuçlar: results/eslesmeler.csv ve results/ozet.md
"""

import csv
import json
import os
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
HAVUZ = KOK / "data" / "futbolcular.csv"
SANATCILAR = KOK / "data" / "sanatcilar.txt"
CACHE = KOK / "cache" / "sozler"
SONUC = KOK / "results"
UA = "turkce-rap-futbolcu/1.0 (https://github.com/osmangazi7hub/turkce_rap_futbolcu)"

# Eşleştirme kuralı: sözlerdeki Türkçe harfler korunur, böylece "şaka" ile
# "Saka", "yaşın" ile "Yashin" karışmaz. Terimdeki her harf ise hem kendisiyle
# hem de klavyede yerine yazılabilen karşılığıyla eşleşir ("Şükür" -> "sukur"
# da bulunur, "Muller" -> "Müller" de). Tek istisna: terimdeki düz "s" harfi
# "ş" ile eşleşmez.
HARF_SINIFI = {
    "ş": "[şs]", "ç": "[çc]", "c": "[cç]", "ğ": "[ğg]", "g": "[gğ]",
    "ı": "[ıi]", "i": "[iı]", "ö": "[öo]", "o": "[oö]", "ü": "[üu]", "u": "[uü]",
}
HARF = "a-zçğıöşü0-9"

# İsimden sonra gelebilecek Türkçe ekler. Serbest "[a-z]*" yerine liste
# kullanıyoruz ki "kane" -> "kanepe" gibi yanlış eşleşmeler olmasın.
I, E = "[iıuü]", "[ea]"
EKLER = [
    f"y?{I}", f"y?{E}", f"n?{I}n", f"n?[dt]{E}n?", f"y?l{E}",
    f"l{E}r", f"l{E}r{I}n?", f"l{E}r{E}", f"l{E}rd{E}n?", f"l{E}r{I}n{I}?n?",
    f"[cç]{I}", f"[cç]{I}l{E}r", f"s{I}", f"s{I}n{I}?n?", f"s{I}n{E}",
    f"y?{I}m", "m", f"y?{I}z", f"s{I}n", f"[dt]{I}r", f"l{I}k", f"s{I}z",
    f"[dt]{E}k{I}", f"y?d{I}", f"v{E}r{I}",
]
EK_DESENI = "(?:" + "|".join(EKLER) + ")?"


def normalize(metin: str) -> str:
    """Türkçe'ye duyarlı küçük harf; Türkçe dışı aksanlar ve apostroflar atılır."""
    metin = metin.replace("I", "ı").replace("İ", "i").lower()
    korunan = set("çğıöşü")
    sonuc = []
    for c in metin:
        if c in korunan:
            sonuc.append(c)
        else:
            sonuc.append("".join(x for x in unicodedata.normalize("NFKD", c)
                                 if not unicodedata.combining(x)))
    return re.sub(r"['’`´]", "", "".join(sonuc))


def terim_deseni(terim: str) -> re.Pattern:
    parcalar = []
    for kelime in re.split(r"[\s\-]+", normalize(terim)):
        if kelime:
            parcalar.append("".join(HARF_SINIFI.get(c, re.escape(c)) for c in kelime))
    govde = r"[\s\-]+".join(parcalar)
    return re.compile(rf"(?<![{HARF}]){govde}{EK_DESENI}(?![{HARF}])")


def havuzu_yukle():
    oyuncular = []
    with open(HAVUZ, encoding="utf-8") as f:
        for satir in csv.DictReader(f):
            terimler = [t.strip() for t in satir["arama_terimleri"].split("|") if t.strip()]
            oyuncular.append({**satir, "desenler": [(t, terim_deseni(t)) for t in terimler]})
    return oyuncular


def http_json(url, basliklar=None, deneme=4):
    for i in range(deneme):
        try:
            istek = urllib.request.Request(url, headers={"User-Agent": UA, **(basliklar or {})})
            with urllib.request.urlopen(istek, timeout=30) as yanit:
                return json.loads(yanit.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if i == deneme - 1:
                raise
        except Exception:
            if i == deneme - 1:
                raise
        time.sleep(2 ** i)


def deezer_sarkilar(sanatci):
    """Sanatçının tüm albüm/single şarkılarını (tekrarsız) döndürür."""
    q = urllib.parse.quote(sanatci)
    sonuc = http_json(f"https://api.deezer.com/search/artist?q={q}")
    adaylar = (sonuc or {}).get("data", [])
    if not adaylar:
        return None, []
    hedef = normalize(sanatci)
    artist = next((a for a in adaylar if normalize(a["name"]) == hedef), adaylar[0])
    sarkilar, gorulen = [], set()
    url = f"https://api.deezer.com/artist/{artist['id']}/albums?limit=100"
    while url:
        sayfa = http_json(url) or {}
        for album in sayfa.get("data", []):
            parcalar = http_json(f"https://api.deezer.com/album/{album['id']}/tracks?limit=200") or {}
            for p in parcalar.get("data", []):
                anahtar = normalize(re.sub(r"\s*[\(\[].*?[\)\]]", "", p["title"]))
                if anahtar in gorulen:
                    continue
                gorulen.add(anahtar)
                sarkilar.append({"baslik": p["title"], "album": album["title"], "sure": p.get("duration")})
            time.sleep(0.1)
        url = sayfa.get("next")
    return artist["name"], sarkilar


def lrclib_soz(sanatci, baslik, sure=None):
    params = {"artist_name": sanatci, "track_name": baslik}
    if sure:
        params["duration"] = sure
    veri = http_json("https://lrclib.net/api/get?" + urllib.parse.urlencode(params))
    if not veri and sure:
        veri = http_json("https://lrclib.net/api/get?" + urllib.parse.urlencode(
            {"artist_name": sanatci, "track_name": baslik}))
    if not veri:
        sonuc = http_json("https://lrclib.net/api/search?" + urllib.parse.urlencode(
            {"artist_name": sanatci, "track_name": baslik})) or []
        veri = next((s for s in sonuc if s.get("plainLyrics")), None)
    return (veri or {}).get("plainLyrics")


def genius_soz(sanatci, baslik):
    token = os.environ.get("GENIUS_TOKEN")
    if not token:
        return None
    q = urllib.parse.quote(f"{sanatci} {baslik}")
    sonuc = http_json(f"https://api.genius.com/search?q={q}", {"Authorization": f"Bearer {token}"})
    for hit in (sonuc or {}).get("response", {}).get("hits", []):
        s = hit["result"]
        if normalize(sanatci) not in normalize(s["primary_artist"]["name"]):
            continue
        try:
            istek = urllib.request.Request(s["url"], headers={"User-Agent": "Mozilla/5.0"})
            html = urllib.request.urlopen(istek, timeout=30).read().decode("utf-8")
        except Exception:
            return None
        bloklar = re.findall(r'<div[^>]*data-lyrics-container="true"[^>]*>(.*?)</div>', html, re.S)
        metin = "\n".join(bloklar)
        metin = re.sub(r"<br\s*/?>", "\n", metin)
        metin = re.sub(r"<[^>]+>", "", metin)
        import html as h
        return h.unescape(metin).strip() or None
    return None


def dosya_adi(metin):
    ascii_ = unicodedata.normalize("NFKD", normalize(metin).replace("ı", "i"))
    return re.sub(r"[^a-z0-9]+", "_", ascii_.encode("ascii", "ignore").decode()).strip("_")


def soz_getir(sanatci, sarki):
    dosya = CACHE / dosya_adi(sanatci) / (dosya_adi(sarki["baslik"]) + ".json")
    if dosya.exists():
        return json.loads(dosya.read_text(encoding="utf-8"))
    try:
        soz, kaynak = lrclib_soz(sanatci, sarki["baslik"], sarki.get("sure")), "lrclib"
        if not soz:
            soz, kaynak = genius_soz(sanatci, sarki["baslik"]), "genius"
    except Exception as e:
        # Geçici hata: önbelleğe yazma ki sonraki çalıştırmada tekrar denensin.
        print(f"   hata ({sarki['baslik']}): {e}")
        return {"soz": None, "kaynak": None}
    kayit = {"soz": soz, "kaynak": kaynak if soz else None}
    dosya.parent.mkdir(parents=True, exist_ok=True)
    dosya.write_text(json.dumps(kayit, ensure_ascii=False), encoding="utf-8")
    return kayit


def tara(soz, oyuncular):
    bulunan = []
    for satir in soz.splitlines():
        n = normalize(satir)
        for o in oyuncular:
            for terim, desen in o["desenler"]:
                if desen.search(n):
                    bulunan.append((o, terim, satir.strip()))
                    break
    return bulunan


def main():
    oyuncular = havuzu_yukle()
    sanatcilar = [s.strip() for s in SANATCILAR.read_text(encoding="utf-8").splitlines()
                  if s.strip() and not s.strip().startswith("#")]
    if not sanatcilar:
        sys.exit("data/sanatcilar.txt boş — önce sanatçı listesini doldurun.")

    SONUC.mkdir(exist_ok=True)
    eslesmeler, istatistik = [], []
    for sanatci in sanatcilar:
        ad, sarkilar = deezer_sarkilar(sanatci)
        if not ad:
            print(f"!! {sanatci}: Deezer'da bulunamadı")
            istatistik.append((sanatci, 0, 0))
            continue
        sozlu = 0
        for i, sarki in enumerate(sarkilar, 1):
            kayit = soz_getir(ad, sarki)
            if not kayit["soz"]:
                continue
            sozlu += 1
            gorulen = set()
            for o, terim, satir in tara(kayit["soz"], oyuncular):
                if (o["isim"], satir.rstrip(",.!? ")) in gorulen:
                    continue
                gorulen.add((o["isim"], satir.rstrip(",.!? ")))
                eslesmeler.append({
                    "sanatci": ad, "sarki": sarki["baslik"], "album": sarki["album"],
                    "futbolcu": o["isim"], "eslesen_terim": terim, "kategori": o["kategori"],
                    "belirsiz": o["belirsiz"], "satir": satir, "kaynak": kayit["kaynak"],
                })
        print(f"{ad}: {len(sarkilar)} şarkı, {sozlu} tanesinin sözü bulundu")
        istatistik.append((ad, len(sarkilar), sozlu))

    alanlar = ["sanatci", "sarki", "album", "futbolcu", "eslesen_terim", "kategori", "belirsiz", "satir", "kaynak"]
    with open(SONUC / "eslesmeler.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=alanlar)
        w.writeheader()
        w.writerows(eslesmeler)

    ozet_yaz(eslesmeler, istatistik)
    print(f"\nToplam {len(eslesmeler)} eşleşme -> results/")


def ozet_yaz(eslesmeler, istatistik):
    kesin = [e for e in eslesmeler if e["belirsiz"] != "evet"]
    sayim = defaultdict(set)
    for e in kesin:
        sayim[e["futbolcu"]].add((e["sanatci"], e["sarki"]))
    satirlar = ["# Türkçe Rapte Futbolcular — Sonuçlar", "",
                "## Taranan sanatçılar", "", "| Sanatçı | Şarkı | Sözü bulunan |", "|---|---|---|"]
    satirlar += [f"| {a} | {t} | {s} |" for a, t, s in istatistik]
    satirlar += ["", "## En çok geçen futbolcular (belirsiz terimler hariç)", "",
                 "| Futbolcu | Şarkı sayısı | Sanatçılar |", "|---|---|---|"]
    for isim, sarkilar in sorted(sayim.items(), key=lambda x: -len(x[1])):
        sanatcilar = ", ".join(sorted({s for s, _ in sarkilar}))
        satirlar.append(f"| {isim} | {len(sarkilar)} | {sanatcilar} |")
    belirsiz = [e for e in eslesmeler if e["belirsiz"] == "evet"]
    if belirsiz:
        satirlar += ["", f"## Elle kontrol edilmesi gerekenler ({len(belirsiz)})", "",
                     "Bu terimler gündelik kelimelerle karışabilir (ör. *Alex*, *Pepe*, *Fred*).", "",
                     "| Futbolcu | Sanatçı – Şarkı | Satır |", "|---|---|---|"]
        for e in belirsiz:
            satirlar.append(f"| {e['futbolcu']} | {e['sanatci']} – {e['sarki']} | {e['satir'].replace('|', '/')} |")
    (SONUC / "ozet.md").write_text("\n".join(satirlar) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
