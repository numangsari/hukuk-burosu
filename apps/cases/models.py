import re
import uuid
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.urls import reverse
from django.utils import timezone

from apps.clients.models import Client, Party, intern_choices, lawyer_choices
from apps.core.models import TimeStampedModel
from apps.core.text import tr_upper

from . import seizure_types, stages
from .party_roles import PARTY_ROLE_CHOICES, PARTY_ROLES


class CaseType(models.TextChoices):
    CIVIL = "civil", "Hukuk Davası"
    CRIMINAL = "criminal", "Ceza Davası"
    ADMINISTRATIVE = "administrative", "İdari Dava"
    ENFORCEMENT = "enforcement", "İcra Takibi"
    INVESTIGATION = "investigation", "Soruşturma"
    CONSULTANCY = "consultancy", "Sözleşme"
    MEDIATION = "mediation", "Arabuluculuk"
    NOTICE = "notice", "İhtarname"
    OTHER = "other", "Diğer"


LITIGATION_TYPES = {CaseType.CIVIL, CaseType.CRIMINAL, CaseType.ADMINISTRATIVE}

# Türe göre form etiketleri. Boş değer alanın o türde gizleneceğini belirtir.
TYPE_LABELS = {
    kind: {
        "official_no": "" if kind in {CaseType.CONSULTANCY, CaseType.OTHER} else "Dosya Numarası",
        "authority": "" if kind in {CaseType.CONSULTANCY, CaseType.OTHER} else "Kurum Adı",
        "subject": "Konu",
        "value": "",
    }
    for kind in CaseType
}


class CaseStatus(models.TextChoices):
    OPEN = "open", "Açık"
    CLOSED = "closed", "Kapalı"


class EnforcementType(models.TextChoices):
    WITHOUT_JUDGMENT = "without_judgment", "İlamsız"
    WITH_JUDGMENT = "with_judgment", "İlamlı"
    NEGOTIABLE = "negotiable", "Kambiyo"
    MORTGAGE = "mortgage", "İpoteğin paraya çevrilmesi"
    PLEDGE = "pledge", "Rehnin paraya çevrilmesi"
    EVICTION = "eviction", "Tahliye"


NUMBER_SUFFIX = {
    CaseType.CIVIL: "Esas",
    CaseType.CRIMINAL: "Esas",
    CaseType.ADMINISTRATIVE: "Esas",
    CaseType.ENFORCEMENT: "İcra",
    CaseType.INVESTIGATION: "Soruşturma",
    CaseType.MEDIATION: "Arabuluculuk",
}
_YEAR_NUMBER = re.compile(r"^\d{4}/\d+$")


def _with_suffix(value: str, suffix: str) -> str:
    """Yalnızca yıl/numara biçimindeki numaraya ek getirilir (eski biçimli numaralar değişmez)."""
    if suffix and value and _YEAR_NUMBER.match(value):
        return f"{value} {suffix}"
    return value


class CaseFlow(models.Model):
    """Birbirine bağlanan dosyaların ortak safahat grubu. Gruptaki dosyalar aynı akışı görür."""

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "ortak safahat"
        verbose_name_plural = "ortak safahatlar"

    def __str__(self):
        return f"Ortak safahat {self.pk}"


