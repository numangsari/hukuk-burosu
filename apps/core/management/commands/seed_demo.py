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
from apps.cases import seizure_types, stages
from apps.cases.models import Case, CaseEvent, CaseParty, Seizure
from apps.cases.party_roles import PARTY_ROLES
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
        counts = dict.fromkeys(["müvekkil", "dosya", "görev", "hareket"], 0)
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
        for n in range(32):
            c = clients[n % len(clients)] if n < len(clients) else rnd.choice(clients)
            t = "enforcement" if n == 1 else rnd.choice(types)
            authority = rnd.choice(ENFORCEMENT) if t == "enforcement" else (
                "Sakarya Cumhuriyet Başsavcılığı" if t == "investigation" else (
                    f"Sakarya {rnd.randint(1, 8)}. Noterliği" if t == "notice" else (
                        "Sakarya Arabuluculuk Bürosu" if t == "mediation" else ("" if t == "consultancy" else rnd.choice(COURTS)))))  # fmt: skip
            status = "closed" if n == 0 else rnd.choices(["open", "closed"], [90, 10])[0]
            if n == 1:
                status = "open"
            folder, number = (
                ("1", "58")
                if n == 0
                else ("15", "8")
                if n == 1
                else ("4", "85")
                if n == 2
                else (str(n % 15 + 1), str(58 + n))
            )
            k = Case.objects.create(
                client=c, case_type=t, archive_folder_no=folder, archive_no=number,
                official_no=f"{today.year}/{rnd.randint(10, 999)}" if t != "consultancy" else "",
                authority=authority, subject=rnd.choice(SUBJECTS[t]), status=status,
                client_role=PARTY_ROLES[t][0][0],
                closing_reason=stages.closing_reasons(t)[0].key if status == "closed" else "",
                enforcement_type="negotiable" if t == "enforcement" else "",
                value=Decimal(rnd.randrange(20_000, 900_000, 500)) if t in ("civil", "enforcement", "mediation") else None,
                responsible_lawyer=c.responsible_lawyer, responsible_intern=c.responsible_intern,
                opened_on=today - dt.timedelta(days=rnd.randint(10, 500)), created_by=admin,
            )  # fmt: skip
            if t not in ("consultancy",):
                role = "debtor" if t == "enforcement" else PARTY_ROLES[t][1][0]
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

        # İcra sekmesindeki örnekler gelecekte yenilenecek biçimde hazırlanır.
        enforcement_case = cases[1]
        debtor = enforcement_case.party_links.get(role="debtor").party
        seizure_date = today - dt.timedelta(days=90)
        for details in (
            {"kind": "bank", "state": "bank_seized", "bank_name": "Örnek Bankası"},
            {
                "kind": "vehicle",
                "state": "vehicle_seized",
                "plate": "54 ABC 123",
                "renewal_on": seizure_types.suggested_renewal(seizure_date),
            },
        ):
            item = Seizure(
                case=enforcement_case,
                debtor=debtor.name,
                debtor_party=debtor,
                seized_on=seizure_date,
                created_by=admin,
                **details,
            )
            item.full_clean()
            item.save()

        # Görevler
        no_doc_types = list(TaskType.objects.filter(is_active=True, requires_document=False))
        if not no_doc_types:
            raise CommandError("Etkin görev türü bulunamadı.")
        everyone = lawyers + interns
        closed_count = 0
        for _n in range(48):
            k = rnd.choice(open_cases)
            task_type = rnd.choice(no_doc_types)
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
            t = Task.objects.create(task_type=task_type, title=task_type.name if task_type.name != "Diğer" else "Dosya belgelerini düzenle", case=k,
                                    assignee=assignee, reviewer=reviewer, due_date=due, created_by=reviewer,
                                    notes="Örnek görev." if rnd.random() < 0.3 else "")  # fmt: skip
            task_services.on_created(t, reviewer)
            if closed_count < 5:
                task_services.perform(t, "submit", assignee, "Hazır, kontrole gönderildi.")
                task_services.perform(t, "approve", reviewer)
                t.status = "done"
                t.completed_at = timezone.now() - dt.timedelta(days=(1, 3, 8, 20, 40)[closed_count])
                t.save(update_fields=["status", "completed_at", "updated_at"])
                task_services.award_closed_task_points(t)
                closed_count += 1
                counts["görev"] += 1
                continue
            r = rnd.random()
            if r < 0.25:
                task_services.perform(t, "submit", assignee, "Hazır, kontrole gönderildi.")
            elif r < 0.35:
                task_services.perform(t, "submit", assignee, "Hazır, kontrole gönderildi.")
                task_services.perform(
                    t, "revise", reviewer, "Eksik noktaları tamamlayın (örnek revizyon)."
                )
            elif r < 0.45:
                task_services.perform(t, "submit", assignee, "Hazır, kontrole gönderildi.")
                task_services.perform(t, "revise", reviewer, "Eksik bilgileri tamamlayın (örnek).")
                task_services.perform(t, "submit", assignee, "Hazır, kontrole gönderildi.")
            elif r < 0.60:
                task_services.perform(t, "submit", assignee, "Hazır, kontrole gönderildi.")
                task_services.perform(t, "approve", reviewer)
            counts["görev"] += 1

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
