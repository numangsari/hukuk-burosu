import contextvars
import copy
import datetime

from django.db import models
from django.utils import timezone

from apps.core.text import tr_capitalize_words

# İstek başına ayar önbelleği. Yalnızca `RequestSettingsCacheMiddleware` açar;
# istek dışında (komut, görev) boştur.
request_cache = contextvars.ContextVar("office_settings_request_cache", default=None)


class OfficeSettings(models.Model):
    """Tek satırlık ofis ayarları tablosu (singleton, pk=1)."""

    class CaseVisibilityMode(models.TextChoices):
        PUBLIC = (
            "public",
            "Herkese açık — Tüm aktif kullanıcılar tüm müvekkil ve dosyaları görebilir",
        )
        RESTRICTED = (
            "restricted",
            "Sorumlu bazlı — Yönetici, Kıdemli Avukat ve Büro Geneli (Sekreter/Muhasebe) tümünü; "
            "Avukat, Stajyer ve Katip yalnızca sorumlu/görevli olduğu kayıtları görür",
        )

    class TaskReviewMode(models.TextChoices):
        REQUIRED = "required", "Her zaman kontrolcü onayı zorunlu"
        ASSISTANTS_ONLY = (
            "assistants_only",
            "Yalnızca yardımcı personel için kontrolcü onayı zorunlu "
            "(Avukatlar doğrudan kapatabilir)",
        )
        OPTIONAL = (
            "optional",
            "Kontrolcü onayı isteğe bağlı "
            "(Boş bırakılırsa doğrudan kapanır, seçilirse onaya gider)",
        )

    class AccountingEditMode(models.TextChoices):
        EVERYONE = "everyone", "Herkes muhasebe kaydı ekleyebilir ve iptal edebilir"
        RESTRICTED = (
            "restricted",
            "Yalnızca Yönetici, Muhasebe ve seçilen kişiler muhasebe kaydı "
            "ekleyebilir / iptal edebilir",
        )

    name = models.CharField("ofis adı", max_length=200, default="Hukuk Bürosu")
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
    google_calendar_api_enabled = models.BooleanField(
        "Google Takvim API aktif",
        default=False,
        help_text="Açık olduğunda duruşma ve toplantılar Google Takvim'e otomatik yazılır.",
    )
    google_calendar_id = models.CharField(
        "Google Takvim ID",
        max_length=255,
        blank=True,
        help_text="Duruşmaların yazılacağı takvim (örn: primary veya takvim e-posta adresi).",
    )
    google_service_account_json = models.TextField(
        "Google Service Account JSON anahtarı",
        blank=True,
        help_text="Google Cloud Service Account JSON içeriği. Güvenli şekilde saklanır.",
    )
    GOOGLE_COLOR_CHOICES = [
        ("9", "Mavi (Yaban Mersini) — Varsayılan"),
        ("7", "Açık Mavi (Tavuskuşu)"),
        ("1", "Lavanta"),
        ("2", "Yeşil (Adaçayı)"),
        ("10", "Koyu Yeşil (Fesleğen)"),
        ("5", "Sarı (Muz)"),
        ("6", "Turuncu (Mandalina)"),
        ("11", "Kırmızı (Domates)"),
        ("4", "Pembe (Flamingo)"),
        ("3", "Mor (Üzüm)"),
        ("8", "Gri (Grafit)"),
    ]
    google_calendar_event_color = models.CharField(
        "Google Takvim genel varsayılan rengi",
        max_length=10,
        default="9",
        choices=GOOGLE_COLOR_CHOICES,
        help_text="Google Takvim'e aktarılan etkinliklerin genel rengi.",
    )
    google_color_hearing = models.CharField(
        "Duruşma / Ön İnceleme rengi",
        max_length=10,
        default="9",
        choices=GOOGLE_COLOR_CHOICES,
    )
    google_color_discovery = models.CharField(
        "Keşif rengi",
        max_length=10,
        default="2",
        choices=GOOGLE_COLOR_CHOICES,
    )
    google_color_meeting = models.CharField(
        "Müvekkil Görüşmesi / Toplantı rengi",
        max_length=10,
        default="5",
        choices=GOOGLE_COLOR_CHOICES,
    )
    google_color_mediation = models.CharField(
        "Arabuluculuk rengi",
        max_length=10,
        default="11",
        choices=GOOGLE_COLOR_CHOICES,
    )
    google_color_other = models.CharField(
        "Bilirkişi / Diğer rengi",
        max_length=10,
        default="8",
        choices=GOOGLE_COLOR_CHOICES,
    )
    documents_root = models.CharField(
        "ofis klasörü",
        max_length=500,
        blank=True,
        help_text=r"Sunucu PC'de belgelerin kopyalanacağı kök klasör, ör. D:\Hukuk Belgeleri",
    )
    idle_minutes = models.PositiveSmallIntegerField(
        "boşta kalınca oturumu kapat (dakika)",
        default=30,
        help_text="Bu süre işlem yapılmayan bilgisayarda oturum kapanır. 0 = kapalı.",
    )
    upcoming_days = models.PositiveSmallIntegerField("yaklaşan tarih penceresi (gün)", default=7)
    backup_time = models.TimeField("yedek saati", default=datetime.time(12, 30))
    backup_dir = models.CharField("yedek hedef klasörü", max_length=500, blank=True)
    use_assistant_assignee = models.BooleanField(
        "yardımcı sorumlu (stajyer / katip) kullan",
        default=True,
        help_text=(
            "Açık olduğunda müvekkil ve dosyalarda yardımcı sorumlu seçimi zorunlu olur; "
            "kapalı olduğunda yardımcı sorumlu alanı gizlenir."
        ),
    )
    case_visibility_mode = models.CharField(
        "dosya ve müvekkil görünürlüğü",
        max_length=20,
        choices=CaseVisibilityMode.choices,
        default=CaseVisibilityMode.PUBLIC,
    )
    task_review_mode = models.CharField(
        "görevlerde kontrolcü onayı",
        max_length=20,
        choices=TaskReviewMode.choices,
        default=TaskReviewMode.REQUIRED,
    )
    accounting_edit_mode = models.CharField(
        "muhasebe kaydı ekleme / iptal etme yetkisi",
        max_length=20,
        choices=AccountingEditMode.choices,
        default=AccountingEditMode.EVERYONE,
    )
    # Rol bazlı yetki matrisi: {yetki anahtarı: [roller]}. Kaydı olmayan yetki için
    # `apps/core/permission_registry.py` içindeki varsayılan geçerlidir. Yukarıdaki üç eski mod
    # alanı (görünürlük, kontrolcü onayı, muhasebe) yalnızca ilk geçişte matrise taşındı.
    role_permissions = models.JSONField("rol yetkileri", default=dict, blank=True)
    # Kurulum tarihi: UYAP eklentisi yalnızca bu tarihten sonraki duruşmaları aktarır.
    installed_on = models.DateField("kurulum tarihi", default=timezone.localdate)
    notice_default_due_days = models.PositiveSmallIntegerField(
        "UETS tebligat varsayılan görev süresi (gün)",
        default=14,
        help_text=(
            "UETS tebligatlarından görev oluştururken veya süre rozeti hesaplanırken "
            "tebliğ tarihine eklenecek varsayılan gün sayısı (ör. 7, 14, 15)."
        ),
    )
    archive_folder_default_capacity = models.PositiveSmallIntegerField(
        "varsayılan fiziki klasör kapasitesi",
        default=8,
        help_text="Yeni klasörlerde önerilen dosya sayısı; klasör oluşturulurken değiştirilebilir.",
    )
    use_task_points = models.BooleanField(
        "personel görev puanı sistemini kullan",
        default=True,
        help_text=(
            "Açık olduğunda görev türlerinde puanlar tanımlanır, kapatılan görevlerden puan "
            "kazanılır ve Ayarlar > Personel puanları ekranı görünür."
        ),
    )

    allowed_hosts = models.TextField(
        "ek erişim adresleri",
        blank=True,
        help_text=(
            "Sunucuya tarayıcıdan girilebilecek ek bilgisayar adları ve IP adresleri "
            "(her satıra bir adres). localhost ve 127.0.0.1 her zaman izinlidir."
        ),
    )

    bank_details = models.TextField(
        "ofis banka bilgileri",
        blank=True,
        help_text=(
            "Banka, hesap sahibi ve IBAN; her hesap ayrı satıra. "
            "Doluysa WhatsApp mesaj şablonlarına eklenir."
        ),
    )

    class Meta:
        verbose_name = "ofis ayarları"
        verbose_name_plural = "ofis ayarları"

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        from django.conf import settings

        self.pk = 1
        super().save(*args, **kwargs)
        hosts = getattr(settings, "ALLOWED_HOSTS", None)
        if hasattr(hosts, "reset"):
            hosts.reset()
        cache = request_cache.get()
        if cache is not None:
            cache.pop("obj", None)

    def set_role_permission(self, key: str, roles) -> None:
        """Bir yetkiye sahip rolleri kaydeder (yönetici her zaman yetkilidir)."""
        saved = dict(self.role_permissions or {})
        saved[key] = sorted(set(roles) | {"admin"})
        self.role_permissions = saved
        self.save(update_fields=["role_permissions"])

    @classmethod
    def load(cls) -> "OfficeSettings":
        """Tek ayar satırı. İstek sırasında veritabanından bir kez okunur; her çağrıya ayrı kopya
        verilir, böylece formun kaydedilmemiş değişikliği başka yerde görünmez."""
        cache = request_cache.get()
        if cache is None:
            obj, _ = cls.objects.get_or_create(pk=1)
            return obj
        if "obj" not in cache:
            cache["obj"], _ = cls.objects.get_or_create(pk=1)
        return copy.copy(cache["obj"])

    @property
    def slug(self) -> str:
        """Yedek ve dışa aktarım dosya adlarında kullanılacak kısa ASCII ad."""
        import re

        from apps.core.text import fold

        parts = [p for p in re.split(r"[^a-z0-9]+", fold(self.name or "")) if p]
        stop_words = {"hukuk", "burosu", "buro", "avukatlik", "ofisi", "ofis", "ortakligi"}
        core = [p for p in parts if p not in stop_words] or parts
        return "-".join(core[:2])[:24] or "hukuk-burosu"


class LookupModel(models.Model):
    name = models.CharField("ad", max_length=200, unique=True)
    is_active = models.BooleanField("aktif", default=True)
    order = models.PositiveIntegerField("sıra", default=0)

    class Meta:
        abstract = True
        ordering = ["order", "name"]

    def __str__(self):
        return self.name


HEARING_TASK_TYPE_NAME = tr_capitalize_words("Duruşma ve Müvekkil Bilgilendirme")


class TaskType(LookupModel):
    requires_document = models.BooleanField("kontrole göndermek için belge zorunlu", default=False)
    requires_accounting = models.BooleanField(
        "kontrole göndermek için gelir / gider zorunlu", default=False
    )
    points = models.PositiveSmallIntegerField("puan", default=0)
    categories = models.JSONField("kategoriler", default=list, blank=True)
    petition_template = models.CharField("dilekçe şablonu", max_length=255, blank=True)

    class Meta(LookupModel.Meta):
        verbose_name = "görev türü"
        verbose_name_plural = "görev türleri"

    def save(self, *args, **kwargs):
        self.name = tr_capitalize_words(self.name)
        return super().save(*args, **kwargs)


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