class Case(TimeStampedModel):
    client = models.ForeignKey(
        Client, verbose_name="müvekkil", on_delete=models.PROTECT, related_name="cases"
    )
    case_type = models.CharField("dosya türü", max_length=20, choices=CaseType.choices)
    client_role = models.CharField(
        "müvekkilin sıfatı", max_length=32, choices=PARTY_ROLE_CHOICES, blank=True
    )
    archive_folder_no = models.CharField("klasör no", max_length=50, blank=True)
    archive_no = models.CharField("dosya no", max_length=50)
    official_no = models.CharField("dosya numarası", max_length=100, blank=True)
    authority = models.CharField("kurum adı", max_length=200, blank=True)
    subject = models.CharField("konu", max_length=300)
    value = models.DecimalField("değer", max_digits=16, decimal_places=2, null=True, blank=True)
    status = models.CharField(
        "durum", max_length=20, choices=CaseStatus.choices, default=CaseStatus.OPEN
    )
    # Açık dosyanın aşaması; seçenekler türe göre `stages.py` içindedir.
    stage = models.CharField("aşama", max_length=40, blank=True)
    closing_reason = models.CharField("kapanma nedeni", max_length=40, blank=True)
    closing_note = models.TextField("kapanış notu", blank=True)
    decision_date = models.DateField("karar tarihi", null=True, blank=True)
    decision_no = models.CharField("karar numarası", max_length=100, blank=True)
    closing_amount = models.DecimalField(
        "tahsil/ödeme tutarı", max_digits=16, decimal_places=2, null=True, blank=True
    )
    closing_amount_date = models.DateField("tahsil/ödeme tarihi", null=True, blank=True)
    closing_accounted = models.BooleanField("muhasebeye kaydedildi", null=True, blank=True)
    enforcement_type = models.CharField(
        "takip türü", max_length=20, choices=EnforcementType.choices, blank=True
    )
    crime = models.CharField("suç", max_length=200, blank=True)
    mediator = models.CharField("arabulucu", max_length=200, blank=True)
    responsible_lawyer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="sorumlu avukat",
        on_delete=models.PROTECT,
        related_name="cases_as_lawyer",
        limit_choices_to=lawyer_choices,
    )
    responsible_intern = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="sorumlu stajyer",
        on_delete=models.PROTECT,
        related_name="cases_as_intern",
        limit_choices_to=intern_choices,
    )
    opened_on = models.DateField(
        "dosya açılış tarihi", default=timezone.localdate, null=True, blank=True
    )
    flow = models.ForeignKey(
        CaseFlow,
        verbose_name="ortak safahat",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="cases",
    )
    # Asıl müvekkil `client`dir; dosyada birden fazla müvekkil varsa diğerleri burada tutulur.
    co_clients = models.ManyToManyField(
        Client,
        through="CaseCoClient",
        verbose_name="ek müvekkiller",
        blank=True,
        related_name="co_cases",
    )
    # Ortak safahattaki sıra ve bu dosyanın akışa neden eklendiğini anlatan not.
    flow_position = models.PositiveIntegerField("akıştaki sıra", default=0)
    flow_note = models.TextField("bağlantı notu", blank=True)
    closed_on = models.DateField("kapanış tarihi", null=True, blank=True)
    notes = models.TextField("notlar", blank=True)
    folder_name = models.CharField(
        "klasör adı",
        max_length=150,
        blank=True,
        help_text='Müvekkil klasörü içindeki dosya klasörü. Boşsa "Arşiv no - Konu" kullanılır.',
    )
    parties = models.ManyToManyField(
        Party, through="CaseParty", related_name="cases", verbose_name="karşı taraflar"
    )

    class Meta:
        verbose_name = "dosya"
        verbose_name_plural = "dosyalar"
        ordering = ["-created_at"]

    def get_client_role_display(self):
        return dict(PARTY_ROLES.get(self.case_type, [])).get(
            self.client_role, dict(PARTY_ROLE_CHOICES).get(self.client_role, self.client_role)
        )

    @property
    def archive_reference(self):
        if self.archive_folder_no:
            return f"{self.archive_folder_no} / {self.archive_no}"
        return self.archive_no

    def client_ids(self) -> set:
        """Dosyanın tüm müvekkillerinin (asıl + ek) kimlikleri."""
        return {self.client_id, *self.co_clients.values_list("pk", flat=True)}

    @property
    def all_clients(self) -> list:
        return [self.client, *self.co_clients.all()]

    @property
    def official_no_display(self) -> str:
        """Dosya numarası; türüne göre sonuna Esas / İcra / Soruşturma / Arabuluculuk eklenir."""
        return _with_suffix(self.official_no, NUMBER_SUFFIX.get(self.case_type, ""))

    @property
    def decision_no_display(self) -> str:
        return _with_suffix(self.decision_no, "Karar")

    @property
    def display_name(self):
        if self.case_type in {CaseType.CONSULTANCY, CaseType.OTHER}:
            return self.subject
        return (
            " - ".join(part for part in (self.authority, self.official_no_display) if part)
            or self.subject
        )

    def __str__(self):
        return self.display_name

    def get_absolute_url(self):
        return reverse("cases:detail", args=[self.pk])

    def save(self, *args, **kwargs):
        self.authority = tr_upper(self.authority).strip()
        self.subject = tr_upper(self.subject).strip()  # dosya adları büyük harf
        if self.status == CaseStatus.OPEN and self.stage not in dict(
            stages.open_stages(self.case_type)
        ):
            self.stage = stages.default_stage(self.case_type)
        super().save(*args, **kwargs)

    @property
    def labels(self) -> dict:
        return TYPE_LABELS[CaseType(self.case_type)]

    @property
    def is_litigation(self) -> bool:
        return self.case_type in LITIGATION_TYPES

    @property
    def is_open(self) -> bool:
        return self.status != CaseStatus.CLOSED

    @property
    def stage_label(self) -> str:
        return stages.stage_label(self.case_type, self.stage)

    @property
    def closing_label(self) -> str:
        return stages.closing_label(self.case_type, self.closing_reason)

    @property
    def status_detail(self) -> str:
        """Durumun alt satırı: açıkta aşama, kapalıda kapanma nedeni."""
        return self.stage_label if self.is_open else self.closing_label

    @property
    def status_summary(self) -> str:
        detail = self.status_detail
        label = self.get_status_display()
        return f"{label} / {detail}" if detail else label

    @staticmethod
    def suggest_archive_no() -> str:
        """Son girilen arşiv no'nun sonundaki sayıyı artırarak boş bir numara önerir."""
        last = Case.objects.order_by("-created_at").values_list("archive_no", flat=True).first()
        if not last:
            return "1"
        match = re.search(r"(\d+)(\D*)$", last)
        if not match:
            return ""
        prefix, digits, suffix = last[: match.start(1)], match.group(1), match.group(2)
        n = int(digits)
        existing = set(Case.objects.values_list("archive_no", flat=True))
        while True:
            n += 1
            candidate = f"{prefix}{str(n).zfill(len(digits))}{suffix}"
            if candidate not in existing:
                return candidate


