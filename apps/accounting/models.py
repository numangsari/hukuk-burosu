"""Muhasebe hareketleri.

Cari bakiye (müvekkilin ofise borcu) = vekalet ücreti + masraf − tahsilat − mahsup
Emanet bakiyesi (ofiste duran müvekkil parası) = karşı taraftan tahsilat − müvekkile ödeme − mahsup
Net durum = cari − emanet
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
    OFFSET = "offset", "Mahsup"


# Bakiyeye etkisi: (cari işareti, emanet işareti)
EFFECTS = {
    EntryKind.FEE: (1, 0),
    EntryKind.EXPENSE: (1, 0),
    EntryKind.COLLECTION: (-1, 0),
    EntryKind.TRUST_IN: (0, 1),
    EntryKind.TRUST_OUT: (0, -1),
    EntryKind.OFFSET: (-1, -1),
}

KIND_HELP = {
    EntryKind.FEE: "Dosya için belirlenen vekalet ücreti. Müvekkilin borcunu artırır.",
    EntryKind.EXPENSE: "Müvekkil adına yapılan harç, masraf vb. Müvekkilin borcunu artırır.",
    EntryKind.COLLECTION: "Müvekkilden alınan ücret veya masraf. Müvekkilin borcunu azaltır.",
    EntryKind.TRUST_IN: "Müvekkil adına karşı taraftan tahsil edilen para. Emanete girer.",
    EntryKind.TRUST_OUT: "Emanetteki paranın müvekkile aktarılması. Emanetten düşer.",
    EntryKind.OFFSET: (
        "Emanetteki paradan ücret/masraf alacağının düşülmesi. Cari ve emanet birlikte azalır."
    ),
}

ZERO = Decimal("0.00")
_MONEY = DecimalField(max_digits=16, decimal_places=2)


def _signed(index: int):
    """Hareket türüne göre işaretli tutar ifadesi (0: cari, 1: emanet)."""
    whens = [
        When(kind=k, then=F("amount") * Value(eff[index]))
        for k, eff in EFFECTS.items()
        if eff[index]
    ]
    return DbCase(*whens, default=Value(ZERO), output_field=_MONEY)


CARI_EXPR = _signed(0)
TRUST_EXPR = _signed(1)


class LedgerQuerySet(models.QuerySet):
    def active(self):
        return self.filter(is_cancelled=False)

    def balances(self) -> dict:
        agg = self.active().aggregate(
            cari=Coalesce(Sum(CARI_EXPR), Value(ZERO), output_field=_MONEY),
            trust=Coalesce(Sum(TRUST_EXPR), Value(ZERO), output_field=_MONEY),
        )
        agg["net"] = agg["cari"] - agg["trust"]
        return agg

    def totals_by_kind(self) -> dict:
        rows = self.active().values("kind").annotate(total=Sum("amount"))
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
    is_cancelled = models.BooleanField("iptal", default=False)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    cancel_reason = models.CharField("iptal nedeni", max_length=300, blank=True)

    objects = LedgerQuerySet.as_manager()

    class Meta:
        verbose_name = "muhasebe hareketi"
        verbose_name_plural = "muhasebe hareketleri"
        ordering = ["-date", "-pk"]
        indexes = [models.Index(fields=["client", "is_cancelled"])]

    def __str__(self):
        return f"{self.get_kind_display()} {self.amount} ₺"

    def save(self, *args, **kwargs):
        if self.case_id:
            self.client_id = Case.objects.values_list("client_id", flat=True).get(pk=self.case_id)
        super().save(*args, **kwargs)

    @property
    def cari_effect(self) -> Decimal:
        return self.amount * EFFECTS[EntryKind(self.kind)][0]

    @property
    def trust_effect(self) -> Decimal:
        return self.amount * EFFECTS[EntryKind(self.kind)][1]
