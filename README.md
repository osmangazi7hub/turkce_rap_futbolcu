# Türkçe Rapte Futbolcular

Türkçe rap şarkı sözlerinde geçen futbolcu isimlerini bulan Python projesi.

Adımlar:
1. `python -m src.build_players` → futbolcu havuzu (`data/players.json`)
2. `data/artists.txt` → taranacak rapçiler (Deezer ID'leriyle)
3. `python -m src.fetch_lyrics` → şarkı listesi Deezer'dan, sözler LRCLIB'den (`data/lyrics/`, git'e girmez; kapsama: `results/lyrics_coverage.csv`)
4. `python -m src.scan` → `results/matches.csv` (her eşleşen satır) ve `results/summary.md` (özet)

## Yapı

```
config.yaml            # ligler, sitelink eşiği, yıl sınırı vb.
src/build_players.py   # Wikidata SPARQL -> data/players.json
src/matcher.py         # Türkçe normalizasyon + ek duyarlı eşleştirme
src/fetch_lyrics.py    # Deezer + LRCLIB -> data/lyrics/
src/scan.py            # sözlerde futbolcu tarama -> results/
data/artists.txt       # rapçi listesi
data/common_words_tr.txt # eke ayrılmayacak yaygın Türkçe kelimeler
data/players.json      # futbolcu havuzu (üretilen)
data/manual_players.csv# 1970 öncesi efsaneler gibi elle eklenenler (Lefter, Metin Oktay, Pelé…)
data/manual_aliases.csv# elle lakap ekle/sil (Tanju, Rüştü, Alex…)
data/cache/            # Wikidata yanıtları, kelime listesi (git'e girmez)
data/lyrics/           # şarkı sözleri (git'e girmez)
results/               # tarama sonuçları
tests/                 # pytest
```

## Kurulum

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m src.build_players          # önbellek varsa onu kullanır
python -m src.build_players --refresh  # Wikidata'dan baştan çek
pytest
```

## Futbolcu havuzu

- **Kapsam:** dünyanın tüm zamanlardaki **en bilinen 1000 futbolcusu** (tüm ligler, tüm dönemler) + **Süper Lig'de oynamışların en bilinen 500'ü**.
  - Bilinirlik = Wikidata sitelink sayısı (kaç dilde Wikipedia sayfası var). Sayılar `config.yaml`'dan değişir.
  - Dünya listesinde en az 3 kulüp kaydı şartı var; futbolu yan uğraş olan ünlüler (Camus, Niels Bohr) elenir.
  - Tier: **S** (dünya 1–100), **A** (101–300), **B** (301–600), **C** (601–1000), **SL** (yalnızca Süper Lig listesinden), **M** (elle eklenen).
- Süper Lig kulüpleri: Wikidata'da lige bağlı (P118, geçmiş kayıtlar dahil) ve lig sezonlarına katılmış (P1923) kulüpler.
- Sorgular bölünür, 429/5xx/timeout'ta üstel beklemeyle tekrar denenir; yanıtlar `data/cache/` altında saklanır.

`data/players.json` kaydı:

| alan | açıklama |
|---|---|
| `wikidata_id` | Q-kodu (elle eklenenlerde `manual:...`) |
| `full_name` | Türkçe, yoksa İngilizce etiket |
| `known_as` | diğer dillerdeki etiketler + takma adlar (ör. "Ronaldinho", "Kral Hakan") |
| `surname` | Wikidata soyadı (P734), yoksa adın son kelimesi |
| `leagues`, `sitelinks`, `turkish` | ligler, sitelink sayısı, TC vatandaşı mı |
| `tier`, `world_rank`, `super_lig_rank` | bilinirlik kademesi ve sıraları |
| `variants` | tüm yazımlar: orijinal, aksansız, Türkçe okunuş (Aboubakar → abubakar) |
| `search_terms` | kesin aranacak terimler |
| `ambiguous_terms`, `ambiguous` | tek başına aranmayan terimler |

### Eşleşme kuralları

1. Tam ad ve çok kelimeli takma adlar **her zaman** aranır.
2. Tek kelimelik lakap etiketler (Ronaldinho, Neymar) aranır — Türkçe kelime değilse.
3. **Tek başına soyad** yalnızca (a) havuzda tekse, (b) [Türkçe kelime listesinde](https://github.com/mertemin/turkish-word-list) yoksa, (c) en az 4 harfse aranır.
   - "Tek" sayılırken başka oyuncuların ön adları da hesaba katılır ("Yusuf" soyad olsa bile aranmaz).
   - **Baskınlık:** aynı ismi taşıyanlardan biri açık ara ünlüyse (sitelink ≥ 1.8 × ikinci, ≥ 30) isim onun için aranır: Messi (226) vs Mbida Messi (5), Maradona vs Hugo Maradona, Hagi vs Ianis Hagi. Eşit ünlülerde (Filippo/Simone Inzaghi) aranmaz.
4. Diğerleri `ambiguous_terms`'e düşer (ör. *Kaká* → "kaka", *Suat Kaya* → "kaya", iki Inzaghi olduğu için "Inzaghi").
5. `data/manual_aliases.csv` ile eklenen lakaplar kurallardan bağımsız her zaman aranır; hatalı Wikidata takma adları silinebilir.
6. Kadın futbolcular çıkarılır (bazı lig öğeleri kadın liglerini de kapsıyor).
7. **Kelime filtresi** (`config.yaml` → `word_filter`): OpenSubtitles sıklık listeleriyle kelimeye benzeyen isimler tek başına aranmaz — Türkçe en sık 50 bin (vardı, durmaz, bunu), en/de/nl/es/it/fr en sık 15 bin (best, young, king; çok ünlülerde 2 bin, böylece "messi" aranır), az bilinenlerde Türkçe altyazılarda ≥ 40 geçenler (inler, akita). Yaygın Türkçe kelimeler eke ayrılmaz ("melodi" ≠ Melo + di, "betondan" ≠ Beto + ndan). Elle engellenenler: `blocked_terms`.
8. Edatlı adlar ("de Souza", "da Silva") soyad gibi değerlendirilir; birden çok kişide varsa aranmaz.
9. Yabancı isimlere Türkçe okunuş varyantı eklenir: Koulibaly → *kulibali*, Carrasco → *karasko*, Sneijder → *snayder* (tek kelimede yalnızca 6+ harfli olanlar).

### Eşleştirici

```python
from src.matcher import Matcher
m = Matcher.from_file("data/players.json")
m.find("Cancelo'yu geçtim, Inzaghi'nin ofsaytı")
```

Normalizasyon ı/i, ş/s, ç/c, ğ/g, ö/o, ü/u katlar. Kesme işaretli (`Cancelo'yu`) ve kesmesiz (`Neymarlar`) ekler yakalanır. Ek listesi sınırlı olduğu için `kane` → `kanepe` gibi yanlış eşleşmeler olmaz.
