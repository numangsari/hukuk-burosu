"""Yalnızca geliştirme ortamı için örnek kullanıcı ve kayıt oluşturur. Gerçek veri içermez."""

import secrets

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.accounts.models import User
from apps.cases.models import Case
from apps.clients.models import Client


class Command(BaseCommand):
    help = "Geliştirme için örnek kullanıcılar (yonetici, avukat, stajyer) ve kayıtlar oluşturur."

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("Bu komut yalnızca DEBUG=True iken çalışır.")
        password = secrets.token_urlsafe(9)
        users = {}
        for username, role, first, last in [
            ("yonetici", User.Role.ADMIN, "Ofis", "Yöneticisi"),
            ("avukat", User.Role.LAWYER, "Deneme", "Avukat"),
            ("stajyer", User.Role.INTERN, "Deneme", "Stajyer"),
        ]:
            user, _ = User.objects.get_or_create(
                username=username, defaults={"role": role, "first_name": first, "last_name": last}
            )
            user.set_password(password)
            user.is_staff = user.is_superuser = role == User.Role.ADMIN
            user.save()
            users[role] = user

        if not Client.objects.exists():
            common = {
                "responsible_lawyer": users[User.Role.LAWYER],
                "responsible_intern": users[User.Role.INTERN],
            }
            a = Client.objects.create(
                kind="person", first_name="Örnek", last_name="Müvekkil", **common
            )
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
        self.stdout.write(
            self.style.SUCCESS(f"Kullanıcılar: yonetici / avukat / stajyer — şifre: {password}")
        )
