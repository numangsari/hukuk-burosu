import datetime

from django.db import models


class OfficeSettings(models.Model):
    """Tek satırlık ofis ayarları tablosu (singleton, pk=1)."""

    name = models.CharField("ofis adı", max_length=200, default="Özkurt Hukuk Bürosu")
    address = models.TextField("adres", blank=True)
    phone = models.CharField("telefon", max_length=50, blank=True)
    email = models.EmailField("e-posta", blank=True)
    tax_office = models.CharField("vergi dairesi", max_length=100, blank=True)
    tax_number = models.CharField("vergi no", max_length=20, blank=True)
    logo = models.ImageField("logo", upload_to="office/", blank=True)
    calendar_ics_url = models.URLField(
        "Google Takvim gizli iCal adresi",
        max_length=1000,
        blank=True,
        help_text="Google Takvim > Ayarlar > Takvimi entegre et > iCal biçiminde gizli adres",
    )
    documents_root = models.CharField(
        "ofis klasörü",
        max_length=500,
        blank=True,
        help_text=r"Sunucu PC'de belgelerin kopyalanacağı kök klasör, ör. D:\Ozkurt Hukuk Ofis",
    )
    idle_minutes = models.PositiveSmallIntegerField(
        "boşta kalınca oturumu kapat (dakika)",
        default=30,
        help_text="Bu süre işlem yapılmayan bilgisayarda oturum kapanır. 0 = kapalı.",
    )
    upcoming_days = models.PositiveSmallIntegerField("yaklaşan tarih penceresi (gün)", default=7)
    backup_time = models.TimeField("yedek saati", default=datetime.time(12, 30))
    backup_dir = models.CharField("yedek hedef klasörü", max_length=500, blank=True)
    lawyer_can_view_accounting = models.BooleanField("avukat muhasebeyi görür", default=True)
    lawyer_can_edit_accounting = models.BooleanField("avukat muhasebe girer", default=True)
    intern_can_view_accounting = models.BooleanField("stajyer muhasebeyi görür", default=False)
    intern_can_edit_accounting = models.BooleanField("stajyer muhasebe girer", default=False)

    class Meta:
        verbose_name = "ofis ayarları"
        verbose_name_plural = "ofis ayarları"

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls) -> "OfficeSettings":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class LookupModel(models.Model):
    name = models.CharField("ad", max_length=200, unique=True)
    is_active = models.BooleanField("aktif", default=True)
    order = models.PositiveIntegerField("sıra", default=0)

    class Meta:
        abstract = True
        ordering = ["order", "name"]

    def __str__(self):
        return self.name


class TaskType(LookupModel):
    requires_document = models.BooleanField("kontrole göndermek için belge zorunlu", default=False)

    class Meta(LookupModel.Meta):
        verbose_name = "görev türü"
        verbose_name_plural = "görev türleri"


class Court(LookupModel):
    """Mahkeme, icra dairesi, savcılık vb. merci listesi."""

    class Kind(models.TextChoices):
        COURT = "court", "Mahkeme"
        ENFORCEMENT = "enforcement", "İcra Dairesi"
        PROSECUTION = "prosecution", "Savcılık"
        MEDIATION = "mediation", "Arabuluculuk Bürosu"
        OTHER = "other", "Diğer"

    kind = models.CharField("tür", max_length=20, choices=Kind.choices, default=Kind.COURT)

    class Meta(LookupModel.Meta):
        verbose_name = "merci"
        verbose_name_plural = "merciler"