class PartyRole(models.TextChoices):
    DEFENDANT = "defendant", "Davalı"
    PLAINTIFF = "plaintiff", "Davacı"
    DEBTOR = "debtor", "Borçlu"
    CREDITOR = "creditor", "Alacaklı"
    SUSPECT = "suspect", "Şüpheli / Sanık"
    COMPLAINANT = "complainant", "Müşteki"
    ADDRESSEE = "addressee", "Muhatap"
    OTHER = "other", "Karşı taraf"


class CaseCoClient(models.Model):
    """Dosyanın asıl müvekkili dışındaki müvekkilleri ve her birinin sıfatı."""

    case = models.ForeignKey(Case, on_delete=models.CASCADE, related_name="co_client_links")
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="co_case_links")
    role = models.CharField("müvekkilin sıfatı", max_length=32, blank=True)

    class Meta:
        verbose_name = "dosya müvekkili"
        verbose_name_plural = "dosya müvekkilleri"
        ordering = ["pk"]
        constraints = [
            models.UniqueConstraint(fields=["case", "client"], name="unique_case_co_client")
        ]

    def __str__(self):
        return f"{self.client} ({self.case_id})"

    @property
    def role_label(self) -> str:
        labels = dict(PARTY_ROLES.get(self.case.case_type, []))
        return labels.get(self.role, dict(PARTY_ROLE_CHOICES).get(self.role, self.role))


class CaseParty(models.Model):
    case = models.ForeignKey(Case, on_delete=models.CASCADE, related_name="party_links")
    party = models.ForeignKey(Party, on_delete=models.PROTECT, related_name="case_links")
    role = models.CharField(
        "taraf sıfatı", max_length=32, choices=PARTY_ROLE_CHOICES, default=PartyRole.OTHER
    )

    class Meta:
        verbose_name = "dosya tarafı"
        verbose_name_plural = "dosya tarafları"
        constraints = [
            models.UniqueConstraint(fields=["case", "party"], name="unique_case_party"),
        ]

    def __str__(self):
        return f"{self.party} ({self.get_role_display()})"

    def get_role_display(self):
        return dict(PARTY_ROLES.get(self.case.case_type, [])).get(
            self.role, dict(PARTY_ROLE_CHOICES).get(self.role, self.role)
        )


class DocumentCategory(models.TextChoices):
    PETITION = "petition", "Dilekçe"
    DECISION = "decision", "Karar / Ara karar"
    SERVICE = "service", "Tebligat"
    EXPERT = "expert", "Bilirkişi raporu"
    CONTRACT = "contract", "Sözleşme"
    EVIDENCE = "evidence", "Delil"
    CORRESPONDENCE = "correspondence", "Yazışma"
    OTHER = "other", "Diğer"


def document_upload_to(instance, filename):
    name = Path(filename)
    return f"cases/{instance.case_id}/{uuid.uuid4().hex[:8]}_{name.stem[:80]}{name.suffix.lower()}"


class Document(TimeStampedModel):
    case = models.ForeignKey(Case, on_delete=models.CASCADE, related_name="documents")
    title = models.CharField("başlık", max_length=300)
    category = models.CharField(
        "kategori", max_length=20, choices=DocumentCategory.choices, default=DocumentCategory.OTHER
    )
    file = models.FileField("dosya", upload_to=document_upload_to)
    original_name = models.CharField(max_length=300, editable=False)
    size = models.PositiveBigIntegerField(default=0, editable=False)
    notes = models.TextField("notlar", blank=True)
    folder_path = models.CharField("klasördeki kopya", max_length=500, blank=True, editable=False)

    class Meta:
        verbose_name = "belge"
        verbose_name_plural = "belgeler"
        ordering = ["-created_at"]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if self.file and not self.original_name:
            self.original_name = Path(self.file.name).name
        if self.file:
            self.size = self.file.size
        super().save(*args, **kwargs)


