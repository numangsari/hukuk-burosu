from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.files.base import ContentFile
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from apps.cases.models import Case
from apps.clients.models import Client
from apps.core.forms import BootstrapMixin
from apps.tasks.models import TaskDocument
from apps.tasks.views import TaskCreateView

from .models import PortalCapture, PortalCase, PortalNotice, PortalNoticeDocument
from .portal_case_sync import sync_portal_case
from .portal_finance import import_finance
from .portal_matching import (
    calculate_notice_due_date,
    find_matching_case,
    get_notice_urgency,
    parse_notice_subject,
)


@login_required
@require_GET
def notice_document(request, pk):
    document = get_object_or_404(PortalNoticeDocument, pk=pk)
    try:
        stream = document.file.open("rb")
    except (FileNotFoundError, ValueError):
        raise Http404 from None
    pdf = document.original_name.lower().endswith(".pdf")
    response = FileResponse(
        stream,
        content_type="application/pdf" if pdf else "application/octet-stream",
        as_attachment=not pdf,
        filename=document.original_name,
    )
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "private, no-store"
    return response


@login_required
def notice_detail(request, pk):
    notice = get_object_or_404(PortalNotice.objects.prefetch_related("documents"), pk=pk)
    details = notice.data.get("ayrinti", {}) if isinstance(notice.data, dict) else {}
    details = details if isinstance(details, dict) else {}
    source = details.get("eyp_details", {})
    source = source if isinstance(source, dict) else {}
    return render(
        request,
        "imports/portal_notice_detail.html",
        {
            "notice": notice,
            "recipient": details.get("recipient_name", ""),
            "source_subject": source.get("Konu", ""),
            "source_name": source.get("DosyaAdi", ""),
        },
    )


@login_required
@user_passes_test(lambda user: user.is_office_admin)
def index(request):
    query = request.GET.get("q", "").strip()
    cases = PortalCase.objects.select_related("case")
    if query:
        cases = cases.filter(Q(authority__icontains=query) | Q(number__icontains=query))
    from apps.core.pagination import page_size

    page = Paginator(cases, page_size(request, default=50)).get_page(request.GET.get("page"))
    for rec in page.object_list:
        if not rec.case_id:
            rec.suggested_case = find_matching_case(rec.authority, rec.number)
        else:
            rec.suggested_case = None
    return render(
        request,
        "imports/portal_review.html",
        {
            "page_obj": page,
            "query": query,
            "case_count": PortalCase.objects.count(),
            "created_count": PortalCase.objects.filter(case__isnull=False).count(),
            "notices": PortalNotice.objects.prefetch_related("documents"),
            "response_count": PortalCapture.objects.count(),
        },
    )


@login_required
def detail(request, pk):
    record = get_object_or_404(PortalCase.objects.select_related("case"), pk=pk)
    data = record.data
    latest_detail = next(
        (item for item in reversed(data.get("ayrintilar", [])) if isinstance(item, dict)), {}
    )
    labels = {
        "davaTurleriStr": "Dava türü",
        "davaAcilisTuruStr": "Açılış türü",
        "dosyaDurumu": "Dosya durumu",
        "durusmaTarihiStr": "Duruşma tarihi",
        "onIncelemTarihiStr": "Ön inceleme tarihi",
        "davaninKonusu": "Dava konusu",
        "takibinTuruAciklama": "Takip türü",
        "takibinYoluAciklama": "Takip yolu",
        "takibinSekliAciklama": "Takip şekli",
        "alacakKalemToplamTutar": "Alacak kalemleri toplamı",
        "alacakKalemFaizTutar": "Faiz",
        "tahsilHarci": "Tahsil harcı",
        "takipSonrasiMasraf": "Takip sonrası masraf",
        "vekaletUcreti": "Vekâlet ücreti",
        "yapilmisBorcTahsilati": "Yapılmış borç tahsilatı",
        "karar": "Karar",
        "kararAciklama": "Sonuç",
        "kararNo": "Karar numarası",
        "kararTarihi": "Karar tarihi",
        "arabulucu": "Arabulucu",
        "gelenBirimAdi": "Gelen birim",
        "gelenDosyaNo": "Gelen dosya numarası",
        "ilgiliDosyaListesiStr": "İlgili dosyalar",
        "ilgiliDavaListesiStr": "İlgili davalar",
        "ilgiliSeriDavaListesiStr": "İlgili seri davalar",
        "birlesenDosyaListStr": "Birleşen dosyalar",
    }
    details = [
        (label, latest_detail[key])
        for key, label in labels.items()
        if key in latest_detail and latest_detail[key] not in (None, "", [])
    ]
    parties = next(
        (
            item
            for item in reversed(data.get("taraf_listeleri", []))
            if isinstance(item, list) and item
        ),
        [],
    )
    document_rows = []
    folders = {}
    for item in data.get("belge_listeleri", []):
        if not isinstance(item, dict):
            continue
        rows = item.get("son20Evrak")
        if not isinstance(rows, list):
            rows = []
        for document in rows:
            if document not in document_rows:
                document_rows.append(document)
        if item.get("tumEvraklar"):
            folders = item["tumEvraklar"]
    finance = next(
        (item for item in reversed(data.get("hesaplar", [])) if isinstance(item, list)), []
    )
    transactions = next(
        (item for item in reversed(data.get("tahsilatlar", [])) if isinstance(item, dict)), {}
    )
    hearings = []
    seen_hearings = set()
    for hearing in data.get("durusmalar", []):
        key = hearing.get("kayitId") or hearing.get("tarihSaat")
        if key not in seen_hearings:
            seen_hearings.add(key)
            hearings.append(hearing)
    suggested_case = None
    if not record.case_id:
        suggested_case = find_matching_case(record.authority, record.number)
    initial_form = {"case": suggested_case.pk} if suggested_case else None

    return render(
        request,
        "imports/portal_detail.html",
        {
            "record": record,
            "link_form": PortalCaseLinkForm(initial=initial_form),
            "suggested_case": suggested_case,
            "details": details,
            "parties": parties,
            "documents": document_rows,
            "folders": folders,
            "finance": finance,
            "transactions": transactions,
            "hearings": hearings,
        },
    )


