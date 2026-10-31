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
    title = models.CharField(
        "unvan", max_length=100, blank=True, help_text="Ör. Koordinatör Avukat"
    )
    order = models.PositiveSmallIntegerField("giriş ekranı sırası", default=0)
    phone = models.CharField("telefon", max_length=30, blank=True)
    avatar = models.ImageField("fotoğraf", upload_to="avatars/", blank=True)
    theme = models.CharField("tema", max_length=10, choices=Theme.choices, default=Theme.LIGHT)
    page_size = models.PositiveSmallIntegerField(
        "sayfa başına kayıt", default=25, choices=[(n, str(n)) for n in (25, 50, 100)]
    )

    class Meta:
        verbose_name = "kullanıcı"
        verbose_name_plural = "kullanıcılar"
        ordering = ["order", "first_name", "last_name"]

    def __str__(self):
        return self.get_full_name() or self.username

    @property
    def is_office_admin(self) -> bool:
        return self.is_superuser or self.role == self.Role.ADMIN

    @property
    def display_title(self) -> str:
        return self.title or self.get_role_display()

    @property
    def avatar_hue(self) -> int:
        """Kullanıcıya sabit bir avatar rengi (HSL ton açısı)."""
        return (self.order * 67 + 210) % 360

    @property
    def initials(self) -> str:
        if self.first_name and self.last_name:
            return (self.first_name[0] + self.last_name[0]).upper()
        return (self.get_full_name() or self.username)[:2].upper()
