"""Dosya detayındaki duruşma ve zaman çizelgesi işlemleri (HTMX partial)."""

from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views import View

from apps.core.permissions import PermissionRequiredMixin, filter_visible_cases, is_admin

from .forms import CaseEventForm
from .models import Case, CaseEvent, Hearing


def visible_case_or_404(request, pk):
    """Kullanıcının görünürlük kuralıyla erişebildiği dosyayı döner; yoksa 404."""
    return get_object_or_404(filter_visible_cases(Case.objects.all(), request.user), pk=pk)


def hearings_partial(request, case):
    return render(
        request,
        "cases/_hearings.html",
        {
            "case": case,
            "hearings": case.hearings.prefetch_related("tasks").order_by("-starts_at"),
            "now": timezone.now(),
        },
    )


def events_partial(request, case, form=None):
    return render(
        request,
        "cases/_timeline.html",
        {
            "case": case,
            "event_form": form or CaseEventForm(initial={"date": timezone.localdate()}),
            "timeline": case.events.filter(kind=CaseEvent.Kind.NOTE).select_related("created_by"),
        },
    )


class HearingDeleteView(PermissionRequiredMixin, View):
    required_permission = "hearings.delete"

    def post(self, request, pk, item_pk):
        case = visible_case_or_404(request, pk)
        get_object_or_404(Hearing, pk=item_pk, case=case).delete()
        return hearings_partial(request, case)


class EventAddView(View):
    def post(self, request, pk):
        case = visible_case_or_404(request, pk)
        form = CaseEventForm(request.POST)
        if not form.is_valid():
            return events_partial(request, case, form)
        e = form.save(commit=False)
        e.case, e.created_by, e.kind = case, request.user, CaseEvent.Kind.NOTE
        e.save()
        return events_partial(request, case)


class EventDeleteView(View):
    """Elle eklenen notu yalnızca ekleyen veya yönetici silebilir."""

    def post(self, request, pk, item_pk):
        case = visible_case_or_404(request, pk)
        e = get_object_or_404(CaseEvent, pk=item_pk, case=case, kind=CaseEvent.Kind.NOTE)
        if e.created_by_id == request.user.pk or is_admin(request.user):
            e.delete()
        return events_partial(request, case)