class PortalCaseLinkForm(forms.Form):
    case = forms.ModelChoiceField(label="Büro dosyası", queryset=Case.objects.all())


@login_required
@user_passes_test(lambda user: user.is_office_admin)
@require_POST
def link_case(request, pk):
    form = PortalCaseLinkForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Geçerli bir büro dosyası seçin.")
        return redirect("portal_review_detail", pk=pk)
    try:
        with transaction.atomic():
            record = get_object_or_404(PortalCase.objects.select_for_update(), pk=pk)
            if record.case_id:
                messages.error(request, "Bu UYAP kaydı zaten bir dosyaya bağlı.")
                return redirect("portal_review_detail", pk=pk)
            case = Case.objects.select_for_update().get(pk=form.cleaned_data["case"].pk)
            if PortalCase.objects.filter(case=case).exists():
                messages.error(request, "Bu dosyaya başka bir UYAP kaydı bağlı.")
                return redirect("portal_review_detail", pk=pk)
            record.case = case
            record.save(update_fields=["case"])
            sync_portal_case(record, default_user=request.user, create_missing=False)
            import_finance(record)
    except IntegrityError:
        messages.error(request, "Dosya başka bir kayıtla ilişkilendirilmiş.")
    else:
        messages.success(request, f"UYAP bilgileri '{case.display_name}' dosyasına bağlandı.")
        return redirect(case)
    return redirect("portal_review_detail", pk=pk)


class NoTaskForm(BootstrapMixin, forms.Form):
    client = forms.ModelChoiceField(
        label="Müvekkil",
        queryset=Client.objects.all(),
        widget=forms.Select(attrs={"data-searchable": "Müvekkil ara"}),
    )
    case = forms.ModelChoiceField(
        label="Dosya",
        queryset=Case.objects.all(),
        required=False,
        widget=forms.Select(attrs={"data-searchable": "Dosya ara"}),
    )
    reason = forms.CharField(
        label="Görev olmama nedeni",
        widget=forms.Textarea(
            attrs={
                "rows": 3,
                "placeholder": "Bu tebligat için neden görev oluşturulmadığını açıklayın...",
            }
        ),
    )

    def clean(self):
        data = super().clean()
        case, client = data.get("case"), data.get("client")
        if case and client and case.client_id != client.pk:
            self.add_error("case", "Seçilen dosya bu müvekkile ait değil.")
        return data


@login_required
def notice_list(request):
    from apps.core.pagination import page_size

    notices = PortalNotice.objects.select_related(
        "resolution_client", "resolution_case", "resolution_task", "resolved_by"
    ).order_by("-delivered_at", "-pk")
    page = Paginator(notices, page_size(request)).get_page(request.GET.get("page"))
    for n in page.object_list:
        if not n.resolution_case:
            auth, num = parse_notice_subject(n.subject)
            n.suggested_case = find_matching_case(auth, num) if num else None
        else:
            n.suggested_case = None
        n.suggested_due_date = calculate_notice_due_date(n.delivered_at)
        urgency, due_label = get_notice_urgency(n.suggested_due_date)
        n.due_urgency = urgency
        n.due_label = due_label
    return render(request, "imports/notices.html", {"notices": page.object_list, "page_obj": page})


