from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from .forms import SeizureForm
from .models import Case, CaseType, Seizure
from .seizures import create_due_tasks, save_seizure


class SeizureSaveView(View):
    def dispatch(self, request, pk, item_pk=None, **kwargs):
        self.case = get_object_or_404(Case, pk=pk, case_type=CaseType.ENFORCEMENT)
        if not self.case.is_open:
            raise PermissionDenied
        self.item = (
            get_object_or_404(Seizure, pk=item_pk, case=self.case)
            if item_pk
            else Seizure(case=self.case)
        )
        return super().dispatch(request, pk=pk, item_pk=item_pk, **kwargs)

    def get(self, request, **kwargs):
        return self._render(request, SeizureForm(instance=self.item))

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
            request, "cases/seizure_form.html", {"case": self.case, "form": form, "item": self.item}
        )
