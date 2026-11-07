from django.conf import settings
from django.db import models


class ImportBatch(models.Model):
    """Tamamlanan her aktarım. Aynı Excel dosyasının ikinci kez aktarılmasını engeller."""

    file_sha256 = models.CharField(max_length=64, unique=True)
    file_name = models.CharField(max_length=200, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    counts = models.JSONField(default=dict)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "veri aktarımı"
        verbose_name_plural = "veri aktarımları"

    def __str__(self):
        return f"{self.file_name} ({self.created_at:%d.%m.%Y})"


class PowerOfAttorneyReview(models.Model):
    """Vekalet listesindeki kullanıcının işlediği satırın kaynağı."""

    source_sha256 = models.CharField(max_length=64)
    source_row = models.PositiveIntegerField()
    source_reference = models.TextField("kaynak vekalet numarası", blank=True)
    source_note = models.TextField("kaynak notu", blank=True)
    automatic = models.BooleanField("otomatik öneriyle aktarıldı", default=False)
    expected_clients = models.PositiveIntegerField("satırdaki müvekkil sayısı", default=1)
    client = models.ForeignKey(
        "clients.Client", on_delete=models.SET_NULL, null=True, related_name="imported_poa_rows"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+", null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "vekalet listesi incelemesi"
        verbose_name_plural = "vekalet listesi incelemeleri"
        constraints = [
            models.UniqueConstraint(
                fields=["source_sha256", "source_row"], name="unique_poa_review_source_row"
            )
        ]

    def __str__(self):
        return f"Vekalet listesi satır {self.source_row}"


class PowerOfAttorneyReviewMember(models.Model):
    """Aynı vekalet satırındaki diğer müvekkiller."""

    review = models.ForeignKey(
        PowerOfAttorneyReview, on_delete=models.CASCADE, related_name="members"
    )
    client = models.ForeignKey(
        "clients.Client", on_delete=models.SET_NULL, null=True, related_name="imported_poa_members"
    )

    class Meta:
        verbose_name = "vekalet listesi ek müvekkili"
        verbose_name_plural = "vekalet listesi ek müvekkilleri"
        constraints = [
            models.UniqueConstraint(fields=["review", "client"], name="unique_poa_review_member")
        ]

    def __str__(self):
        return f"Vekalet listesi satır {self.review.source_row} ek müvekkili"


class OfficeSourceRecord(models.Model):
    """Arşiv ve icra listesindeki bir satırın aktarım durumu."""

    source_sha256 = models.CharField(max_length=64)
    source_name = models.CharField(max_length=200)
    sheet = models.CharField(max_length=100)
    row_number = models.PositiveIntegerField()
    values = models.JSONField(default=dict)
    reason = models.CharField(max_length=300, blank=True)
    skipped = models.BooleanField("atlandı", default=False)
    case = models.ForeignKey(
        "cases.Case",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="office_sources",
    )

    class Meta:
        ordering = ["source_name", "sheet", "row_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["source_sha256", "sheet", "row_number"], name="unique_office_source_row"
            )
        ]
        verbose_name = "ofis listesi satırı"
        verbose_name_plural = "ofis listesi satırları"

    def __str__(self):
        return f"{self.source_name} — {self.sheet} satır {self.row_number}"


class PortalCapture(models.Model):
    """Deneme ortamında incelenen yanıtlardan güvenli alanlar."""

    fingerprint = models.CharField(max_length=64, unique=True)
    source_users = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name="+", blank=True)
    source_unknown = models.BooleanField(default=True)

    source = models.CharField(max_length=20)
    path = models.CharField(max_length=200)
    captured_at = models.DateTimeField(null=True, blank=True)
    data = models.JSONField()

    class Meta:
        verbose_name = "portal yanıtı"
        verbose_name_plural = "portal yanıtları"

    def __str__(self):
        return f"{self.source}: {self.path}"


