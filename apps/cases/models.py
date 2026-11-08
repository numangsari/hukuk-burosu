import re
import uuid
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.functions import Coalesce, TruncDate
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
    SALES_OFFICE = "sales_office", "Satış Memurluğu"
    INVESTIGATION = "investigation", "Soruşturma"
    CONSULTANCY = "consultancy", "Sözleşme"
    MEDIATION = "mediation", "Arabuluculuk"
    NOTICE = "notice", "İhtarname"
    OTHER = "other", "Diğer"


LITIGATION_TYPES = {CaseType.CIVIL, CaseType.CRIMINAL, CaseType.ADMINISTRATIVE}

# UYAP'ta karşılığı olmayan dosya türleri: UYAP bölümleri (taraf, muhasebe) gösterilmez.
NO_PORTAL_TYPES = {CaseType.CONSULTANCY, CaseType.NOTICE, CaseType.OTHER}

# Türe göre form etiketleri. Boş değer alanın o türde gizleneceğini belirtir.
TYPE_LABELS = {
    kind: {
        "official_no": ""
        if kind in {CaseType.CONSULTANCY, CaseType.OTHER}
        else ("Tarih ve Yevmiye No" if kind == CaseType.NOTICE else "Dosya Numarası"),
        "authority": "" if kind in {CaseType.CONSULTANCY, CaseType.OTHER} else "Kurum Adı",
        "subject": "Konu",
        "value": "",
    }
    for kind in CaseType
}


class NumberKind(models.TextChoices):
    """Esas türündeki dosyalarda numaranın türü; varsayılan Esas."""

    ESAS = "esas", "Esas"
    MISC = "d_is", "D.İş"
    COMMISSION = "talimat", "Talimat"


NUMBER_KIND_TYPES = {CaseType.CIVIL, CaseType.CRIMINAL, CaseType.ADMINISTRATIVE}


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


class ArchiveCategory(TimeStampedModel):
    name = models.CharField("tür adı", max_length=320, unique=True)
    tracks_state = models.BooleanField("açık / kapalı ayrımı", default=True)
    default_for_case_types = models.JSONField("varsayılan dosya türleri", default=list, blank=True)
    client = models.OneToOneField(
        Client,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="physical_archive_category",
        verbose_name="özel müvekkil",
    )

    class Meta:
        verbose_name = "fiziki klasör türü"
        verbose_name_plural = "fiziki klasör türleri"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                models.functions.Lower("name"), name="archive_category_name_ci_unique"
            )
        ]

    def __str__(self):
        return self.name


