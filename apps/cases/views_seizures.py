from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from apps.core.permissions import filter_visible_cases, is_admin

from .forms import SeizureForm
from .models import Case, CaseType, Seizure
from .seizures import create_due_tasks, save_seizure


class SeizureSaveView(View):
    def dispatch(self, request, pk, item_pk=None, **kwargs):
        self.case = get_object_or_404(
            filter_visible_cases(Case.objects.all(), request.user),
            pk=pk,
            case_type=CaseType.ENFORCEMENT,
        )
        if not self.case.is_open:
            raise PermissionDenied
        self.item = (
            get_object_or_404(Seizure, pk=item_pk, case=self.case)
            if item_pk
            else Seizure(case=self.case)
        )
        return super().dispatch(request, pk=pk, item_pk=item_pk, **kwargs)

    def get(self, request, **kwargs):
        from .seizure_types import KINDS

        kind = request.GET.get("kind", "")
        initial = {"kind": kind} if not self.item.pk and kind in dict(KINDS) else {}
        return self._render(request, SeizureForm(instance=self.item, initial=initial))

    def post(self, request, **kwargs):
        form = SeizureForm(request.POST, instance=self.item)
        if form.is_valid():
            try:
                save_seizure(self.case, form, request.user)
            except (ValueError, ValidationError) as error:
                form.add_error(
                    None,
                    " ".join(error.messages) if isinstance(error, ValidationError) else str(error),
                )
            else:
                create_due_tasks()
                messages.success(request, "Haciz takibi kaydedildi.")
                return redirect(f"{self.case.get_absolute_url()}#t-haciz")
        return self._render(request, form)

    def _render(self, request, form):
        return render(
            request,
            "cases/seizure_form.html",
            {"case": self.case, "form": form, "item": self.item, "seizure_config": form.config},
        )


class SeizureDeleteView(View):
    def post(self, request, pk, item_pk):
        if not is_admin(request.user):
            raise PermissionDenied
        with transaction.atomic():
            case = get_object_or_404(
                filter_visible_cases(Case.objects.all(), request.user).select_for_update(
                    of=("self",)
                ),
                pk=pk,
                case_type=CaseType.ENFORCEMENT,
            )
            if not case.is_open:
                raise PermissionDenied
            item = get_object_or_404(Seizure.objects.select_for_update(), pk=item_pk, case=case)
            item.delete()
        messages.success(request, "Haciz kaydı silindi.")
        return redirect(f"{case.get_absolute_url()}#t-haciz")
