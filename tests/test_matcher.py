import pytest

from src.build_players import apply_rules, turkish_phonetic
from src.matcher import Matcher, normalize


def player(qid, full_name, known_as=(), surname=None, turkish=False, mononyms=()):
    return {
        "wikidata_id": qid, "full_name": full_name, "known_as": list(known_as),
        "surname": surname, "leagues": [], "sitelinks": 50, "turkish": turkish,
        "_mononyms": set(mononyms),
    }


WORDS = {"kaka", "kaya", "demir", "son", "saka", "pepe", "yilmaz", "turan", "kane", "sukur"}


@pytest.fixture(scope="module")
def pool():
    players = [
        player("Q1", "Diego Maradona", surname="Maradona"),
        player("Q2", "Vincent Aboubakar", surname="Aboubakar"),
        player("Q3", "Kalidou Koulibaly", surname="Koulibaly"),
        player("Q4", "Yannick Carrasco", surname="Carrasco"),
        player("Q5", "Adam Lallana", surname="Lallana"),
        player("Q6", "Cristiano Ronaldo", surname="Ronaldo"),
        player("Q7", "Ronaldo", known_as=["Ronaldo Nazário"], mononyms={"ronaldo"}),
        player("Q8", "Filippo Inzaghi", surname="Inzaghi"),
        player("Q9", "Simone Inzaghi", surname="Inzaghi"),
        player("Q10", "Neymar", mononyms={"neymar"}),
        player("Q11", "Edin Džeko", surname="Džeko"),
        player("Q12", "João Cancelo", surname="Cancelo"),
        player("Q13", "Hakan Şükür", surname="Şükür", turkish=True),
        player("Q14", "Kaká", mononyms={"kaka"}),
        player("Q15", "Suat Kaya", surname="Kaya", turkish=True),
        player("Q16", "Harry Kane", surname="Kane"),
        player("Q17", "Arda Turan", surname="Turan", turkish=True),
        player("Q18", "Ronaldinho", mononyms={"ronaldinho"}),
    ]
    apply_rules(players, WORDS, min_surname_len=4)
    return players


@pytest.fixture(scope="module")
def m(pool):
    return Matcher(pool)


def names(matcher, line):
    return sorted(x.name for x in matcher.find(line))


# --- normalizasyon -------------------------------------------------------- #

@pytest.mark.parametrize("raw,expected", [
    ("İNZAGHİ", "inzaghi"),
    ("DZEKO'NUN", "dzeko'nun"),
    ("Džeko", "dzeko"),
    ("Şükür ılık çöğü", "sukur ilik cogu"),
    ("Cancelo’yu", "cancelo'yu"),
])
def test_normalize(raw, expected):
    assert normalize(raw) == expected


def test_phonetic():
    assert turkish_phonetic("Aboubakar") == "abubakar"
    assert turkish_phonetic("Koulibaly") == "kulibali"
    assert turkish_phonetic("Carrasco") == "karasko"
    assert turkish_phonetic("Sneijder") == "snayder"


# --- kesme işaretli ve kesmesiz ekler ------------------------------------- #

@pytest.mark.parametrize("line,expected", [
    ("Cancelo'yu geçtim sağ kanattan", ["João Cancelo"]),
    ("Inzaghi'nin ofsayt çizgisi", []),                 # iki Inzaghi var -> soyad tek değil
    ("Filippo Inzaghi'nin ofsayt çizgisi", ["Filippo Inzaghi"]),
    ("Maradona gibi pas ver", ["Diego Maradona"]),
    ("Maradonayı izledim", ["Diego Maradona"]),
    ("Neymar'a selam söyle", ["Neymar"]),
    ("Neymarlar gibi düşüyolar", ["Neymar"]),
    ("Edin Dzeko'nun kafası", ["Edin Džeko"]),
    ("DZEKO gibi uzun", ["Edin Džeko"]),
    ("Hakan Sukurun golu", ["Hakan Şükür"]),
    ("Ronaldinho'nun dansı", ["Ronaldinho"]),
])
def test_suffixes(m, line, expected):
    assert names(m, line) == expected


# --- Ati242 referans örnekleri (Türkçe okunuşla yazılmış halleri) --------- #

@pytest.mark.parametrize("line,expected", [
    ("Abubakar gibi bitiriş", ["Vincent Aboubakar"]),
    ("Aboubakar'ın kafası", ["Vincent Aboubakar"]),
    ("savunmada Kulibali", ["Kalidou Koulibaly"]),
    ("Yannick Carrasco gibi çalım", ["Yannick Carrasco"]),
    ("yanik karasko", ["Yannick Carrasco"]),
    ("Lallana'yla ortada", ["Adam Lallana"]),
    ("Lalana", ["Adam Lallana"]),
])
def test_ati242_examples(m, line, expected):
    assert names(m, line) == expected


# --- yanlış eşleşme olmamalı ---------------------------------------------- #

@pytest.mark.parametrize("line", [
    "kanepede yatıyorum",        # Kane + "pe" ek değil
    "şükür ki buradayım",        # soyad tek başına değil, tam ad gerekli
    "ite kaka gelemedik",        # Kaká Türkçe kelime -> belirsiz
    "kaya gibi sağlam",          # Kaya Türkçe kelime
    "Turan diyarı",              # Turan kelime listesinde
    "messianik bir ses",         # kelime sınırı
])
def test_no_false_positives(m, line):
    assert names(m, line) == []


def test_ambiguous_flags(pool):
    by = {p["wikidata_id"]: p for p in pool}
    assert by["Q14"]["ambiguous"] and "kaka" in by["Q14"]["ambiguous_terms"]
    assert by["Q15"]["ambiguous"]                     # Kaya
    assert by["Q8"]["ambiguous"] and by["Q9"]["ambiguous"]   # iki Inzaghi
    assert not by["Q1"]["ambiguous"]                  # Maradona tek ve kelime değil


def test_ambiguous_mode_reports_them(pool):
    m = Matcher(pool, include_ambiguous=True)
    res = m.find("ite kaka gelemedik")
    assert [r.name for r in res] == ["Kaká"] and res[0].ambiguous


def test_ronaldo_full_name_beats_mononym(m):
    # "Cristiano Ronaldo" geçince Ronaldo Nazário ayrıca sayılmaz
    assert names(m, "Cristiano Ronaldo gibi") == ["Cristiano Ronaldo"]
    assert names(m, "Ronaldo gibi") == ["Ronaldo"]