class ArchiveFolder(TimeStampedModel):
    class Kind(models.TextChoices):
        OPEN = "open", "Açık"
        CLOSED = "closed", "Kapalı"
        ENFORCEMENT = "enforcement", "İcra"
        PROXY = "proxy", "Vekaletnameler"
        NOTICE = "notice", "İhtarnameler"
        MEDIATION = "mediation", "Arabuluculuklar"
        CONTRACT = "contract", "Sözleşmeler"
        FEE_CONTRACT = "fee_contract", "Avukatlık Ücret Sözleşmeleri"
        OTHER = "other", "Diğer"
        CATEGORY = "category", "Türlü klasör"
        LEGACY = "legacy", "Eski kayıt"

    class PhysicalState(models.TextChoices):
        OPEN = "open", "Açık"
        CLOSED = "closed", "Kapalı"
        SINGLE = "single", "Ayrımsız"

    name = models.CharField("klasör adı", max_length=340, unique=True)
    kind = models.CharField("tür", max_length=12, choices=Kind.choices)
    custom_kind = models.CharField("diğer tür adı", max_length=30, blank=True)
    capacity = models.PositiveSmallIntegerField("kapasite", null=True, blank=True)
    category = models.ForeignKey(
        ArchiveCategory,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="folders",
        verbose_name="tür",
    )
    physical_state = models.CharField(
        "fiziki durum", max_length=6, choices=PhysicalState.choices, blank=True
    )
    number = models.PositiveIntegerField("klasör numarası", null=True, blank=True)
    is_active = models.BooleanField("yeni yerleşime açık", default=True)

    class Meta:
        verbose_name = "fiziki klasör"
        verbose_name_plural = "fiziki klasörler"
        constraints = [
            models.UniqueConstraint(
                models.functions.Lower("name"), name="archive_folder_name_ci_unique"
            ),
            models.UniqueConstraint(
                fields=["category", "physical_state", "number"],
                name="archive_category_state_number_unique",
            ),
        ]
        ordering = ["name"]

    def __str__(self):
        return self.name


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
        Client,
        verbose_name="müvekkil",
        on_delete=models.PROTECT,
        related_name="cases",
        null=True,
        blank=True,
    )
    case_type = models.CharField("dosya türü", max_length=20, choices=CaseType.choices)
    client_role = models.CharField(
        "müvekkilin sıfatı", max_length=32, choices=PARTY_ROLE_CHOICES, blank=True
    )
    archive_folder = models.ForeignKey(
        ArchiveFolder,
        verbose_name="fiziki klasör",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="cases",
    )
    archive_folder_no = models.CharField("klasör no", max_length=340, blank=True)
    archive_no = models.CharField("dosya no", max_length=50, blank=True)
    archive_needs_review = models.BooleanField("fiziki arşiv yeri incelenecek", default=False)
    official_no = models.CharField("dosya numarası", max_length=100, blank=True)
    # İhtarnamede noterin düzenleme tarihi (numara yalnızca yevmiye numarasıdır).
    official_date = models.DateField("ihtarname tarihi", null=True, blank=True)
    # İhtarnamede tebligat bilgisi: tebligat numarası, tebliğ edilip edilmediği ve tebliğ tarihi.
    notice_service_no = models.CharField("tebligat no", max_length=50, blank=True)
    notice_served = models.BooleanField("tebliğ edildi", default=False)
    notice_served_on = models.DateField("tebliğ tarihi", null=True, blank=True)
    official_no_kind = models.CharField(
        "numara türü", max_length=10, choices=NumberKind.choices, default=NumberKind.ESAS
    )
    authority = models.CharField("kurum adı", max_length=200, blank=True)
    subject = models.CharField("konu", max_length=300, blank=True)
    uyap_stage = models.CharField("UYAP aşama", max_length=200, blank=True)
    uyap_subject = models.CharField("UYAP dava konusu", max_length=500, blank=True)
    next_hearing_at = models.CharField("sıradaki duruşma tarihi", max_length=100, blank=True)
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
    enforcement_basis = models.TextField("takibin dayanağı", blank=True)
    enforcement_amount = models.DecimalField(
        "takipte kesinleşen miktar", max_digits=16, decimal_places=2, null=True, blank=True
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
        verbose_name="yardımcı sorumlu",
        on_delete=models.PROTECT,
        related_name="cases_as_intern",
        limit_choices_to=intern_choices,
        null=True,
        blank=True,
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
        return {
            cid for cid in (self.client_id, *self.co_clients.values_list("pk", flat=True)) if cid
        }

    @property
    def all_clients(self) -> list:
        return [c for c in [self.client, *self.co_clients.all()] if c]

    @property
    def missing_fields(self) -> list[str]:
        """Dosyada kullanıcının tamamlaması gereken eksik zorunlu alanlar."""
        missing = []
        if not self.client_id:
            missing.append("Müvekkil")
        if not self.client_role:
            missing.append("Müvekkilin sıfatı")
        if not self.archive_folder_no or not self.archive_no:
            missing.append("Fiziki arşiv no")
        if not self.subject:
            missing.append("Konu")
        return missing

    @property
    def uyap_status_banner(self) -> str:
        """Açık/kapalı durumu ile UYAP aşama/kapanış bilgisini bir arada döndürür."""
        stage = (self.uyap_stage or "").strip()
        if self.is_open:
            if stage and stage.lower() not in {"açık", "acik"}:
                return f"AÇIK: {stage}"
            return "AÇIK: Açık" if stage else "AÇIK"
        parts = []
        if self.closed_on:
            parts.append(self.closed_on.strftime("%d.%m.%Y"))
        reason = self.closing_label
        if stage and not stage.lower().startswith("kapalı") and stage.lower() != "kapali":
            reason = stage
        elif stage:
            match = re.search(r"Kapalı\s*\(([^0-9\)]+)\)", stage, re.I)
            if match:
                reason = match.group(1).strip()
        if reason:
            parts.append(reason)
        return f"KAPALI: {' · '.join(parts)}" if parts else "KAPALI"

    @property
    def official_no_display(self) -> str:
        """Dosya numarası; türüne göre sonuna Esas / İcra / Soruşturma / Arabuluculuk eklenir."""
        if self.case_type == CaseType.NOTICE:
            # İhtarnamede numara yalnızca noterin yevmiye numarasıdır.
            number = (
                f"{self.official_no} Yevmiye" if self.official_no.isdigit() else self.official_no
            )
            date = self.official_date.strftime("%d.%m.%Y") if self.official_date else ""
            return " / ".join(part for part in (date, number) if part)
        suffix = NUMBER_SUFFIX.get(self.case_type, "")
        if self.case_type in NUMBER_KIND_TYPES and self.official_no_kind in (
            NumberKind.MISC,
            NumberKind.COMMISSION,
        ):
            suffix = NumberKind(self.official_no_kind).label
        return _with_suffix(self.official_no, suffix)

    @property
    def decision_no_display(self) -> str:
        return _with_suffix(self.decision_no, "Karar")

    @property
    def display_name(self):
        if self.case_type in {CaseType.CONSULTANCY, CaseType.OTHER}:
            return self.subject or self.uyap_subject or "Dosya"
        return (
            " - ".join(part for part in (self.authority, self.official_no_display) if part)
            or self.subject
            or self.uyap_subject
            or "Dosya"
        )

    def __str__(self):
        return self.display_name

    def get_absolute_url(self):
        return reverse("cases:detail", args=[self.pk])

    def save(self, *args, **kwargs):
        preserve_unknown_stage = kwargs.pop("preserve_unknown_stage", False)
        if self.pk and not self.stage:
            preserve_unknown_stage = (
                not type(self).objects.filter(pk=self.pk).exclude(stage="").exists()
            )
        self.authority = tr_upper(self.authority).strip()
        self.subject = tr_upper(self.subject).strip()  # dosya adları büyük harf
        if (
            not preserve_unknown_stage
            and self.status == CaseStatus.OPEN
            and self.stage not in dict(stages.open_stages(self.case_type))
        ):
            self.stage = stages.default_stage(self.case_type)

        # Fiziki klasör ForeignKey ve metin senkronizasyonu
        if self.pk:
            old_vals = (
                type(self)
                .objects.filter(pk=self.pk)
                .values("archive_folder_id", "archive_folder_no")
                .first()
            )
            if old_vals:
                old_folder_id = old_vals["archive_folder_id"]
                old_folder_no = old_vals["archive_folder_no"]

                if self.archive_folder_id != old_folder_id:
                    self.archive_folder_no = self.archive_folder.name if self.archive_folder else ""
                elif self.archive_folder_no != old_folder_no:
                    if self.archive_folder_no:
                        self.archive_folder = ArchiveFolder.objects.filter(
                            name__iexact=self.archive_folder_no
                        ).first()
                    else:
                        self.archive_folder = None
                elif self.archive_folder_no and not self.archive_folder_id:
                    self.archive_folder = ArchiveFolder.objects.filter(
                        name__iexact=self.archive_folder_no
                    ).first()
            else:
                if self.archive_folder_id:
                    self.archive_folder_no = self.archive_folder.name
                elif self.archive_folder_no:
                    self.archive_folder = ArchiveFolder.objects.filter(
                        name__iexact=self.archive_folder_no
                    ).first()
        else:
            if self.archive_folder_id:
                self.archive_folder_no = self.archive_folder.name
            elif self.archive_folder_no:
                self.archive_folder = ArchiveFolder.objects.filter(
                    name__iexact=self.archive_folder_no
                ).first()

        # update_fields belirtilmişse fiziki klasör alanları senkronize kaydedilsin
        if "update_fields" in kwargs and kwargs["update_fields"] is not None:
            uf = set(kwargs["update_fields"])
            if "archive_folder" in uf or "archive_folder_no" in uf:
                uf.add("archive_folder")
                uf.add("archive_folder_no")
                kwargs["update_fields"] = list(uf)

        super().save(*args, **kwargs)

    @property
    def labels(self) -> dict:
        return TYPE_LABELS[CaseType(self.case_type)]

    @property
    def has_portal(self) -> bool:
        """Dosya türü UYAP'ta izlenebilir mi (sözleşme, ihtarname ve diğer değil)."""
        return self.case_type not in NO_PORTAL_TYPES

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
    from_uyap = models.BooleanField("UYAP kaydı", default=False)

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


class DocumentSource(models.TextChoices):
    OFFICE = "office", "Büro belgesi"
    UYAP = "uyap", "UYAP evrakı"


def document_upload_to(instance, filename):
    name = Path(filename)
    return f"cases/{instance.case_id}/{uuid.uuid4().hex[:8]}_{name.stem[:80]}{name.suffix.lower()}"


class DocumentQuerySet(models.QuerySet):
    def office(self):
        return self.filter(source="office")

    def uyap(self):
        return self.filter(source="uyap")

    def chronological(self):
        """Belge tarihine (UYAP evrakında UYAP tarihi, yoksa yüklenme günü) göre yeniden eskiye."""
        return self.annotate(
            sort_date=Coalesce(
                "document_date", TruncDate("created_at"), output_field=models.DateField()
            )
        ).order_by("-sort_date", "-created_at")


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
    document_date = models.DateField("belge tarihi", null=True, blank=True)
    source = models.CharField(
        "kaynak", max_length=10, choices=DocumentSource.choices, default=DocumentSource.OFFICE
    )
    uyap_type = models.CharField("UYAP evrak türü", max_length=120, blank=True, editable=False)

    objects = DocumentQuerySet.as_manager()

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
    CLIENT_MEETING = "client_meeting", "Müvekkil görüşmesi"
    CLIENT_MEETING_OFFSITE = "client_offsite", "Müvekkil görüşmesi (ofis dışı)"
    OFFICE_MEETING = "office_meeting", "Ofis içi toplantı"
    OTHER = "other", "Diğer"


class HearingStatus(models.TextChoices):
    PLANNED = "planned", "Planlandı"
    HELD = "held", "Yapıldı"
    POSTPONED = "postponed", "Ertelendi"
    CANCELLED = "cancelled", "İptal"


class HearingInformMethod(models.TextChoices):
    WHATSAPP = "whatsapp", "WhatsApp"
    OTHER = "other", "Başka yolla"


# Duruşma listesinde yalnızca bu türler görünür; sonuç ve müvekkil bilgilendirme de yalnızca
# bunlarda beklenir. Diğer türler (toplantı, görüşme, bilirkişi vb.) takvimde etkinlik olarak kalır.
RESULT_KINDS = ("hearing", "preliminary", "discovery")
LIST_KINDS = RESULT_KINDS


class Hearing(TimeStampedModel):
    case = models.ForeignKey(
        Case, on_delete=models.CASCADE, related_name="hearings", null=True, blank=True
    )
    client = models.ForeignKey(
        "clients.Client",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="hearings",
        verbose_name="müvekkil",
    )
    title = models.CharField("etkinlik başlığı", max_length=255, blank=True)
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="görevli / sorumlu",
    )
    kind = models.CharField(
        "tür", max_length=20, choices=HearingKind.choices, default=HearingKind.HEARING
    )
    starts_at = models.DateTimeField("tarih ve saat")
    ends_at = models.DateTimeField("bitiş tarihi ve saat", null=True, blank=True)
    authority = models.CharField("mahkeme / yer", max_length=200, blank=True)
    notes = models.TextField("notlar", blank=True)
    status = models.CharField(
        "durum", max_length=20, choices=HearingStatus.choices, default=HearingStatus.PLANNED
    )
    result = models.TextField("sonuç / ara karar", blank=True)
    decisions = models.TextField("duruşmada verilen kararlar", blank=True)
    excuse_submitted = models.BooleanField("mazeret gönderildi", default=False)
    is_remote = models.BooleanField("e-duruşma", default=False)
    client_informed = models.BooleanField("müvekkile bilgi verildi", null=True, blank=True)
    client_not_informed_reason = models.TextField("müvekkile bilgi verilmeme sebebi", blank=True)
    # Müvekkil bilgilendirme kaydı: WhatsApp açılınca veya başka yolla bildirilince işaretlenir.
    client_informed_at = models.DateTimeField(
        "müvekkil bilgilendirme zamanı", null=True, blank=True
    )
    client_informed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="bilgilendiren",
    )
    inform_method = models.CharField(
        "bilgilendirme yolu", max_length=20, blank=True, choices=HearingInformMethod.choices
    )
    portal_ref = models.CharField(
        "UYAP duruşma referansı", max_length=100, blank=True, db_index=True
    )
    google_event_id = models.CharField(
        "Google Takvim etkinlik ID", max_length=255, blank=True, db_index=True
    )
    # Son Google Takvim eşitlemesi başarısızsa işaretlenir; `retry_google_sync` yeniden dener.
    google_sync_pending = models.BooleanField(
        "Google Takvim eşitlemesi bekliyor", default=False, db_index=True
    )

    class Meta:
        verbose_name = "duruşma / etkinlik"
        verbose_name_plural = "duruşmalar ve etkinlikler"
        ordering = ["starts_at"]

    def __str__(self):
        return f"{self.title_display} — {self.starts_at:%d.%m.%Y %H:%M}"

    @property
    def attendance(self) -> str:
        """Katılma durumu: mazeret, e-duruşma veya katılınacak (iki işaretin tek seçimi)."""
        if self.excuse_submitted:
            return "excuse"
        return "remote" if self.is_remote else "attend"

    @property
    def attendance_label(self) -> str:
        return {"excuse": "Mazeret", "remote": "E-duruşma", "attend": "Katılınacak"}[
            self.attendance
        ]

    @property
    def is_done(self) -> bool:
        """İçinde bulunulan gün dahil geçmiş duruşmalar yapılmış sayılır (saatten bağımsız)."""
        return timezone.localtime(self.starts_at).date() <= timezone.localdate()

    @property
    def uses_result_flow(self) -> bool:
        """Yalnızca duruşma, ön inceleme ve keşifte sonuç ve müvekkil bilgilendirme akışı vardır."""
        return self.kind in RESULT_KINDS

    @property
    def needs_result(self) -> bool:
        return self.uses_result_flow and self.status != HearingStatus.CANCELLED

    @property
    def result_missing(self) -> bool:
        return self.is_done and self.needs_result and not self.result.strip()

    @property
    def inform_missing(self) -> bool:
        """Müvekkili olan, yapılmış duruşmada bilgilendirme yapılmadıysa uyarı verilir."""
        return (
            self.is_done
            and self.needs_result
            and bool(self.effective_client)
            and not self.client_informed_at
            and not self.client_informed
        )

    @property
    def needs_attention(self) -> bool:
        return self.result_missing or self.inform_missing

    @property
    def title_display(self):
        if self.title:
            return self.title
        if self.case:
            return self.case.display_name
        if self.client:
            return f"{self.get_kind_display()} — {self.client}"
        return self.get_kind_display()

    @property
    def effective_client(self):
        return self.client or (self.case.client if self.case else None)

    @property
    def client_phone(self) -> str:
        client = self.effective_client
        return client.primary_phone if client else ""

    @property
    def client_whatsapp_phone(self) -> str:
        client = self.effective_client
        return client.whatsapp_phone if client else ""


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