class HearingKind(models.TextChoices):
    HEARING = "hearing", "Duruşma"
    PRELIMINARY = "preliminary", "Ön inceleme"
    DISCOVERY = "discovery", "Keşif"
    EXPERT = "expert", "Bilirkişi incelemesi"
    MEDIATION = "mediation", "Arabuluculuk toplantısı"
    OTHER = "other", "Diğer"


class HearingStatus(models.TextChoices):
    PLANNED = "planned", "Planlandı"
    HELD = "held", "Yapıldı"
    POSTPONED = "postponed", "Ertelendi"
    CANCELLED = "cancelled", "İptal"


class Hearing(TimeStampedModel):
    case = models.ForeignKey(Case, on_delete=models.CASCADE, related_name="hearings")
    kind = models.CharField(
        "tür", max_length=20, choices=HearingKind.choices, default=HearingKind.HEARING
    )
    starts_at = models.DateTimeField("tarih ve saat")
    authority = models.CharField("mahkeme / yer", max_length=200, blank=True)
    room = models.CharField("salon", max_length=100, blank=True)
    notes = models.TextField("notlar", blank=True)
    status = models.CharField(
        "durum", max_length=20, choices=HearingStatus.choices, default=HearingStatus.PLANNED
    )
    result = models.TextField("sonuç / ara karar", blank=True)

    class Meta:
        verbose_name = "duruşma"
        verbose_name_plural = "duruşmalar"
        ordering = ["starts_at"]

    def __str__(self):
        return f"{self.get_kind_display()} — {self.starts_at:%d.%m.%Y %H:%M}"


