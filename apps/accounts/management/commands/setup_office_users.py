"""Ofis kullanıcılarını oluşturur veya günceller.

PIN koda yazılmaz; komuta parametre olarak verilir:
    manage.py setup_office_users --pin <PIN>
Mevcut kullanıcının PIN'i yalnızca --reset-pin verilirse değiştirilir.
"""

from django.contrib.auth import password_validation
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.accounts.models import User

# (kullanıcı adı, ad, soyad, rol, unvan)
OFFICE_USERS = [
    ("ali.samet.ozkurt", "Ali Samet", "ÖZKURT", User.Role.ADMIN, "Yönetici Avukat"),
    ("nursu.ozkok", "Nursu", "ÖZKÖK", User.Role.LAWYER, "Koordinatör Avukat"),
    ("gokturk.kizilkaya", "Göktürk", "KIZILKAYA", User.Role.LAWYER, "Avukat"),
    ("irfan.mesut.baysal", "İrfan Mesut", "BAYSAL", User.Role.LAWYER, "Avukat"),
    ("ecenur.kucuk", "Ecenur", "KÜÇÜK", User.Role.INTERN, "Stajyer Avukat"),
    ("omer.faruk.ozbakir", "Ömer Faruk", "ÖZBAKIR", User.Role.INTERN, "Stajyer Avukat"),
]


class Command(BaseCommand):
    help = "Ofis kullanıcılarını oluşturur. Yeni kullanıcılara --pin ile verilen PIN atanır."

    def add_arguments(self, parser):
        parser.add_argument("--pin", required=True, help="Varsayılan PIN (4 rakam)")
        parser.add_argument(
            "--reset-pin", action="store_true", help="Mevcut kullanıcıların PIN'ini de sıfırla"
        )

    @transaction.atomic
    def handle(self, *args, pin, reset_pin, **options):
        try:
            password_validation.validate_password(pin)
        except ValidationError as e:
            raise CommandError(" ".join(e.messages)) from e
        for order, (username, first, last, role, title) in enumerate(OFFICE_USERS):
            user, created = User.objects.update_or_create(
                username=username,
                defaults={
                    "first_name": first,
                    "last_name": last,
                    "role": role,
                    "title": title,
                    "order": order,
                    "is_active": True,
                    "is_staff": role == User.Role.ADMIN,
                    "is_superuser": role == User.Role.ADMIN,
                },
            )
            if created or reset_pin:
                user.set_password(pin)
                user.save(update_fields=["password"])
            self.stdout.write(f"{'oluşturuldu' if created else 'güncellendi'}: {user} ({title})")
