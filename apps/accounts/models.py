from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    class Role(models.TextChoices):
        ADMIN = "admin", "Yönetici"
        LAWYER = "lawyer", "Avukat"
        INTERN = "intern", "Stajyer"

    class Theme(models.TextChoices):
        LIGHT = "light", "Açık"
        DARK = "dark", "Koyu"

    role = models.CharField("rol", max_length=10, choices=Role.choices, default=Role.LAWYER)
    phone = models.CharField("telefon", max_length=30, blank=True)
    avatar = models.ImageField("fotoğraf", upload_to="avatars/", blank=True)
    theme = models.CharField("tema", max_length=10, choices=Theme.choices, default=Theme.LIGHT)
    page_size = models.PositiveSmallIntegerField(
        "sayfa başına kayıt", default=25, choices=[(n, str(n)) for n in (25, 50, 100)]
    )

    class Meta:
        verbose_name = "kullanıcı"
        verbose_name_plural = "kullanıcılar"
        ordering = ["first_name", "last_name"]

    def __str__(self):
        return self.get_full_name() or self.username

    @property
    def is_office_admin(self) -> bool:
        return self.is_superuser or self.role == self.Role.ADMIN

    @property
    def initials(self) -> str:
        name = self.get_full_name() or self.username
        return "".join(p[0] for p in name.split()[:2]).upper()