@login_required
def notice_no_task(request, pk):
    notice = get_object_or_404(PortalNotice, pk=pk)
    initial = {}
    auth, num = parse_notice_subject(notice.subject)
    suggested = find_matching_case(auth, num) if num else None
    if suggested:
        initial["case"] = suggested.pk
        if suggested.client:
            initial["client"] = suggested.client.pk

    form = NoTaskForm(request.POST or None, initial=initial if not request.POST else None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            notice = get_object_or_404(PortalNotice.objects.select_for_update(), pk=pk)
            if notice.resolved_at:
                messages.error(request, "Bu tebligat daha önce işlendi.")
            else:
                notice.resolution_client = form.cleaned_data["client"]
                notice.resolution_case = form.cleaned_data["case"]
                notice.no_task_reason = form.cleaned_data["reason"]
                notice.resolved_by = request.user
                notice.resolved_at = timezone.now()
                notice.save(
                    update_fields=[
                        "resolution_client",
                        "resolution_case",
                        "no_task_reason",
                        "resolved_by",
                        "resolved_at",
                    ]
                )
                messages.success(request, "Tebligat için görev olmadığı kaydedildi.")
                if getattr(request, "htmx", False):
                    response = HttpResponse(status=204)
                    response["HX-Trigger"] = "notice-saved"
                    return response
        return redirect("notice_list")
    template_name = (
        "imports/_notice_no_task_modal.html"
        if getattr(request, "htmx", False)
        else "imports/notice_no_task.html"
    )
    return render(request, template_name, {"form": form, "notice": notice})


class NoticeTaskCreateView(TaskCreateView):
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            from django.contrib.auth.views import redirect_to_login

            return redirect_to_login(request.get_full_path())
        self.notice = get_object_or_404(PortalNotice, pk=kwargs["pk"])
        if self.notice.resolved_at:
            messages.error(request, "Bu tebligat daha önce işlendi.")
            return redirect("notice_list")
        return super().dispatch(request, *args, **kwargs)

    def get_success_url(self):
        return reverse("notice_list")

    def get_template_names(self):
        if getattr(self.request, "htmx", False):
            return ["imports/_notice_task_create_modal.html"]
        return super().get_template_names()

    def get_initial(self):
        initial = super().get_initial()
        if self.notice.delivered_at:
            initial["due_date"] = calculate_notice_due_date(self.notice.delivered_at)
        auth, num = parse_notice_subject(self.notice.subject)
        suggested = find_matching_case(auth, num) if num else None
        if suggested:
            initial["case"] = suggested
            if suggested.client:
                initial["client"] = suggested.client
        initial["title"] = f"Tebligat: {self.notice.subject[:100]}"
        return initial

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        form.fields["client"].required = True
        if getattr(self.request, "htmx", False):
            for field in form.fields.values():
                for attr in list(field.widget.attrs):
                    if attr.startswith("@change") or attr == "x-ref":
                        field.widget.attrs.pop(attr)
        return form

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["notice"] = self.notice
        return context

    def form_valid(self, form):
        contents = []
        try:
            for doc in self.notice.documents.all():
                with doc.file.open("rb") as source:
                    contents.append((doc.original_name, source.read()))
        except (OSError, ValueError):
            form.add_error(None, "Tebligat belgesine erişilemedi; görev oluşturulmadı.")
            return self.form_invalid(form)
        created_files = []
        try:
            with transaction.atomic():
                notice = PortalNotice.objects.select_for_update().get(pk=self.notice.pk)
                if notice.resolved_at:
                    form.add_error(None, "Bu tebligat daha önce işlendi.")
                    return self.form_invalid(form)
                response = super().form_valid(form)
                for name, content in contents:
                    doc = TaskDocument(
                        task=self.object,
                        original_name=name,
                        size=len(content),
                        uploaded_by=self.request.user,
                    )
                    doc.file.save(name, ContentFile(content), save=False)
                    created_files.append((doc.file.storage, doc.file.name))
                    doc.save()
                notice.resolution_client = self.object.client
                notice.resolution_case = self.object.case
                notice.resolution_task = self.object
                notice.resolved_by = self.request.user
                notice.resolved_at = timezone.now()
                notice.save(
                    update_fields=[
                        "resolution_client",
                        "resolution_case",
                        "resolution_task",
                        "resolved_by",
                        "resolved_at",
                    ]
                )
                if getattr(self.request, "htmx", False):
                    messages.success(self.request, "Görev başarıyla oluşturuldu.")
                    resp = HttpResponse(status=204)
                    resp["HX-Trigger"] = "notice-saved"
                    return resp
                return response
        except Exception:
            for storage, name in created_files:
                storage.delete(name)
            raise
