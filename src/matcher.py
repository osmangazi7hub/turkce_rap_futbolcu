"""Şarkı sözlerinde futbolcu isimlerini bulan eşleştirici.

Normalizasyon: Türkçe'ye duyarlı küçük harf (I→ı, İ→i), ardından
ı/i, ş/s, ç/c, ğ/g, ö/o, ü/u katlanır ve diğer aksanlar atılır.
Böylece "Dzeko", "Džeko", "DZEKO'NUN" hepsi "dzeko" olur.

Eşleştirme kelime sınırlıdır ve Türkçe ekleri tanır:
  - Kesme işaretli:   "Cancelo'yu", "Inzaghi'nin"  -> kesmeden önceki kısım
  - Kesmesiz:         "Neymarı", "Drogbalar"       -> bilinen ek listesiyle soyulur
Ek listesi serbest değil, böylece "kane" -> "kanepe" gibi yanlış eşleşme olmaz.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

TR_FOLD = str.maketrans({"ı": "i", "ş": "s", "ç": "c", "ğ": "g", "ö": "o", "ü": "u"})
APOSTROPHES = "'’`´ʼ‘"

# Normalize edilmiş (katlanmış) Türkçe ekler: hal, çoğul, iyelik, ek-fiil,
# ilgi, -ci, -lik, -siz, -ce vb. Ünlü uyumu katlamadan sonra i/u ve e/a'ya iner.
_I, _E = "[iu]", "[ea]"
SUFFIXES = [
    f"y?{_I}", f"y?{_E}", f"n?{_I}n", f"n?[dt]{_E}n?", f"y?l{_E}", f"y?k{_E}n",
    f"l{_E}r", f"l{_E}r{_I}n?", f"l{_E}r{_E}", f"l{_E}r[dt]{_E}n?", f"l{_E}r{_I}n{_I}?n?",
    f"l{_E}r{_I}n?{_E}", f"l{_E}rl{_E}", f"l{_E}r{_I}m{_I}z",
    f"c{_I}", f"c{_I}l{_E}r", f"c{_I}l{_I}k", f"s{_I}", f"s{_I}n{_I}?n?", f"s{_I}n{_E}",
    f"y?{_I}m", "m", f"y?{_I}m{_I}z", f"y?{_I}z", f"s{_I}n", f"[dt]{_I}r", f"l{_I}k",
    f"s{_I}z", f"y?d{_I}", f"y?d{_I}m", f"[dt]{_E}k{_I}", f"v{_E}r{_I}", f"c{_E}",
    f"g{_I}ll", f"g{_I}l", f"c{_E}s{_I}n{_E}",
]
SUFFIX_RE = re.compile("(?:" + "|".join(SUFFIXES) + ")")
MAX_SUFFIX_LEN = 7

TOKEN_RE = re.compile(r"[a-z0-9]+(?:'[a-z]*)?")


def normalize(text: str) -> str:
    """Türkçe normalizasyon. Kesme işaretleri tek tip "'" olarak korunur."""
    text = text.replace("I", "ı").replace("İ", "i").lower()
    text = text.translate(TR_FOLD)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    for a in APOSTROPHES:
        text = text.replace(a, "'")
    # ß, ø, æ, đ gibi ayrışmayan harfler
    return text.translate(str.maketrans({"ß": "ss", "ø": "o", "æ": "ae", "đ": "d", "ł": "l", "œ": "oe"}))


def tokenize_term(term: str) -> tuple[str, ...]:
    """Bir isim terimini normalize edilmiş kelimelere böler (kesme ve tire atılır)."""
    norm = normalize(term).replace("'", "")
    return tuple(re.findall(r"[a-z0-9]+", norm))


def _stems(token: str, common: frozenset[str] = frozenset()) -> set[str]:
    """Bir sözcüğün olası gövdeleri: kendisi + ek soyulmuş halleri.
    Yaygın bir Türkçe kelimeyse ("melodi", "polisi", "umarım") eke ayrılmaz."""
    if "'" in token:
        # Kesme işareti varsa ondan önceki kısım isimdir; sonrası ne olursa olsun ektir.
        return {token.split("'", 1)[0]}
    stems = {token}
    if token in common:
        return stems
    # En uzun "yaygın kelime" öneki: "betondan" -> "beton", "boykota" -> "boykot".
    # Gövde bundan kısa olamaz; yoksa "beto + ndan" gibi yanlış bölünür.
    floor = max((n for n in range(3, len(token)) if token[:n] in common), default=0)
    for k in range(1, min(MAX_SUFFIX_LEN, len(token) - 2) + 1):
        if len(token) - k >= floor and SUFFIX_RE.fullmatch(token[-k:]):
            stems.add(token[:-k])
    return stems


@dataclass(frozen=True)
class Match:
    wikidata_id: str
    name: str
    term: str          # eşleşen arama terimi (normalize)
    text: str          # satırda eşleşen kısım (normalize)
    ambiguous: bool
    start: int = 0     # satırdaki kelime aralığı [start, end)
    end: int = 0


class Matcher:
    def __init__(self, players: list[dict], include_ambiguous: bool = False,
                 common_words: set[str] | None = None):
        self.common = frozenset(common_words or ())
        # ilk kelime -> [(terim kelimeleri, oyuncu, belirsiz mi)]
        self.index: dict[str, list[tuple[tuple[str, ...], dict, bool]]] = {}
        for p in players:
            for term in p.get("search_terms", []):
                self._add(term, p, False)
            if include_ambiguous:
                for term in p.get("ambiguous_terms", []):
                    self._add(term, p, True)

    @classmethod
    def from_file(cls, path: str | Path = "data/players.json", **kw) -> "Matcher":
        path = Path(path)
        common = path.parent / "common_words_tr.txt"
        if "common_words" not in kw and common.exists():
            kw["common_words"] = set(common.read_text(encoding="utf-8").split())
        with open(path, encoding="utf-8") as f:
            return cls(json.load(f), **kw)

    def _add(self, term: str, player: dict, ambiguous: bool) -> None:
        toks = tokenize_term(term)
        if toks:
            self.index.setdefault(toks[0], []).append((toks, player, ambiguous))

    def find(self, line: str) -> list[Match]:
        tokens = TOKEN_RE.findall(normalize(line))
        plain = [t.split("'", 1)[0] if "'" in t else t for t in tokens]
        stems = [_stems(t, self.common) for t in tokens]
        found: dict[tuple[str, int, int], Match] = {}
        for i in range(len(tokens)):
            # Tek kelimelik terimlerde ek soyulabilir; çok kelimelilerde ilk kelime tam olmalı.
            for key in stems[i] | {plain[i]}:
                for toks, player, amb in self.index.get(key, ()):
                    n = len(toks)
                    if i + n > len(tokens):
                        continue
                    if n == 1:
                        ok = toks[0] in stems[i]
                    else:
                        ok = (toks[0] == plain[i]
                              and all(toks[j] == plain[i + j] for j in range(1, n - 1))
                              and toks[-1] in stems[i + n - 1])
                    if not ok:
                        continue
                    k = (player["wikidata_id"], i, i + n)
                    m = Match(player["wikidata_id"], player["full_name"], " ".join(toks),
                              " ".join(tokens[i:i + n]), amb, i, i + n)
                    # Aynı aralıkta hem kesin hem belirsiz terim eşleştiyse kesini tut
                    if k not in found or (found[k].ambiguous and not amb):
                        found[k] = m
        return _drop_contained(_prefer_exact(list(found.values())))


def _prefer_exact(matches: list[Match]) -> list[Match]:
    """Aynı kelime hem ekli hem eksiz okunuşla eşleştiyse eksizi tut:
    "Zidane" -> Zidane (Zidan + "-e" değil)."""
    exact = {(m.start, m.end) for m in matches if m.term.replace(" ", "") ==
             m.text.split("'", 1)[0].replace(" ", "")}
    return [m for m in matches if (m.start, m.end) not in exact
            or m.term.replace(" ", "") == m.text.split("'", 1)[0].replace(" ", "")]


def _drop_contained(matches: list[Match]) -> list[Match]:
    """Daha uzun bir eşleşmenin içinde kalanları at.

    "Cristiano Ronaldo" geçen satırda ayrıca Ronaldo Nazário'nun "Ronaldo"su,
    "Edin Dzeko"da ayrıca tek başına "Dzeko" raporlanmaz.
    """
    out = []
    for m in matches:
        if any(o.start <= m.start and m.end <= o.end and (o.end - o.start) > (m.end - m.start)
               for o in matches):
            continue
        out.append(m)
    return out
