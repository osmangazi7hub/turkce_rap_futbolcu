# Türkçe Rapte Futbolcular

Türkçe rap şarkı sözlerinde geçen futbolcu isimlerini bulan Python projesi.

> Bu aşama: proje iskeleti + **futbolcu havuzu** + eşleştirici. Şarkı sözü çekme (Genius vb.) sonraki adım.

## Yapı

```
config.yaml            # ligler, sitelink eşiği, yıl sınırı vb.
src/build_players.py   # Wikidata SPARQL -> data/players.json
src/matcher.py         # Türkçe normalizasyon + ek duyarlı eşleştirme
data/players.json      # futbolcu havuzu (üretilen)
data/manual_players.csv# 1970 öncesi efsaneler gibi elle eklenenler
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

- **Kapsam:** 1970 ve sonrasında İngiltere (Premier League + 1992 öncesi First Division), İspanya, İtalya, Almanya, Fransa, Hollanda, Portekiz ve Türkiye üst liglerinde oynamış futbolcular.
  - Süper Lig: **hepsi**.
  - Diğer ligler: Wikipedia sitelink sayısı **≥ 15** olanlar (`config.yaml` → `sitelink_threshold`, lig bazında da değiştirilebilir).
  - Yıl: kulüp kaydının başlangıç/bitiş tarihi ≥ 1970; tarih yoksa doğum yılı ≥ 1950.
- Kulüpler: Wikidata'da lige bağlı (P118, geçmiş kayıtlar dahil) ve lig sezonlarına katılmış (P1923) kulüpler. Eksik kalan kulüp olursa `extra_clubs` ile eklenir.
- Sorgular lig ve kulüp gruplarına bölünür, 429/5xx/timeout'ta üstel beklemeyle tekrar denenir.

`data/players.json` kaydı:

| alan | açıklama |
|---|---|
| `wikidata_id` | Q-kodu (elle eklenenlerde `manual:...`) |
| `full_name` | Türkçe, yoksa İngilizce etiket |
| `known_as` | diğer dillerdeki etiketler + takma adlar (ör. "Ronaldinho", "Kral Hakan") |
| `surname` | Wikidata soyadı (P734), yoksa adın son kelimesi |
| `leagues`, `sitelinks`, `turkish` | ligler, sitelink sayısı, TC vatandaşı mı |
| `variants` | tüm yazımlar: orijinal, aksansız, Türkçe okunuş (Aboubakar → abubakar) |
| `search_terms` | kesin aranacak terimler |
| `ambiguous_terms`, `ambiguous` | tek başına aranmayan terimler |

### Eşleşme kuralları

1. Tam ad ve çok kelimeli takma adlar **her zaman** aranır.
2. Tek kelimelik lakap etiketler (Ronaldinho, Neymar) aranır — Türkçe kelime değilse.
3. **Tek başına soyad** yalnızca (a) havuzda tekse, (b) [Türkçe kelime listesinde](https://github.com/mertemin/turkish-word-list) yoksa, (c) en az 4 harfse aranır.
4. Diğerleri `ambiguous_terms`'e düşer (ör. *Kaká* → "kaka", *Suat Kaya* → "kaya", iki Inzaghi olduğu için "Inzaghi").
5. Yabancı isimlere Türkçe okunuş varyantı eklenir: Koulibaly → *kulibali*, Carrasco → *karasko*, Sneijder → *snayder*.

### Eşleştirici

```python
from src.matcher import Matcher
m = Matcher.from_file("data/players.json")
m.find("Cancelo'yu geçtim, Inzaghi'nin ofsaytı")
```

Normalizasyon ı/i, ş/s, ç/c, ğ/g, ö/o, ü/u katlar. Kesme işaretli (`Cancelo'yu`) ve kesmesiz (`Neymarlar`) ekler yakalanır. Ek listesi sınırlı olduğu için `kane` → `kanepe` gibi yanlış eşleşmeler olmaz.
