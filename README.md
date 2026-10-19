# Türkçe Rapte Futbolcular

Türkçe rap şarkı sözlerinde geçen futbolcu isimlerini bulan proje.

## Nasıl çalışır?

1. **Futbolcu havuzu** – `data/futbolcular.csv`: dünyanın en bilinen futbolcuları + Süper Lig / Türk futbolu isimleri.
   - `arama_terimleri`: sözlerde aranacak yazımlar, `|` ile ayrılır (ör. `Hagi|Gheorghe Hagi`).
   - `kategori`: `dunya` / `turkiye`, `donem`: `efsane` / `guncel`.
   - `belirsiz=evet`: gündelik bir kelimeyle karışabilen isimler (Alex, Pepe, Fred, Kaka…). Bunlar sonuçta ayrı listelenir, elle kontrol edilir.
2. **Sanatçılar** – `data/sanatcilar.txt`: her satıra bir sanatçı.
3. **Tarama** – `scripts/tara.py`
   - Şarkı listesi: Deezer API (anahtar gerekmez)
   - Sözler: [LRCLIB](https://lrclib.net) (anahtar gerekmez); bulunamazsa ve `GENIUS_TOKEN` secret'ı tanımlıysa Genius.
   - Eşleştirme Türkçe eklere duyarlıdır (`Messi'yi`, `Hagi'nin`, `Drogbalar`) ve Türkçe harfleri ayırt eder (`şaka` ≠ `Saka`, `yaşın` ≠ `Yashin`), ama aksansız yazımı da yakalar (`Hakan Sukur`).
4. **Sonuçlar** – `results/eslesmeler.csv` (her eşleşen satır) ve `results/ozet.md` (özet tablo).

## GitHub üzerinden çalıştırma

**Actions → "Şarkı sözlerini tara" → Run workflow.** İsterseniz sanatçıları virgülle girebilirsiniz; boş bırakılırsa `data/sanatcilar.txt` kullanılır. Sonuçlar otomatik olarak `results/` klasörüne commit edilir.

Genius'u da kullanmak için: Settings → Secrets and variables → Actions → `GENIUS_TOKEN` (genius.com/api-clients üzerinden alınır).

> Not: Spotify'ın şarkı sözü veren herkese açık bir API'si yok, bu yüzden kullanılmıyor.

## Yerelde çalıştırma

```bash
python3 scripts/tara.py
```
