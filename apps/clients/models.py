from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models
from django.db.models import Q
from django.urls import reverse

from apps.core.models import TimeStampedModel
from apps.core.text import fold, poa_reference_number, tr_upper
from apps.core.validators import normalize_iban, validate_iban, validate_tckn, validate_vkn


class PersonKind(models.TextChoices):
    PERSON = "person", "Gerçek kişi"
    COMPANY = "company", "Tüzel kişi"


LAWYER_ROLES = ("admin", "senior", "lawyer")
ASSISTANT_ROLES = ("intern", "paralegal")


def lawyer_choices():
    return {"role__in": list(LAWYER_ROLES), "is_active": True}


def intern_choices():
    return {"role__in": list(ASSISTANT_ROLES), "is_active": True}


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
        verbose_name="yardımcı sorumlu",
        on_delete=models.PROTECT,
        related_name="clients_as_intern",
        limit_choices_to=intern_choices,
        null=True,
        blank=True,
    )
    notes = models.TextField("notlar", blank=True)
    # Vekaleti olan müvekkilin numarası (V-121): vekaletin fiziki klasördeki yerini gösterir.
    poa_no = models.PositiveIntegerField(
        "vekalet no",
        null=True,
        blank=True,
        help_text=(
            "Fiziki vekalet klasöründeki sıra numarası (V-121 için 121). "
            "Aynı vekaleti paylaşan müvekkillerde numara aynı olabilir."
        ),
    )
    folder_name = models.CharField(
        "klasör adı",
        max_length=120,
        blank=True,
        help_text="Ofis klasöründeki müvekkil klasörü. Boşsa otomatik bulunur/oluşturulur.",
    )
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

    @property
    def poa_label(self) -> str:
        return f"V-{self.poa_no}" if self.poa_no else ""

    @property
    def poa_labels(self) -> list[str]:
        """Müvekkilin asıl ve kaynak listesinden ilişkilendirilen numaraları."""
        numbers = [self.poa_no] if self.poa_no else []
        reviews = list(self.imported_poa_rows.all())
        reviews.extend(member.review for member in self.imported_poa_members.all())
        for review in reviews:
            number = poa_reference_number(review.source_reference)
            if number and number not in numbers:
                numbers.append(number)
        return [f"V-{number}" for number in numbers]

    @staticmethod
    def suggest_poa_no() -> int:
        """Son vekalet numarasının bir fazlası."""
        last = Client.objects.aggregate(m=models.Max("poa_no"))["m"]
        return (last or 0) + 1

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
        # Müvekkil adları her zaman büyük harfle tutulur.
        self.first_name = tr_upper(self.first_name).strip()
        self.last_name = tr_upper(self.last_name).strip()
        self.title = tr_upper(self.title).strip()
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
    folder_path = models.CharField("klasördeki kopya", max_length=500, blank=True, editable=False)

    class Meta:
        verbose_name = "vekalet"
        verbose_name_plural = "vekaletler"
        ordering = ["-date"]

    def __str__(self):
        return f"{self.notary} — {self.date:%d.%m.%Y} / {self.journal_no}"


def retainer_upload_to(instance, filename):
    return f"clients/{instance.client_id}/sozlesme/{filename}"


class RetainerAgreement(TimeStampedModel):
    """Avukatlık sözleşmesi. Müvekkile bağlıdır; isteğe bağlı olarak bir dosyaya bağlanır."""

    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="retainer_agreements")
    case = models.ForeignKey(
        "cases.Case",
        verbose_name="ilişkili dosya",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="retainer_agreements",
    )
    signed_on = models.DateField("sözleşme tarihi")
    fee_amount = models.DecimalField(
        "vekalet ücreti (₺)", max_digits=16, decimal_places=2, null=True, blank=True
    )
    pdf = models.FileField("PDF", upload_to=retainer_upload_to, blank=True)
    notes = models.TextField("notlar", blank=True)
    folder_path = models.CharField("klasördeki kopya", max_length=500, blank=True, editable=False)

    class Meta:
        verbose_name = "avukatlık sözleşmesi"
        verbose_name_plural = "avukatlık sözleşmeleri"
        ordering = ["-signed_on", "-pk"]

    def __str__(self):
        return f"Avukatlık sözleşmesi — {self.signed_on:%d.%m.%Y}"


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


class WhatsAppSettings(models.Model):
    enabled = models.BooleanField("WhatsApp gönderimini aç", default=False)
    reminder_hours = models.PositiveSmallIntegerField(
        "kaç saat önce hatırlatılsın",
        default=24,
        validators=[MinValueValidator(1), MaxValueValidator(168)],
    )
    language = models.CharField("hazır mesaj dili", max_length=10, default="tr")
    hearing_template = models.CharField("onaylı duruşma mesajının adı", max_length=120, blank=True)
    appointment_template = models.CharField(
        "onaylı randevu mesajının adı", max_length=120, blank=True
    )
    start_template = models.CharField(
        "onaylı sohbet başlatma mesajının adı", max_length=120, blank=True
    )
    webhook_verified_at = models.DateTimeField(null=True, blank=True, editable=False)

    class Meta:
        verbose_name = "WhatsApp ofis ayarı"
        verbose_name_plural = "WhatsApp ofis ayarı"

    def __str__(self):
        return "WhatsApp ofis ayarı"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        return cls.objects.get_or_create(pk=1)[0]


