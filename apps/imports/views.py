import hashlib
import uuid
from pathlib import Path

from django import forms
from django.conf import settings
from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.views import View

from apps.accounts.models import User
from apps.core.forms import BootstrapMixin
from apps.core.permissions import AdminRequiredMixin

from . import services

TMP_DIR = "imports/tmp"


class UploadForm(BootstrapMixin, forms.Form):
    file = forms.FileField(label="Doldurulmuş şablon (.xlsx)")
    default_lawyer = forms.ModelChoiceField(
        label="Varsayılan sorumlu avukat",
        queryset=User.objects.filter(role__in=["admin", "lawyer"], is_active=True),
    )
    default_intern = forms.ModelChoiceField(
        label="Varsayılan sorumlu stajyer",
        queryset=User.objects.filter(role="intern", is_active=True),
    )


def _tmp_path(token: str) -> Path:
    if not token.isalnum():
        raise ValueError
    return Path(settings.MEDIA_ROOT) / TMP_DIR / f"{token}.xlsx"


class TemplateDownloadView(AdminRequiredMixin, View):
    def get(self, request):
        resp = HttpResponse(
            services.template_bytes(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        resp["Content-Disposition"] = 'attachment; filename="ozkurt-aktarim-sablonu.xlsx"'
        return resp


class ImportView(AdminRequiredMixin, View):
    template_name = "imports/import.html"

    def get(self, request):
        return render(request, self.template_name, {"form": UploadForm()})

    def post(self, request):
        # 2. adım: önizlenen dosyayı aktar
        if token := request.POST.get("token"):
            try:
                path = _tmp_path(token)
                file_hash = hashlib.sha256(path.read_bytes()).hexdigest()
                with open(path, "rb") as f:
                    plan = services.build_plan(
                        f,
                        User.objects.get(pk=request.POST["default_lawyer"]),
                        User.objects.get(pk=request.POST["default_intern"]),
                        file_hash=file_hash,
                    )
                counts = services.execute(
                    plan,
                    request.user,
                    file_hash=file_hash,
                    file_name=request.POST.get("file_name", ""),
                )
            except (ValueError, OSError, User.DoesNotExist) as e:
                messages.error(request, f"Aktarım yapılamadı: {e}")
                return redirect("imports:import")
            path.unlink(missing_ok=True)
            messages.success(
                request,
                f"Aktarıldı: {counts['clients']} müvekkil, {counts['cases']} dosya, {counts['balances']} açılış bakiyesi.",
            )
            return redirect("clients:list")

        # 1. adım: yükle ve önizle
        form = UploadForm(request.POST, request.FILES)
        if not form.is_valid():
            return render(request, self.template_name, {"form": form})
        token = uuid.uuid4().hex
        path = _tmp_path(token)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as out:
            for chunk in form.cleaned_data["file"].chunks():
                out.write(chunk)
        try:
            with open(path, "rb") as f:
                plan = services.build_plan(
                    f,
                    form.cleaned_data["default_lawyer"],
                    form.cleaned_data["default_intern"],
                    file_hash=hashlib.sha256(path.read_bytes()).hexdigest(),
                )
        except ValueError as e:
            path.unlink(missing_ok=True)
            form.add_error("file", str(e))
            return render(request, self.template_name, {"form": form})
        summary = [
            (
                sheet,
                plan.count(sheet, "create"),
                plan.count(sheet, "skip"),
                plan.count(sheet, "error"),
            )
            for sheet in services.SHEETS
        ]
        return render(
            request,
            self.template_name,
            {
                "form": form,
                "plan": plan,
                "summary": summary,
                "token": token,
                "file_name": form.cleaned_data["file"].name,
                "default_lawyer": form.cleaned_data["default_lawyer"].pk,
                "default_intern": form.cleaned_data["default_intern"].pk,
            },
        )
