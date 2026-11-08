"""Muhasebe hareketleri.

Müvekkilin ofise borcu = vekalet ücreti + masraf
Müvekkilin ofisten alacağı = karşı taraftan tahsilat
Bakiye = (müvekkilin ofise borcu − müvekkilden tahsilat) − karşı taraftan tahsilat
         + müvekkile ödeme
Pozitif bakiye müvekkilin ofise, negatif bakiye ofisin müvekkile borçlu olduğunu gösterir.
Hareket silinmez, iptal edilir; iptal edilenler bakiyeye girmez.
"""

from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Case as DbCase
from django.db.models import DecimalField, F, Sum, Value, When
from django.db.models.functions import Coalesce

from apps.cases.models import Case
from apps.clients.models import Client
from apps.core.models import TimeStampedModel


class EntryKind(models.TextChoices):
    FEE = "fee", "Vekalet ücreti"
    EXPENSE = "expense", "Masraf"
    COLLECTION = "collection", "Tahsilat (müvekkilden)"
    TRUST_IN = "trust_in", "Karşı taraftan tahsilat"
    TRUST_OUT = "trust_out", "Müvekkile ödeme"


# Bakiyeye etkisi (+: müvekkilin borcunu artırır, −: azaltır).
EFFECTS = {
    EntryKind.FEE: 1,
    EntryKind.EXPENSE: 1,
    EntryKind.COLLECTION: -1,
    EntryKind.TRUST_IN: -1,
    EntryKind.TRUST_OUT: 1,
}

# Müvekkilin ofise borcunu oluşturan hareketler ve ofisten alacağını oluşturan hareket.
DEBT_KINDS = (EntryKind.FEE, EntryKind.EXPENSE)
CREDIT_KINDS = (EntryKind.TRUST_IN,)

KIND_HELP = {
    EntryKind.FEE: "Dosya için belirlenen vekalet ücreti. Müvekkilin ofise borcunu artırır.",
    EntryKind.EXPENSE: "Müvekkil adına yapılan harç, masraf vb. Müvekkilin ofise borcunu artırır.",
    EntryKind.COLLECTION: "Müvekkilden alınan ücret veya masraf. Bakiyeyi azaltır.",
    EntryKind.TRUST_IN: (
        "Müvekkil adına karşı taraftan tahsil edilen para. Müvekkilin ofisten alacağıdır; "
        "bakiyeyi azaltır."
    ),
    EntryKind.TRUST_OUT: (
        "Müvekkile yapılan ödeme. Müvekkilin ofisten alacağını kapatır, bakiyeyi artırır."
    ),
}

ZERO = Decimal("0.00")
_MONEY = DecimalField(max_digits=16, decimal_places=2)


def _signed():
    """Hareket türüne göre işaretli tutar ifadesi (bakiye)."""
    whens = [When(kind=k, then=F("amount") * Value(sign)) for k, sign in EFFECTS.items()]
    return DbCase(*whens, default=Value(ZERO), output_field=_MONEY)


def _only(kinds):
    whens = [When(kind=k, then=F("amount")) for k in kinds]
    return DbCase(*whens, default=Value(ZERO), output_field=_MONEY)


BALANCE_EXPR = _signed()
DEBT_EXPR = _only(DEBT_KINDS)
CREDIT_EXPR = _only(CREDIT_KINDS)


class LedgerQuerySet(models.QuerySet):
    def active(self):
        return self.filter(is_cancelled=False)

    def counted(self):
        """Bakiyeye giren hareketler: iptal edilmemiş ve hesap dışı bırakılmamış."""
        return self.filter(is_cancelled=False, excluded_from_balance=False)

    def balances(self) -> dict:
        """debt: müvekkilin ofise borcu, credit: müvekkilin ofisten alacağı, balance: bakiye;
        collection (müvekkilden tahsilat) ve payout (müvekkile ödeme) bakiyenin kalemleridir."""
        return self.counted().aggregate(
            debt=Coalesce(Sum(DEBT_EXPR), Value(ZERO), output_field=_MONEY),
            credit=Coalesce(Sum(CREDIT_EXPR), Value(ZERO), output_field=_MONEY),
            collection=Coalesce(
                Sum(_only((EntryKind.COLLECTION,))), Value(ZERO), output_field=_MONEY
            ),
            payout=Coalesce(Sum(_only((EntryKind.TRUST_OUT,))), Value(ZERO), output_field=_MONEY),
            balance=Coalesce(Sum(BALANCE_EXPR), Value(ZERO), output_field=_MONEY),
        )

    def totals_by_kind(self) -> dict:
        rows = self.counted().values("kind").annotate(total=Sum("amount"))
        totals = {k: ZERO for k in EntryKind.values}
        totals.update({r["kind"]: r["total"] for r in rows})
        return totals


