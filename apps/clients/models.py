from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.urls import reverse

from apps.core.models import TimeStampedModel
from apps.core.text import fold
from apps.core.validators import normalize_iban, validate_iban, validate_tckn, validate_vkn


class PersonKind(models.TextChoices):
    PERSON = "person", "Gerçek kişi"
    COMPANY = "company", "Tüzel kişi"


def lawyer_choices():
    return {"role__in": ["admin", "lawyer"], "is_active": True}


def intern_choices():
    return {"role": "intern", "is_active": True}


class Client(TimeStampedModel):
    kind = models.CharField("tür", max_length=10, choices=PersonKind.choices)
    first_name = models.CharField("ad", max_length=100, blank=True)
    last_name = models.CharField("soyad", max_length=100, blank=True)
    tckn = models.CharField("TC kimlik no", max_length=11, blank=True, validators=[validate_tckn])
    title = models.CharField("unvan", max_length=300, blank=True)
    vkn = models.CharField("vergi kimlik no", max_length=10, blank=True, validators=[validate_vkn])
    tax_office = models.CharField("vergi dairesi", max_length=100, blank=True)
    mersis_no = models.CharField("MERSİS no", max_length=16, blank=True)
    responsible_lawyer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="sorumlu avukat",
        on_delete=models.PROTECT,
        related_name="clients_as_lawyer",
        limit_choices_to=lawyer_choices,
    )
    responsible_intern = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="sorumlu stajyer",
        on_delete=models.PROTECT,
        related_name="clients_as_intern",
        limit_choices_to=intern_choices,
    )
    notes = models.TextField("notlar", blank=True)
    is_active = models.BooleanField("aktif", default=True)
    # Görüntülenen ad ve aksansız arama anahtarı save() içinde doldurulur.
    name = models.CharField("ad / unvan", max_length=300, editable=False, db_index=True)
    search_key = models.CharField(max_length=300, editable=False, db_index=True)

    class Meta:
        verbose_name = "müvekkil"
        verbose_name_plural = "müvekkiller"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["tckn"], condition=~Q(tckn=""), name="unique_client_tckn"
            ),
            models.UniqueConstraint(fields=["vkn"], condition=~Q(vkn=""), name="unique_client_vkn"),
        ]

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("clients:detail", args=[self.pk])

    @property
    def identity_no(self) -> str:
        return self.tckn if self.kind == PersonKind.PERSON else self.vkn

    def clean(self):
        errors = {}
        if self.kind == PersonKind.PERSON:
            if not self.first_name:
                errors["first_name"] = "Gerçek kişide ad zorunludur."
            if not self.last_name:
                errors["last_name"] = "Gerçek kişide soyad zorunludur."
        elif self.kind == PersonKind.COMPANY and not self.title:
            errors["title"] = "Tüzel kişide unvan zorunludur."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.kind == PersonKind.PERSON:
            self.title = self.vkn = self.tax_office = self.mersis_no = ""
            self.name = f"{self.first_name} {self.last_name}".strip()
        else:
            self.first_name = self.last_name = self.tckn = ""
            self.name = self.title.strip()
        self.search_key = fold(self.name)
        super().save(*args, **kwargs)


class ContactKind(models.TextChoices):
    PHONE = "phone", "Telefon"
    EMAIL = "email", "E-posta"
    KEP = "kep", "KEP"
    ADDRESS = "address", "Adres"


class ClientContact(models.Model):
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="contacts")
    kind = models.CharField("tür", max_length=10, choices=ContactKind.choices)
    label = models.CharField("etiket", max_length=50, blank=True, help_text="İş, ev, cep...")
    value = models.TextField("değer")
    is_primary = models.BooleanField("birincil", default=False)

    class Meta:
        verbose_name = "iletişim bilgisi"
        verbose_name_plural = "iletişim bilgileri"
        ordering = ["kind", "-is_primary", "id"]

    def __str__(self):
        return f"{self.get_kind_display()}: {self.value}"


class ClientIban(models.Model):
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="ibans")
    bank = models.CharField("banka", max_length=100, blank=True)
    iban = models.CharField("IBAN", max_length=34, validators=[validate_iban])
    holder = models.CharField("hesap sahibi", max_length=200, blank=True)
    is_primary = models.BooleanField("birincil", default=False)

    class Meta:
        verbose_name = "IBAN"
        verbose_name_plural = "IBAN listesi"
        ordering = ["-is_primary", "id"]

    def __str__(self):
        return self.formatted

    def save(self, *args, **kwargs):
        self.iban = normalize_iban(self.iban)
        super().save(*args, **kwargs)

    @property
    def formatted(self) -> str:
        return " ".join(self.iban[i : i + 4] for i in range(0, len(self.iban), 4))


class ClientRepresentative(models.Model):
    """Tüzel kişinin yetkili veya irtibat kişisi."""

    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="representatives")
    name = models.CharField("ad soyad", max_length=200)
    position = models.CharField("görev", max_length=100, blank=True)
    phone = models.CharField("telefon", max_length=30, blank=True)
    email = models.EmailField("e-posta", blank=True)

    class Meta:
        verbose_name = "yetkili kişi"
        verbose_name_plural = "yetkili kişiler"
        ordering = ["id"]

    def __str__(self):
        return self.name


def poa_upload_to(instance, filename):
    return f"clients/{instance.client_id}/vekalet/{filename}"


class PowerOfAttorney(TimeStampedModel):
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="powers_of_attorney")
    notary = models.CharField("noter", max_length=200)
    date = models.DateField("tarih")
    journal_no = models.CharField("yevmiye no", max_length=50)
    archive_no = models.CharField("arşiv no", max_length=50, blank=True)
    pdf = models.FileField("PDF", upload_to=poa_upload_to, blank=True)
    notes = models.TextField("notlar", blank=True)

    class Meta:
        verbose_name = "vekalet"
        verbose_name_plural = "vekaletler"
        ordering = ["-date"]

    def __str__(self):
        return f"{self.notary} — {self.date:%d.%m.%Y} / {self.journal_no}"


class Party(TimeStampedModel):
    """Karşı taraf: davalı, borçlu, şüpheli vb."""

    kind = models.CharField("tür", max_length=10, choices=PersonKind.choices)
    name = models.CharField("ad soyad / unvan", max_length=300)
    identity_no = models.CharField("TCKN / VKN", max_length=11, blank=True, db_index=True)
    address = models.TextField("adres", blank=True)
    lawyer = models.CharField("vekili", max_length=200, blank=True)
    notes = models.TextField("notlar", blank=True)
    search_key = models.CharField(max_length=300, editable=False, db_index=True)

    class Meta:
        verbose_name = "karşı taraf"
        verbose_name_plural = "karşı taraflar"
        ordering = ["name"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        self.search_key = fold(self.name)
        super().save(*args, **kwargs)
