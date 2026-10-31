"""Yalnızca geliştirme ortamı için örnek müvekkil ve dosya oluşturur. Gerçek veri içermez.

Önce kullanıcılar oluşturulmalıdır: manage.py setup_office_users --pin <PIN>
"""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.accounts.models import User
from apps.cases.models import Case
from apps.clients.models import Client


class Command(BaseCommand):
    help = "Geliştirme için örnek müvekkil ve dosya kayıtları oluşturur."

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("Bu komut yalnızca DEBUG=True iken çalışır.")
        lawyer = User.objects.filter(role__in=["admin", "lawyer"], is_active=True).first()
        intern = User.objects.filter(role="intern", is_active=True).first()
        if not (lawyer and intern):
            raise CommandError("Önce setup_office_users ile kullanıcıları oluşturun.")
        if Client.objects.exists():
            self.stdout.write("Müvekkil kaydı zaten var, örnek veri eklenmedi.")
            return
        common = {"responsible_lawyer": lawyer, "responsible_intern": intern}
        a = Client.objects.create(kind="person", first_name="Örnek", last_name="Müvekkil", **common)
        b = Client.objects.create(kind="company", title="Örnek Ticaret A.Ş.", **common)
        Case.objects.create(
            client=a,
            case_type="civil",
            archive_no="2026/0001",
            subject="Alacak davası (örnek)",
            **common,
        )
        Case.objects.create(
            client=b,
            case_type="enforcement",
            archive_no="2026/0002",
            subject="Kambiyo takibi (örnek)",
            enforcement_type="negotiable",
            **common,
        )
        self.stdout.write(self.style.SUCCESS("Örnek müvekkil ve dosyalar oluşturuldu."))
