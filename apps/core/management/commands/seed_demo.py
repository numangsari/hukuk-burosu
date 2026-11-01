"""Geliştirme/deneme için gerçekçi ama UYDURMA örnek veri üretir. Yalnızca DEBUG=True iken çalışır.

Gerçek kişi verisi kullanılmaz: adlar rastgele birleştirilir, TCKN/VKN girilmez,
telefonlar 0555 000 xx xx biçimindedir. Tekrar çalıştırılırsa yeni veri eklemez.
"""

import datetime as dt
import random
from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.accounting.models import EntryKind, LedgerEntry
from apps.accounting.services import create_entry
from apps.accounts.models import User
from apps.cases import stages
from apps.cases.models import Case, CaseEvent, CaseParty, Hearing
from apps.clients.models import Client, ClientContact, ClientIban, Party, PowerOfAttorney
from apps.office.models import TaskType
from apps.tasks import services as task_services
from apps.tasks.models import Task

MARKER = "seed_demo"
FIRST = ["Ahmet", "Mehmet", "Ayşe", "Fatma", "Emre", "Zeynep", "Burak", "Elif", "Can", "Selin", "Mert", "Derya", "Kerem", "Gamze", "Onur", "Ece", "Hakan", "Pınar"]  # fmt: skip
LAST = ["YILMAZ", "KAYA", "DEMİR", "ŞAHİN", "ÇELİK", "YILDIZ", "AYDIN", "ÖZDEMİR", "ARSLAN", "DOĞAN", "KILIÇ", "ASLAN", "ÇETİN", "KARA", "KOÇ", "KURT"]  # fmt: skip
COMPANIES = ["Sakarya Yapı İnşaat Ltd. Şti.", "Marmara Lojistik A.Ş.", "Adapazarı Gıda San. Tic. Ltd. Şti.", "Erenler Otomotiv A.Ş.", "Sapanca Turizm Ltd. Şti.", "Hendek Tekstil A.Ş."]  # fmt: skip
COURTS = ["Sakarya 1. Asliye Hukuk Mahkemesi", "Sakarya 2. Asliye Hukuk Mahkemesi", "Sakarya 3. İş Mahkemesi", "Sakarya 2. Asliye Ceza Mahkemesi", "Sakarya İdare Mahkemesi", "Sakarya 4. Sulh Hukuk Mahkemesi"]  # fmt: skip
ENFORCEMENT = [
    "Sakarya 1. İcra Dairesi",
    "Sakarya 3. İcra Dairesi",
    "İstanbul Anadolu 12. İcra Dairesi",
]
SUBJECTS = {
    "civil": ["Alacak davası", "Tazminat davası", "Kira tespit davası", "Tahliye davası", "Boşanma davası", "Ortaklığın giderilmesi"],
    "criminal": ["Dolandırıcılık", "Güveni kötüye kullanma", "Tehdit"],
    "administrative": ["İmar para cezası iptali", "Ruhsat iptali"],
    "enforcement": ["Kambiyo senedine dayalı takip", "İlamsız icra takibi", "Kira alacağı takibi"],
    "investigation": ["Soruşturma — şikâyet", "Soruşturma — müdafilik"],
    "consultancy": ["Sözleşme incelemesi", "Şirket danışmanlığı"],
    "mediation": ["İşçi alacağı arabuluculuk", "Ticari uyuşmazlık arabuluculuk"],
    "notice": ["Kira ihtarnamesi", "Ödeme ihtarnamesi"],
}  # fmt: skip
TASK_TITLES = {
    "Dilekçe": ["Cevap dilekçesi hazırla", "Cevaba cevap dilekçesi", "İstinaf dilekçesi", "Bilirkişi raporuna itiraz dilekçesi"],
    "Duruşma hazırlığı": ["Duruşma notlarını hazırla", "Tanık listesini güncelle"],
    "Müvekkil görüşmesi": ["Müvekkille ön görüşme", "Müvekkile dosya durumunu bildir"],
    "Harç / Masraf": ["Gider avansı yatır", "Harç makbuzunu dosyaya ekle"],
    "İcra takibi": ["Haciz talebi", "Maaş haczi müzekkeresi", "Mal varlığı araştırması"],
    "Keşif": ["Keşif masrafını yatır"],
    "Tebligat takibi": ["UYAP tebligatlarını kontrol et", "Tebligat parçasını dosyaya işle"],
    "Bilirkişi": ["Bilirkişi raporunu incele"],
    "Diğer": ["Vekaletnameyi yenile"],
}  # fmt: skip


def phone(i):
    return f"0555 000 {i // 100:02d} {i % 100:02d}"