class LedgerEntry(TimeStampedModel):
    client = models.ForeignKey(
        Client, verbose_name="müvekkil", on_delete=models.PROTECT, related_name="ledger_entries"
    )
    case = models.ForeignKey(
        Case,
        verbose_name="dosya",
        on_delete=models.PROTECT,
        related_name="ledger_entries",
        null=True,
        blank=True,
    )
    closing_event = models.ForeignKey(
        "cases.CaseEvent",
        verbose_name="kapanış kaydı",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="collections",
        editable=False,
    )
    kind = models.CharField("hareket türü", max_length=20, choices=EntryKind.choices)
    amount = models.DecimalField(
        "tutar (₺)",
        max_digits=16,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    date = models.DateField("tarih")
    description = models.CharField("açıklama", max_length=300, blank=True)
    receipt = models.FileField("belge / makbuz", upload_to="ledger/%Y/", blank=True)
    receipt_no = models.CharField("makbuz no", max_length=60, blank=True)
    portal_ref = models.CharField(max_length=64, unique=True, null=True, blank=True, editable=False)
    is_cancelled = models.BooleanField("iptal", default=False)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    cancel_reason = models.CharField("iptal nedeni", max_length=300, blank=True)
    # UYAP'tan hatalı gelen kaydı silmeden bakiyeden çıkarmak için (yalnızca portal_ref dolu).
    excluded_from_balance = models.BooleanField("hesap dışı", default=False)
    excluded_at = models.DateTimeField(null=True, blank=True)
    excluded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    exclude_reason = models.CharField("hesap dışı bırakma nedeni", max_length=300, blank=True)

    objects = LedgerQuerySet.as_manager()

    class Meta:
        verbose_name = "muhasebe hareketi"
        verbose_name_plural = "muhasebe hareketleri"
        ordering = ["-date", "-pk"]
        indexes = [models.Index(fields=["client", "is_cancelled"])]
        # Form dışı yazımda da (servis, aktarım, kabuk) bütünlük veritabanında korunur.
        constraints = [
            models.CheckConstraint(condition=models.Q(amount__gt=0), name="ledger_amount_positive"),
            models.CheckConstraint(
                condition=models.Q(is_cancelled=False) | models.Q(cancelled_at__isnull=False),
                name="ledger_cancel_has_time",
            ),
        ]

    def __str__(self):
        return f"{self.get_kind_display()} {self.amount} ₺"

    def save(self, *args, **kwargs):
        if self.case_id:
            # Çok müvekkilli dosyada hareket seçilen müvekkile yazılır; müvekkil dosyanın
            # müvekkillerinden değilse asıl müvekkile düşer.
            case = Case.objects.get(pk=self.case_id)
            if self.client_id not in case.client_ids():
                self.client_id = case.client_id
        super().save(*args, **kwargs)

    @property
    def balance_effect(self) -> Decimal:
        if self.excluded_from_balance:
            return ZERO
        return self.amount * EFFECTS[EntryKind(self.kind)]


class OfficeEntry(TimeStampedModel):
    """Büronun kendi (müvekkile bağlı olmayan) geliri ve gideri; yalnızca yönetici görür.

    Müvekkil bakiyesine ve cari hesaplara girmez. Silinmez, iptal edilir.
    """

    class Kind(models.TextChoices):
        INCOME = "income", "Ofis geliri"
        EXPENSE = "expense", "Ofis gideri"

    kind = models.CharField("hareket türü", max_length=10, choices=Kind.choices)
    amount = models.DecimalField(
        "tutar (₺)",
        max_digits=16,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    date = models.DateField("tarih")
    description = models.CharField("açıklama", max_length=300)
    receipt = models.FileField("belge / makbuz", upload_to="office-ledger/%Y/", blank=True)
    receipt_no = models.CharField("makbuz no", max_length=60, blank=True)
    is_cancelled = models.BooleanField("iptal", default=False)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    cancel_reason = models.CharField("iptal nedeni", max_length=300, blank=True)

    class Meta:
        verbose_name = "ofis içi gelir/gider"
        verbose_name_plural = "ofis içi gelir/giderler"
        ordering = ["-date", "-pk"]

    def __str__(self):
        return f"{self.get_kind_display()} {self.amount} ₺"
