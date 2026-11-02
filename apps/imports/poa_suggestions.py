"""Vekalet listesinde yalnızca açık biçimli satırlar için öneri üretir."""

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.clients.models import Client
from apps.core.text import fold

from .models import PowerOfAttorneyReview
from .poa_review import SourceRow, get_teams, mark_processed, read_source

# Tek başına ad veya soyad kabul edilmeyecek kurum ve işlem sözcükleri.
EXCLUDED_WORDS = {
    "apartman",
    "apartmani",
    "baro",
    "barosu",
    "baskanligi",
    "belediye",
    "dernek",
    "dernegi",
    "egitim",
    "eczane",
    "gida",
    "grup",
    "hastane",
    "hastanesi",
    "icra",
    "insaat",
    "kooperatif",
    "koop",
    "lisesi",
    "mahkeme",
    "mudurlugu",
    "okul",
    "okulu",
    "otomotiv",
    "sanayi",
    "satis",
    "seker",
    "sirketi",
    "site",
    "sitesi",
    "tapu",
    "tarim",
    "temsil",
    "ticaret",
    "vakfi",
    "ve",
    "vekaletname",
    "yapi",
    "yonetim",
    "yonetimi",
    "yoneticiligi",
}

# Çok sözcüklü adlarda, iki adın da yaygın kişi adı olduğu açık örnekler kullanılır.
MALE_FIRST_NAMES = {
    "abdussamet",
    "alparslan",
    "ahmed",
    "ahmet",
    "ali",
    "apdul",
    "atakan",
    "aziz",
    "baki",
    "baran",
    "beytullah",
    "bekir",
    "berke",
    "birkan",
    "bulent",
    "cihan",
    "cemil",
    "cuneyt",
    "ertugrul",
    "fahreddin",
    "halil",
    "hamdi",
    "hasan",
    "ibrahim",
    "ilker",
    "ismail",
    "korkud",
    "lutfi",
    "mehmet",
    "mohmd",
    "muhammed",
    "muhammet",
    "mumin",
    "mahmut",
    "muzaffer",
    "mustafa",
    "nazif",
    "necip",
    "nedim",
    "oguzhan",
    "omer",
    "resit",
    "salih",
    "semsi",
    "yigit",
    "yunus",
    "yusuf",
    "yakup",
    "umit",
}
MALE_MIDDLE_NAMES = {
    "adem",
    "ahmet",
    "ali",
    "arda",
    "berke",
    "berk",
    "bilgehan",
    "atilla",
    "baran",
    "berkay",
    "cahit",
    "can",
    "cenk",
    "cuneyt",
    "cem",
    "cemil",
    "duha",
    "emre",
    "eren",
    "enes",
    "faruk",
    "fatih",
    "fehmi",
    "hazar",
    "haydar",
    "kagan",
    "kaan",
    "kerim",
    "melih",
    "mert",
    "mehmet",
    "mesut",
    "mithat",
    "murat",
    "necati",
    "onur",
    "oguz",
    "osman",
    "osama",
    "rasit",
    "riza",
    "sami",
    "samet",
    "samil",
    "serhat",
    "selim",
    "sinasi",
    "sukru",
    "taha",
    "tahsin",
    "tevfik",
    "ugur",
    "yasin",
    "yasar",
    "zahit",
    "ziya",
}
FEMALE_FIRST_NAMES = {
    "aysegul",
    "azade",
    "deniz",
    "elmas",
    "fatma",
    "feyza",
    "fulya",
    "hasret",
    "melis",
    "murvet",
    "saliha",
    "selva",
    "zeliha",
    "zeynep",
    "yasemin",
}
FEMALE_MIDDLE_NAMES = {
    "aysun",
    "betul",
    "esma",
    "erva",
    "gulsum",
    "gulsevin",
    "handan",
    "ilayda",
    "irem",
    "meltem",
    "nedime",
    "nur",
    "sena",
    "sitare",
}


@dataclass(frozen=True)
class SuggestedClient:
    row: object
    kind: str
    first_name: str = ""
    last_name: str = ""
    title: str = ""
    annotation: str = ""

    @property
    def name(self):
        return self.title if self.kind == "company" else f"{self.first_name} {self.last_name}"