class Command(BaseCommand):
    help = "Deneme için uydurma örnek veri üretir (yalnızca DEBUG)."

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("Bu komut yalnızca DEBUG=True iken çalışır.")
        if Client.objects.filter(notes__contains=MARKER).exists():
            self.stdout.write("Örnek veri zaten var; yeni kayıt eklenmedi.")
            return
        lawyers = list(User.objects.filter(role__in=["admin", "lawyer"], is_active=True))
        interns = list(User.objects.filter(role="intern", is_active=True))
        if not lawyers or not interns:
            raise CommandError("Önce setup_office_users ile kullanıcıları oluşturun.")
        rnd = random.Random(20261101)
        today = timezone.localdate()
        with transaction.atomic():
            counts = self.seed(rnd, today, lawyers, interns)
        self.stdout.write(
            self.style.SUCCESS(
                "Örnek veri eklendi: " + ", ".join(f"{v} {k}" for k, v in counts.items())
            )
        )

    def seed(self, rnd, today, lawyers, interns):
        admin = next((u for u in lawyers if u.role == "admin"), lawyers[0])
        counts = dict.fromkeys(["müvekkil", "dosya", "görev", "duruşma", "hareket"], 0)
        used_names = set()
        clients = []
        for i in range(18):
            lawyer, intern = rnd.choice(lawyers), rnd.choice(interns)
            note = f"Deneme kaydı ({MARKER})"
            if i < 12:
                while True:
                    first, last = rnd.choice(FIRST), rnd.choice(LAST)
                    if (first, last) not in used_names:
                        used_names.add((first, last))
                        break
                c = Client.objects.create(kind="person", first_name=first, last_name=last, responsible_lawyer=lawyer,
                                          responsible_intern=intern, notes=note, created_by=admin)  # fmt: skip
            else:
                c = Client.objects.create(kind="company", title=COMPANIES[i - 12], tax_office="Sakarya",
                                          responsible_lawyer=lawyer, responsible_intern=intern, notes=note, created_by=admin)  # fmt: skip
            ClientContact.objects.create(
                client=c, kind="phone", label="Cep", value=phone(i + 1), is_primary=True
            )
            ClientContact.objects.create(
                client=c, kind="email", value=f"musteri{i + 1}@example.com", is_primary=True
            )
            if rnd.random() < 0.5:
                ClientIban.objects.create(
                    client=c,
                    iban="TR330006100519786457841326",
                    bank="Örnek Bank",
                    holder=c.name,
                    is_primary=True,
                )
            if rnd.random() < 0.7:
                PowerOfAttorney.objects.create(client=c, notary=f"Sakarya {rnd.randint(1, 6)}. Noterliği",
                                               date=today - dt.timedelta(days=rnd.randint(30, 900)),
                                               journal_no=str(rnd.randint(10000, 99999)), archive_no=f"V-{100 + i}", created_by=admin)  # fmt: skip
            clients.append(c)
        counts["müvekkil"] = len(clients)

        types = list(SUBJECTS)
        cases = []
        base_no = 200
        for n in range(32):
            c = clients[n % len(clients)] if n < len(clients) else rnd.choice(clients)
            t = rnd.choice(types)
            authority = rnd.choice(ENFORCEMENT) if t == "enforcement" else (
                "Sakarya Cumhuriyet Başsavcılığı" if t == "investigation" else (
                    f"Sakarya {rnd.randint(1, 8)}. Noterliği" if t == "notice" else (
                        "Sakarya Arabuluculuk Bürosu" if t == "mediation" else ("" if t == "consultancy" else rnd.choice(COURTS)))))  # fmt: skip
            status = rnd.choices(["open", "closed"], [90, 10])[0]
            k = Case.objects.create(
                client=c, case_type=t, archive_no=f"2026/{base_no + n:04d}",
                official_no=f"2026/{rnd.randint(10, 999)} {'E.' if t in ('civil', 'criminal', 'administrative') else ''}".strip(),
                authority=authority, subject=rnd.choice(SUBJECTS[t]), status=status,
                closing_reason=stages.closing_reasons(t)[0].key if status == "closed" else "",
                enforcement_type="negotiable" if t == "enforcement" else "",
                value=Decimal(rnd.randrange(20_000, 900_000, 500)) if t in ("civil", "enforcement", "mediation") else None,
                responsible_lawyer=c.responsible_lawyer, responsible_intern=c.responsible_intern,
                opened_on=today - dt.timedelta(days=rnd.randint(10, 500)), created_by=admin,
            )  # fmt: skip
            if t not in ("consultancy",):
                role = {
                    "enforcement": "debtor",
                    "investigation": "suspect",
                    "notice": "addressee",
                }.get(t, "defendant")
                p = Party.objects.create(kind=rnd.choice(["person", "company"]),
                                         name=f"{rnd.choice(FIRST)} {rnd.choice(LAST)}" if rnd.random() < 0.6 else rnd.choice(COMPANIES).replace("A.Ş.", "Ticaret A.Ş."),
                                         created_by=admin)  # fmt: skip
                CaseParty.objects.create(case=k, party=p, role=role)
            CaseEvent.objects.create(
                case=k,
                date=k.opened_on,
                title="Dosya açıldı",
                description="Müvekkille ilk görüşme yapıldı.",
                created_by=admin,
            )
            cases.append(k)
        counts["dosya"] = len(cases)
        open_cases = [k for k in cases if k.status != "closed"]

        # Görevler
        type_by_name = {t.name: t for t in TaskType.objects.all()}
        no_doc_types = [
            n for n in TASK_TITLES if n in type_by_name and not type_by_name[n].requires_document
        ]
        doc_types = [
            n for n in TASK_TITLES if n in type_by_name and type_by_name[n].requires_document
        ]
        everyone = lawyers + interns
        for _n in range(48):
            k = rnd.choice(open_cases)
            tname = rnd.choice(no_doc_types if rnd.random() < 0.75 or not doc_types else doc_types)
            assignee = rnd.choice(
                [
                    k.responsible_intern,
                    k.responsible_intern,
                    k.responsible_lawyer,
                    rnd.choice(everyone),
                ]
            )
            reviewer = (
                k.responsible_lawyer
                if assignee != k.responsible_lawyer
                else rnd.choice([u for u in lawyers if u != assignee] or lawyers)
            )
            if reviewer == assignee:
                continue
            due = today + dt.timedelta(days=rnd.randint(-8, 25))
            t = Task.objects.create(task_type=type_by_name[tname], title=rnd.choice(TASK_TITLES[tname]), case=k,
                                    assignee=assignee, reviewer=reviewer, due_date=due, created_by=reviewer,
                                    notes="Örnek görev." if rnd.random() < 0.3 else "")  # fmt: skip
            task_services.on_created(t, reviewer)
            if type_by_name[tname].requires_document:
                counts["görev"] += 1
                continue  # belge zorunlu türler aktif kalır
            r = rnd.random()
            if r < 0.25:
                task_services.perform(t, "submit", assignee)
            elif r < 0.35:
                task_services.perform(t, "submit", assignee)
                task_services.perform(
                    t, "revise", reviewer, "Eksik noktaları tamamlayın (örnek revizyon)."
                )
            elif r < 0.55:
                task_services.perform(t, "submit", assignee)
                task_services.perform(t, "approve", reviewer)
            counts["görev"] += 1

        # Duruşmalar
        court_cases = [
            k for k in open_cases if k.case_type in ("civil", "criminal", "administrative")
        ]
        for k in rnd.sample(court_cases, min(14, len(court_cases))):
            day = today + dt.timedelta(days=rnd.randint(1, 35))
            if day.weekday() >= 5:
                day += dt.timedelta(days=7 - day.weekday())
            start = timezone.make_aware(
                dt.datetime.combine(
                    day, dt.time(rnd.choice([9, 10, 11, 13, 14, 15]), rnd.choice([0, 15, 30, 45]))
                )
            )
            Hearing.objects.create(
                case=k,
                starts_at=start,
                authority=k.authority,
                room=str(rnd.randint(1, 20)),
                created_by=admin,
            )
            past = start - dt.timedelta(days=rnd.randint(40, 90))
            Hearing.objects.create(case=k, starts_at=past, authority=k.authority, status="postponed",
                                   result="Tanıkların dinlenmesi için ertelendi (örnek).", created_by=admin)  # fmt: skip
            CaseEvent.objects.create(case=k, date=past.date(), kind="hearing", title="Duruşma ertelendi",
                                     description="Tanıkların dinlenmesi için ertelendi (örnek).", created_by=admin)  # fmt: skip
            counts["duruşma"] += 2

        # Muhasebe
        for k in cases:
            fee = Decimal(rnd.randrange(15_000, 120_000, 1000))
            create_entry(LedgerEntry(client=k.client, case=k, kind=EntryKind.FEE, amount=fee, date=k.opened_on,
                                     description="Vekalet ücreti", created_by=admin))  # fmt: skip
            create_entry(LedgerEntry(client=k.client, case=k, kind=EntryKind.EXPENSE, amount=Decimal(rnd.randrange(800, 6000, 50)),
                                     date=k.opened_on + dt.timedelta(days=3), description="Harç ve gider avansı", created_by=admin))  # fmt: skip
            paid = fee * Decimal(rnd.choice(["0", "0.3", "0.5", "1"]))
            if paid:
                create_entry(LedgerEntry(client=k.client, case=k, kind=EntryKind.COLLECTION, amount=paid.quantize(Decimal("1")),
                                         date=k.opened_on + dt.timedelta(days=rnd.randint(5, 60)), description="Müvekkilden tahsilat", created_by=admin))  # fmt: skip
                counts["hareket"] += 1
            counts["hareket"] += 2
            if k.case_type == "enforcement" and rnd.random() < 0.7:
                collected = Decimal(rnd.randrange(20_000, 200_000, 1000))
                d = k.opened_on + dt.timedelta(days=rnd.randint(30, 120))
                create_entry(LedgerEntry(client=k.client, case=k, kind=EntryKind.TRUST_IN, amount=collected, date=d,
                                         description="Borçludan tahsilat", created_by=admin))  # fmt: skip
                create_entry(LedgerEntry(client=k.client, case=k, kind=EntryKind.TRUST_OUT, amount=(collected * Decimal("0.7")).quantize(Decimal("1")),
                                         date=d + dt.timedelta(days=3), description="Müvekkile havale", created_by=admin))  # fmt: skip
                counts["hareket"] += 2
        return counts
