"""Dilekçe havuzu: herkesin görüp indirebildiği, herkesin yükleyebildiği örnek dilekçeler."""

from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Count
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.utils.decorators import method_decorator
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.generic import CreateView, ListView, View

from apps.core.forms import BootstrapMixin
from apps.core.pagination import page_size
from apps.core.permission_registry import has_perm
from apps.core.text import fold
from apps.core.uploads import validate_upload

from .models import PetitionSample


class PetitionSampleForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = PetitionSample
        fields = ["title", "petition_type", "description", "file"]
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}
        labels = {"petition_type": "Dilekçe türü"}

    def clean_file(self):
        f = self.cleaned_data.get("file")
        validate_upload(f)
        return f


class PetitionPoolListView(ListView):
    template_name = "tasks/pool.html"
    context_object_name = "samples"

    def get_paginate_by(self, queryset):
        return page_size(self.request, default=50)

    def get_queryset(self):
        g = self.request.GET
        qs = PetitionSample.objects.select_related("created_by")
        if q := g.get("q", "").strip():
            qs = qs.filter(search_key__contains=fold(q))
        if tur := g.get("tur", "").strip():
            qs = qs.filter(petition_type=tur)
        return qs

    def get_template_names(self):
        if self.request.htmx:
            return ["tasks/_pool_table.html"]
        return [self.template_name]

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        rows = (
            PetitionSample.objects.exclude(petition_type="")
            .values("petition_type")
            .annotate(count=Count("pk"))
            .order_by("petition_type")
        )
        ctx["types"] = [{"name": r["petition_type"], "count": r["count"]} for r in rows]
        ctx["is_admin"] = has_perm(self.request.user, "petition_pool.delete_any")
        return ctx


@method_decorator(xframe_options_sameorigin, name="dispatch")
class PetitionSampleCreateView(CreateView):
    model = PetitionSample
    form_class = PetitionSampleForm
    template_name = "tasks/pool_form.html"

    def form_valid(self, form):
        sample = form.save(commit=False)
        sample.created_by = self.request.user
        sample.original_name = form.cleaned_data["file"].name[:300]
        sample.size = form.cleaned_data["file"].size
        sample.save()
        messages.success(self.request, "Dilekçe havuza eklendi.")
        if self.request.GET.get("pencere"):
            return HttpResponse("<script>window.parent.location.reload()</script>")
        return redirect("tasks:pool")


class PetitionSampleDeleteView(View):
    http_method_names = ["post"]

    def post(self, request, pk):
        sample = get_object_or_404(PetitionSample, pk=pk)
        own = sample.created_by_id == request.user.pk
        if not own and not has_perm(request.user, "petition_pool.delete_any"):
            raise PermissionDenied
        sample.file.delete(save=False)
        sample.delete()
        messages.success(request, "Dilekçe havuzdan silindi.")
        return redirect("tasks:pool")
