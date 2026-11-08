"""Liste sayfalarının Excel ve PDF çıktısı.

Çıktı, sayfadaki süzgeçlerin tümünü uygular ve sayfalara bölünmeden listenin tamamını verir.
Rapor modülünün çıktı üreticileri (`apps.reports.renderers`) kullanılır.
"""

from django.http import HttpResponse
from django.utils import timezone
from django.utils.text import slugify

from apps.office.models import OfficeSettings
from apps.reports.base import Column, ReportResult
from apps.reports.renderers import to_pdf, to_xlsx

EXPORT_FORMATS = ("xlsx", "pdf")
XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def wants_export(request) -> str:
    """İstenen çıktı biçimi ("xlsx" / "pdf") veya boş metin."""
    value = request.GET.get("export", "")
    return value if value in EXPORT_FORMATS else ""


def export_response(result: ReportResult, kind: str) -> HttpResponse:
    office = OfficeSettings.load()
    name = f"{slugify(result.title.replace('ı', 'i'))}-{timezone.localdate():%Y%m%d}"
    if kind == "xlsx":
        data, content_type = to_xlsx(result, office.name), XLSX_TYPE
    else:
        info = " · ".join(
            x for x in [office.address.replace("\n", " "), office.phone, office.email] if x
        )
        data, content_type = to_pdf(result, office.name, info), "application/pdf"
    response = HttpResponse(data, content_type=content_type)
    response["Content-Disposition"] = f'attachment; filename="{name}.{kind}"'
    response["Cache-Control"] = "private, no-store"
    return response


def build_result(title: str, subtitle: str, columns: list[Column], rows, landscape=True):
    return ReportResult(
        title=title, subtitle=subtitle, columns=columns, rows=list(rows), landscape=landscape
    )


def filter_summary(request, labels: dict[str, str] | None = None) -> str:
    """Çıktı alt başlığı: kayıt sayısı ve uygulanan arama metni."""
    q = (request.GET.get("q") or "").strip()
    return f"Arama: {q}" if q else "Tüm kayıtlar (süzgeçler uygulanmış)"


class ListExportMixin:
    """`ListView`e Excel/PDF çıktısı ekler (`?export=xlsx|pdf`).

    Alt sınıf `export_title`, `export_columns` ve `export_row(obj)` tanımlar. Çıktı, sayfalama
    olmadan `get_queryset()` sonucunun tamamını kapsar; görünürlük süzgeçleri bu sorguda uygulanır.
    """

    export_title = "Liste"
    export_landscape = True

    def export_columns(self) -> list[Column]:
        raise NotImplementedError

    def export_row(self, obj) -> list:
        raise NotImplementedError

    def export_subtitle(self) -> str:
        return filter_summary(self.request)

    def get(self, request, *args, **kwargs):
        if kind := wants_export(request):
            rows = [self.export_row(obj) for obj in self.get_queryset()]
            result = build_result(
                self.export_title,
                f"{self.export_subtitle()} · {len(rows)} kayıt",
                self.export_columns(),
                rows,
                self.export_landscape,
            )
            return export_response(result, kind)
        return super().get(request, *args, **kwargs)