def suggest(row):
    """Açık kişi adlarını ve türü anlaşılır kurum unvanlarını ayırır."""
    if not row.poa_no or row.poa_no > 2147483647:
        return None
    parts = unicodedata.normalize("NFC", row.name).split()
    if not parts:
        return None
    title = " ".join(parts)
    folded_title = fold(title)
    if not any(separator in title for separator in (",", ";", "/")):
        has_trade_marker = bool(re.search(r"\btic(?:aret)?\b", folded_title))
        has_business_marker = bool(re.search(r"\botomotiv\b", folded_title))
        has_company_form = bool(re.search(r"\b(?:anonim|limited)\s+sirketi\b", folded_title))
        if len(title) <= 300 and (has_company_form or (has_trade_marker and has_business_marker)):
            return SuggestedClient(row, "company", title=title)
    if any(not part.isalpha() for part in parts):
        return None
    words = [fold(part) for part in parts]
    if (len(parts) == 2 and words[-1] == "tekstil") or words[-1] in {"dernegi", "vakfi"}:
        if len(" ".join(parts)) > 300:
            return None
        return SuggestedClient(row, "company", title=" ".join(parts))
    annotation = ""
    if words[-1] == "bosanma":
        annotation = parts[-1]
        parts, words = parts[:-1], words[:-1]
    if any(len(part) < 2 for part in parts):
        return None
    if any(word in EXCLUDED_WORDS or word == "tekstil" for word in words):
        return None
    if len(parts) == 3:
        male = words[0] in MALE_FIRST_NAMES and words[1] in MALE_MIDDLE_NAMES
        female = words[0] in FEMALE_FIRST_NAMES and words[1] in FEMALE_MIDDLE_NAMES
        if not male and not female:
            return None
        return SuggestedClient(
            row, "person", first_name=" ".join(parts[:2]), last_name=parts[2], annotation=annotation
        )
    if len(parts) != 2:
        return None
    return SuggestedClient(
        row, "person", first_name=parts[0], last_name=parts[1], annotation=annotation
    )


def name_key(name):
    return fold(unicodedata.normalize("NFC", name))


def build_plan(source_hash, rows):
    """Aynı ad veya numarayı içeren ve mevcut kayıtla çakışan satırları dışarıda bırakır."""
    mark_processed(source_hash, rows)
    suggestions = [item for row in rows if (item := suggest(row))]
    names = Counter()
    for row in rows:
        for part in row.name.split(","):
            candidate = suggest(SourceRow(row.number, row.reference, part.strip(), row.note))
            if candidate:
                names[name_key(candidate.name)] += 1
    numbers = Counter(row.poa_no for row in rows if row.poa_no)
    existing_names = {
        name_key(name) for name in Client.objects.values_list("search_key", flat=True)
    }
    existing_numbers = set(Client.objects.exclude(poa_no=None).values_list("poa_no", flat=True))
    previously_reviewed = set(
        PowerOfAttorneyReview.objects.filter(source_sha256=source_hash).values_list(
            "source_row", flat=True
        )
    )
    return [
        item
        for item in suggestions
        if item.row.status == "pending"
        and item.row.number not in previously_reviewed
        and names[name_key(item.name)] == 1
        and numbers[item.row.poa_no] == 1
        and name_key(item.name) not in existing_names
        and item.row.poa_no not in existing_numbers
    ]


@transaction.atomic
def execute(source_hash):
    """Liste değişmediyse açık önerileri ve kaynak izlerini birlikte kaydeder."""
    teams = get_teams(lock=True)
    current_hash, rows = read_source()
    if current_hash != source_hash:
        raise ValidationError("Kaynak liste değişti; aktarım yapılmadı.")
    plan = build_plan(current_hash, rows)
    counts = [
        Client.objects.filter(responsible_lawyer=lawyer, responsible_intern=intern).count()
        for lawyer, intern in teams
    ]
    for item in plan:
        team_index = min(range(len(teams)), key=counts.__getitem__)
        lawyer, intern = teams[team_index]
        notes = []
        if item.annotation:
            notes.append(f"Kaynak açıklaması: {item.annotation}")
        if item.row.note and item.row.note != ".":
            notes.append(f"Kaynak notu: {item.row.note}")
        client = Client(
            kind=item.kind,
            first_name=item.first_name,
            last_name=item.last_name,
            title=item.title,
            poa_no=item.row.poa_no,
            notes="\n".join(notes),
            responsible_lawyer=lawyer,
            responsible_intern=intern,
        )
        client.full_clean()
        client.save()
        PowerOfAttorneyReview.objects.update_or_create(
            source_sha256=current_hash,
            source_row=item.row.number,
            defaults={
                "client": client,
                "created_by": None,
                "source_reference": item.row.reference,
                "source_note": item.row.note,
                "automatic": True,
            },
        )
        counts[team_index] += 1
    if read_source()[0] != current_hash:
        raise ValidationError("Kaynak liste aktarım sırasında değişti; işlem geri alındı.")
    return len(plan)
