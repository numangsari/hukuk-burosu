import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal


@dataclass
class Column:
    label: str
    kind: str = "text"  # text / money / date / int
    width: float = 1.0  # göreli genişlik (PDF ve Excel)


@dataclass
class ReportResult:
    title: str
    subtitle: str
    columns: list[Column]
    rows: list[list] = field(default_factory=list)
    totals: list | None = None
    summary: list[tuple[str, str]] = field(default_factory=list)
    landscape: bool = True


def fmt(value, kind: str) -> str:
    """Önizleme ve PDF için Türkçe biçim."""
    if value is None or value == "":
        return "—"
    if kind == "money":
        q = Decimal(value).quantize(Decimal("0.01"))
        sign = "-" if q < 0 else ""
        whole, frac = f"{abs(q):.2f}".split(".")
        return f"{sign}{int(whole):,}".replace(",", ".") + f",{frac} ₺"
    if kind == "date" and isinstance(value, dt.date):
        return value.strftime("%d.%m.%Y")
    if kind == "int":
        return str(value)
    return str(value)