class PortalCase(models.Model):
    """Kaynak dosyayı, varsa sisteme açılan dosyayla birlikte izler."""

    fingerprint = models.CharField(max_length=64, unique=True)
    source_users = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name="+", blank=True)
    source_unknown = models.BooleanField(default=True)

    authority = models.CharField(max_length=200)
    number = models.CharField(max_length=100)
    category = models.CharField(max_length=40, blank=True)
    status = models.CharField(max_length=200, blank=True)
    data = models.JSONField(default=dict)
    case = models.OneToOneField("cases.Case", on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        ordering = ["authority", "number"]
        verbose_name = "portal dosyası"
        verbose_name_plural = "portal dosyaları"

    def __str__(self):
        return f"{self.authority} {self.number}"


class PortalDocument(models.Model):
    """UYAP'tan alınmış bir dosya evrakı. Aynı evrak ikinci kez alınmaz; kullanıcı belgeyi
    dosyadan silse bile yeniden indirilmez."""

    portal_case = models.ForeignKey(PortalCase, on_delete=models.CASCADE, related_name="documents")
    evrak_id = models.CharField(max_length=64)
    content_hash = models.CharField(max_length=64)
    document = models.OneToOneField(
        "cases.Document", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "UYAP evrakı"
        verbose_name_plural = "UYAP evrakları"
        constraints = [
            models.UniqueConstraint(fields=["portal_case", "evrak_id"], name="uyap_evrak_tekil")
        ]

    def __str__(self):
        return f"UYAP evrakı {self.evrak_id}"


class PortalNotice(models.Model):
    fingerprint = models.CharField(max_length=64, unique=True)
    source_users = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name="+", blank=True)
    source_unknown = models.BooleanField(default=True)

    sender = models.CharField(max_length=300, blank=True)
    subject = models.TextField(blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    read = models.BooleanField(default=False)
    data = models.JSONField(default=dict)
    resolution_client = models.ForeignKey(
        "clients.Client",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="portal_notices",
    )
    resolution_case = models.ForeignKey(
        "cases.Case", null=True, blank=True, on_delete=models.PROTECT, related_name="portal_notices"
    )
    resolution_task = models.OneToOneField(
        "tasks.Task", null=True, blank=True, on_delete=models.PROTECT, related_name="portal_notice"
    )
    no_task_reason = models.TextField(blank=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="resolved_notices",
    )
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-delivered_at"]
        verbose_name = "portal tebligatı"
        verbose_name_plural = "portal tebligatları"

    def __str__(self):
        return self.subject or self.sender


class PortalNoticeDocument(models.Model):
    """Tebligatla ilişkilendirilmiş kaynak belgenin bir sürümü."""

    notice = models.ForeignKey(PortalNotice, on_delete=models.PROTECT, related_name="documents")
    source_part = models.CharField(max_length=256)
    content_hash = models.CharField(max_length=64)
    file = models.FileField(upload_to="portal_notices/%Y/%m")
    original_name = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["notice", "source_part", "content_hash"],
                name="unique_portal_notice_document",
            )
        ]
        verbose_name = "tebligat belgesi"
        verbose_name_plural = "tebligat belgeleri"

    def __str__(self):
        return self.original_name


class PortalConnection(models.Model):
    """Deneme eklentisinin yerel sunucuyla bağlantısı."""

    key_hash = models.CharField(max_length=64, unique=True)
    owner = models.ForeignKey("accounts.User", on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    active = models.BooleanField(default=True)
    last_seen = models.DateTimeField(null=True, blank=True)
    uyap_status = models.CharField(max_length=30, blank=True)
    uets_status = models.CharField(max_length=30, blank=True)
    uyap_attempt_at = models.DateTimeField(null=True, blank=True)
    uets_attempt_at = models.DateTimeField(null=True, blank=True)
    uyap_success_at = models.DateTimeField(null=True, blank=True)
    uets_success_at = models.DateTimeField(null=True, blank=True)
    # Eklentinin oturum yoklaması: oturum açık mı (None: bilgi yok) ve ne zaman yoklandı.
    uyap_session_ok = models.BooleanField(null=True, blank=True)
    uyap_session_at = models.DateTimeField(null=True, blank=True)
    uets_session_ok = models.BooleanField(null=True, blank=True)
    uets_session_at = models.DateTimeField(null=True, blank=True)
    # O an tarayıcıda açık olan hesabın bağlı olduğu izinli avukat (eşleşmezse boş).
    uyap_account = models.ForeignKey(
        "PortalLawyerAccess", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    uets_account = models.ForeignKey(
        "PortalLawyerAccess", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        verbose_name = "portal bağlantısı"
        verbose_name_plural = "portal bağlantıları"

    def __str__(self):
        return f"Portal bağlantısı {self.pk}"


class PortalLawyerAccess(models.Model):
    """Yönetici tarafından belirlenen portal izinleri."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="portal_access",
        verbose_name="büro kullanıcısı",
    )
    identity_number = models.CharField("TC kimlik numarası", max_length=11, unique=True)
    uyap_enabled = models.BooleanField("UYAP verilerini al", default=False)
    uets_enabled = models.BooleanField("UETS verilerini al", default=False)

    class Meta:
        verbose_name = "portal kişi izni"
        verbose_name_plural = "portal kişi izinleri"

    def __str__(self):
        return str(self.user)
