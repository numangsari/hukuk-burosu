from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponse
from django.shortcuts import render
from django.utils import timezone
from django.utils.text import slugify
from django.views import View

from apps.accounting.permissions import can_view as can_view_accounting
from apps.office.models import OfficeSettings

from .base import fmt
from .definitions import REPORTS
from .renderers import to_pdf, to_xlsx


def visible_reports(user):
    allowed = can_view_accounting(user)
    return {k: v for k, v in REPORTS.items() if allowed or not v["financial"]}


class ReportIndexView(View):
    def get(self, request):
        return render(request, "reports/index.html", {"reports": visible_reports(request.user)})


class ReportView(View):
    def get(self, request, key):
        spec = REPORTS.get(key)
        if spec is None:
            raise Http404
        if spec["financial"] and not can_view_accounting(request.user):
            raise PermissionDenied
        submitted = "goster" in request.GET or "format" in request.GET
        form = spec["form"](request.GET if submitted else None)
        result = None
        if submitted and form.is_valid():
            result = spec["build"](form.cleaned_data, request.user)
            fmt_ = request.GET.get("format")
            if fmt_ in ("xlsx", "pdf"):
                return self.export(result, fmt_)
        rows = totals = None
        if result:
            rows = [
                [(fmt(v, c.kind), c.kind) for v, c in zip(r, result.columns, strict=False)]
                for r in result.rows
            ]
            totals = (
                [(fmt(v, c.kind) if v not in (None, "") else "", c.kind) for v, c in zip(result.totals, result.columns, strict=False)]
                if result.totals
                else None
            )  # fmt: skip
        return render(
            request,
            "reports/report.html",
            {
                "key": key,
                "spec": spec,
                "form": form,
                "result": result,
                "rows": rows,
                "totals": totals,
            },
        )

    def export(self, result, kind):
        office = OfficeSettings.load()
        name = f"{slugify(result.title.replace('ı', 'i'))}-{timezone.localdate():%Y%m%d}"
        if kind == "xlsx":
            data = to_xlsx(result, office.name)
            ctype = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        else:
            info = " · ".join(
                x for x in [office.address.replace("\n", " "), office.phone, office.email] if x
            )
            data = to_pdf(result, office.name, info)
            ctype = "application/pdf"
        resp = HttpResponse(data, content_type=ctype)
        resp["Content-Disposition"] = f'attachment; filename="{name}.{kind}"'
        return resp
