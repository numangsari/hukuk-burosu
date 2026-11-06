"""Dosya detayındaki duruşma ve zaman çizelgesi işlemleri (HTMX partial)."""

from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views import View

from apps.core.permissions import AdminRequiredMixin, filter_visible_cases, is_admin

from .forms import CaseEventForm, HearingForm, HearingResultForm
from .models import Case, CaseEvent, Hearing, HearingStatus


def hearings_partial(request, case, form=None):
    return render(
        request,
        "cases/_hearings.html",
        {
            "case": case,
            "hearing_form": form or HearingForm(initial={"authority": case.authority}),
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


class HearingAddView(View):
    def post(self, request, pk):
        case = get_object_or_404(filter_visible_cases(Case.objects.all(), request.user), pk=pk)
        form = HearingForm(request.POST)
        if not form.is_valid():
            return hearings_partial(request, case, form)
        h = form.save(commit=False)
        h.case, h.created_by = case, request.user
        h.save()
        return hearings_partial(request, case)


class HearingResultView(View):
    """Duruşma sonucunu/durumunu kaydeder; sonuç zaman çizelgesine düşer."""

    def post(self, request, pk, item_pk):
        case = get_object_or_404(filter_visible_cases(Case.objects.all(), request.user), pk=pk)
        h = get_object_or_404(Hearing, pk=item_pk, case=case)
        form = HearingResultForm(request.POST, instance=h)
        if form.is_valid():
            h = form.save()
            if h.status != HearingStatus.PLANNED:
                text = f"{h.get_kind_display()} {h.get_status_display().lower()}"
                CaseEvent.objects.create(
                    case=case,
                    date=timezone.localtime(h.starts_at).date(),
                    kind=CaseEvent.Kind.HEARING,
                    title=text,
                    description=h.result,
                    created_by=request.user,
                )
        return hearings_partial(request, case)


class HearingDeleteView(AdminRequiredMixin, View):
    def post(self, request, pk, item_pk):
        case = get_object_or_404(filter_visible_cases(Case.objects.all(), request.user), pk=pk)
        get_object_or_404(Hearing, pk=item_pk, case=case).delete()
        return hearings_partial(request, case)


class EventAddView(View):
    def post(self, request, pk):
        case = get_object_or_404(filter_visible_cases(Case.objects.all(), request.user), pk=pk)
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
        case = get_object_or_404(filter_visible_cases(Case.objects.all(), request.user), pk=pk)
        e = get_object_or_404(CaseEvent, pk=item_pk, case=case, kind=CaseEvent.Kind.NOTE)
        if e.created_by_id == request.user.pk or is_admin(request.user):
            e.delete()
        return events_partial(request, case)