class CaseEvent(models.Model):
    """Dosya zaman çizelgesi."""

    class Kind(models.TextChoices):
        NOTE = "note", "Not"
        HEARING = "hearing", "Duruşma"
        SERVICE = "service", "Tebligat"
        TASK = "task", "Görev"
        DOCUMENT = "document", "Belge"
        STATUS = "status", "Durum"

    case = models.ForeignKey(Case, on_delete=models.CASCADE, related_name="events")
    date = models.DateField("tarih")
    kind = models.CharField("tür", max_length=20, choices=Kind.choices, default=Kind.NOTE)
    title = models.CharField("başlık", max_length=300)
    description = models.TextField("açıklama", blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "zaman çizelgesi kaydı"
        verbose_name_plural = "zaman çizelgesi"
        ordering = ["-date", "-created_at"]

    def __str__(self):
        return self.title


class Seizure(TimeStampedModel):
    case = models.ForeignKey(Case, on_delete=models.CASCADE, related_name="seizures")
    debtor = models.CharField("borçlu", max_length=300)
    asset = models.CharField("önceki mal varlığı bilgisi", max_length=500, blank=True)
    debtor_party = models.ForeignKey(
        Party, on_delete=models.SET_NULL, null=True, blank=True, related_name="seizures"
    )
    debtor_client = models.ForeignKey(
        Client, on_delete=models.SET_NULL, null=True, blank=True, related_name="debtor_seizures"
    )
    kind = models.CharField("haciz türü", max_length=20, choices=seizure_types.KINDS, blank=True)
    state = models.CharField("durum", max_length=32, blank=True)
    employer = models.CharField("işveren / işyeri", max_length=200, blank=True)
    bank_name = models.CharField("banka adı", max_length=200, blank=True)
    plate = models.CharField("plaka", max_length=20, blank=True)
    property_info = models.CharField("taşınmaz bilgisi", max_length=500, blank=True)
    address = models.TextField("adres", blank=True)
    notice_stage = models.CharField(
        "ihbarname", max_length=4, choices=seizure_types.NOTICE_STAGES, blank=True
    )
    recipient = models.CharField("ihbarname muhatabı", max_length=300, blank=True)
    related_case_info = models.CharField(
        "alacaklı olduğu dosya bilgisi", max_length=300, blank=True
    )
    seized_on = models.DateField("haciz tarihi", null=True, blank=True)
    renewal_on = models.DateField("yenileme tarihi", db_index=True, null=True, blank=True)
    is_active = models.BooleanField("haciz takibi aktif", default=True)
    notes = models.TextField("not", blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_seizures"
    )

    class Meta:
        ordering = ["renewal_on", "pk"]
        verbose_name = "haciz takibi"
        verbose_name_plural = "haciz takipleri"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(renewal_on__gte=models.F("seized_on")),
                name="seizure_renewal_after_date",
            ),
            models.CheckConstraint(
                condition=models.Q(debtor_party__isnull=True)
                | models.Q(debtor_client__isnull=True),
                name="seizure_single_debtor",
            ),
        ]

    def __str__(self):
        return f"{self.debtor_display} — {self.asset_label}"

    @property
    def debtor_display(self):
        return str(self.debtor_party or self.debtor_client or self.debtor)

    @property
    def state_label(self):
        return dict(seizure_types.STATES.get(self.kind, [])).get(self.state, "")

    @property
    def details(self):
        return " · ".join(
            str(getattr(self, field) or "")
            for field in seizure_types.DETAIL_FIELDS.get(self.kind, [])
            if getattr(self, field)
        )

    @property
    def asset_label(self):
        if not self.kind:
            return self.asset
        return " · ".join(part for part in (self.get_kind_display(), self.details) if part)

    @property
    def needs_renewal(self):
        return not self.kind or self.state in seizure_types.RENEWAL_STATES

    def clean(self):
        super().clean()
        if self.case_id and self.case.case_type != CaseType.ENFORCEMENT:
            raise ValidationError("Haciz takibi yalnızca icra dosyalarında kullanılabilir.")
        if self.kind:
            errors = {}
            if self.state not in dict(seizure_types.STATES.get(self.kind, [])):
                errors["state"] = "Haciz türüne uygun bir durum seçin."
            if self.debtor_party_id and self.case_id:
                valid_debtor = self.case.party_links.filter(
                    party_id=self.debtor_party_id, role="debtor"
                ).exists()
            elif self.debtor_client_id and self.case_id:
                valid_debtor = (
                    self.case.client_id == self.debtor_client_id
                    and self.case.client_role == "debtor"
                ) or self.case.co_client_links.filter(
                    client_id=self.debtor_client_id, role="debtor"
                ).exists()
            else:
                valid_debtor = False
            if not valid_debtor:
                errors["debtor"] = "Dosyanın taraflarında borçlu olarak kayıtlı birini seçin."
            if self.state in seizure_types.SEIZED_STATES and not self.seized_on:
                errors["seized_on"] = "Haciz tarihini girin."
            if self.kind == "bank" and not self.bank_name.strip():
                errors["bank_name"] = "Her banka için ayrı kayıt açıp banka adını girin."
            if self.kind == "vehicle" and self.state != "vehicle_none" and not self.plate.strip():
                errors["plate"] = "Her araç için ayrı kayıt açıp tek plaka girin."
            if (
                self.kind == "property"
                and self.state != "property_none"
                and not self.property_info.strip()
            ):
                errors["property_info"] = "Taşınmaz bilgisini girin."
            if self.kind == "location" and not self.address.strip():
                errors["address"] = "Gidilen adresi girin."
            if self.kind == "notice" and self.notice_stage not in dict(seizure_types.NOTICE_STAGES):
                errors["notice_stage"] = "89/1, 89/2 veya 89/3 seçin."
            if (
                self.kind == "claim"
                and self.state == "claim_exists"
                and not self.related_case_info.strip()
            ):
                errors["related_case_info"] = (
                    "Alacaklı olunan dosyanın kurum ve numara bilgisini girin."
                )
            if (
                self.kind in {"vehicle", "property"}
                and self.state in seizure_types.RENEWAL_STATES
                and not self.renewal_on
            ):
                errors["renewal_on"] = "Yenileme tarihini girin."
            if self.renewal_on and not self.seized_on:
                errors["seized_on"] = "Yenileme için haciz tarihini de girin."
            if errors:
                raise ValidationError(errors)
        if self.seized_on and self.renewal_on and self.renewal_on < self.seized_on:
            raise ValidationError({"renewal_on": "Yenileme tarihi haciz tarihinden önce olamaz."})


class SeizureRenewal(TimeStampedModel):
    seizure = models.ForeignKey(Seizure, on_delete=models.CASCADE, related_name="renewals")
    due_date = models.DateField("yenileme tarihi")
    task = models.OneToOneField(
        "tasks.Task",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="seizure_renewal",
    )

    class Meta:
        verbose_name = "haciz yenileme görevi"
        verbose_name_plural = "haciz yenileme görevleri"
        constraints = [
            models.UniqueConstraint(fields=["seizure", "due_date"], name="unique_seizure_renewal")
        ]