class WhatsAppContact(TimeStampedModel):
    client = models.OneToOneField(Client, on_delete=models.CASCADE, related_name="whatsapp_contact")
    contact = models.ForeignKey(ClientContact, on_delete=models.SET_NULL, null=True, blank=True)
    phone_number = models.CharField(
        "WhatsApp numarası",
        max_length=15,
        unique=True,
        validators=[
            RegexValidator(r"^[1-9][0-9]{7,14}$", "Geçerli bir uluslararası numara seçin.")
        ],
    )
    opted_in = models.BooleanField("müvekkil WhatsApp mesajlarını kabul etti", default=False)
    reminders_enabled = models.BooleanField("duruşma ve randevu hatırlatması gönder", default=False)
    consent_recorded_at = models.DateTimeField(null=True, blank=True)
    consent_recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )

    class Meta:
        verbose_name = "müvekkil WhatsApp tercihi"
        verbose_name_plural = "müvekkil WhatsApp tercihleri"

    def __str__(self):
        return str(self.client)


class ClientAppointment(TimeStampedModel):
    class Status(models.TextChoices):
        PLANNED = "planned", "Planlandı"
        DONE = "done", "Yapıldı"
        CANCELLED = "cancelled", "İptal edildi"

    client = models.ForeignKey(Client, on_delete=models.PROTECT, related_name="appointments")
    title = models.CharField("randevu konusu", max_length=200)
    starts_at = models.DateTimeField("tarih ve saat")
    location = models.CharField("yer", max_length=200, blank=True)
    status = models.CharField(
        "durum", max_length=20, choices=Status.choices, default=Status.PLANNED
    )

    class Meta:
        ordering = ["-starts_at", "-pk"]
        verbose_name = "müvekkil randevusu"
        verbose_name_plural = "müvekkil randevuları"

    def __str__(self):
        return self.title


class WhatsAppMessage(models.Model):
    class Direction(models.TextChoices):
        INCOMING = "incoming", "Gelen"
        OUTGOING = "outgoing", "Giden"

    class Status(models.TextChoices):
        RECEIVED = "received", "Alındı"
        QUEUED = "queued", "Gönderilmeyi bekliyor"
        SENDING = "sending", "Gönderiliyor"
        SENT = "sent", "WhatsApp'a iletildi"
        DELIVERED = "delivered", "Ulaştı"
        READ = "read", "Okundu"
        FAILED = "failed", "Gönderilemedi"
        UNCERTAIN = "uncertain", "Gönderim sonucu kontrol edilmeli"
        CANCELLED = "cancelled", "Gönderimden kaldırıldı"

    client = models.ForeignKey(
        Client, on_delete=models.SET_NULL, null=True, blank=True, related_name="whatsapp_messages"
    )
    phone_number = models.CharField(max_length=15, db_index=True)
    direction = models.CharField(max_length=10, choices=Direction.choices)
    status = models.CharField(max_length=12, choices=Status.choices)
    body = models.TextField("mesaj", max_length=4096, blank=True)
    message_type = models.CharField(max_length=20, default="text")
    external_id = models.CharField(max_length=200, blank=True)
    template_name = models.CharField(max_length=120, blank=True)
    template_parameters = models.JSONField(default=list, blank=True)
    dedup_key = models.CharField(max_length=200, blank=True)
    hearing = models.ForeignKey("cases.Hearing", on_delete=models.SET_NULL, null=True, blank=True)
    appointment = models.ForeignKey(
        ClientAppointment, on_delete=models.SET_NULL, null=True, blank=True
    )
    occurred_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    attempted_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    error = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ["-occurred_at", "-pk"]
        verbose_name = "WhatsApp mesajı"
        verbose_name_plural = "WhatsApp mesajları"
        indexes = [models.Index(fields=["phone_number", "direction", "occurred_at"])]
        constraints = [
            models.UniqueConstraint(
                fields=["external_id"], condition=~Q(external_id=""), name="unique_whatsapp_message"
            ),
            models.UniqueConstraint(
                fields=["dedup_key"], condition=~Q(dedup_key=""), name="unique_whatsapp_dispatch"
            ),
        ]

    def __str__(self):
        return f"WhatsApp mesajı {self.pk}"


class WhatsAppReceipt(models.Model):
    external_id = models.CharField(max_length=200, unique=True)
    status = models.CharField(max_length=12)
    occurred_at = models.DateTimeField()
    error_code = models.CharField(max_length=30, blank=True)

    class Meta:
        verbose_name = "WhatsApp teslim bilgisi"
        verbose_name_plural = "WhatsApp teslim bilgileri"

    def __str__(self):
        return f"Teslim bilgisi {self.pk}"
