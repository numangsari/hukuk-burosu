from django import forms

from apps.accounts.models import User
from apps.cases.models import Case, CaseStatus
from apps.clients.models import Client
from apps.core.forms import BootstrapMixin, DateInput
from apps.core.permissions import filter_visible_cases, filter_visible_clients
from apps.core.uploads import validate_upload
from apps.office.models import HEARING_TASK_TYPE_NAME, OfficeSettings, TaskType

from .models import Task
from .people import assignee_choices, reviewer_choices


class CaseChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        client_label = obj.client.name if obj.client_id and obj.client else "Müvekkil eksik"
        return f"{obj.archive_reference} — {obj.display_name} ({client_label})"


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    def clean(self, data, initial=None):
        return [super(MultipleFileField, self).clean(item, initial) for item in (data or [])]


class TaskForm(BootstrapMixin, forms.ModelForm):
    # Mevcut kayıtta not ve belge görev geçmişinden yönetilir; rutin görevde formda kalır.
    keep_notes_and_documents = False
    # Görev bir dosyaya bağlıdır; yalnızca rutin görev kuralında dosya isteğe bağlıdır.
    case_required = True
    # Yalnızca dosya listesini süzmek için; kaydedilen müvekkil her zaman dosyanın müvekkilidir.
    client = forms.ModelChoiceField(label="müvekkil", queryset=Client.objects.all(), required=False)
    case = CaseChoiceField(
        label="dosya",
        queryset=Case.objects.none(),
        required=True,
    )
    document = MultipleFileField(label="Belge", required=False, widget=MultipleFileInput)
    requires_accounting = forms.TypedChoiceField(
        label="Gelir/gider kaydı",
        help_text="Görev gerçekleştirilirken gelir / gider işlemi yapılacaksa seçiniz.",
        choices=[("", "Seçiniz…"), ("yes", "Var"), ("no", "Yok")],
        coerce=lambda value: value == "yes",
        required=True,
        widget=forms.RadioSelect,
    )

    requires_document = forms.TypedChoiceField(
        label="Dilekçe zorunluluğu",
        help_text="Kontrole göndermek için dilekçe yüklenmesi gerekiyorsa seçiniz.",
        choices=[("", "Seçiniz…"), ("yes", "Var"), ("no", "Yok")],
        coerce=lambda value: value == "yes",
        empty_value=None,
        required=False,
        widget=forms.RadioSelect,
    )

    class Meta:
        model = Task
        fields = [
            "task_type",
            "title",
            "case",
            "assignee",
            "reviewer",
            "second_reviewer",
            "due_date",
            "notes",
            "requires_accounting",
            "requires_document",
        ]
        widgets = {"due_date": DateInput()}

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["case"].required = self.case_required
        office = OfficeSettings.load()
        self.task_review_mode = office.task_review_mode
        if self.task_review_mode in (
            OfficeSettings.TaskReviewMode.OPTIONAL,
            OfficeSettings.TaskReviewMode.ASSISTANTS_ONLY,
        ):
            self.fields["reviewer"].required = False
            self.fields["reviewer"].empty_label = "Kontrolcü yok (Doğrudan kapanır)"
        else:
            self.fields["reviewer"].required = True

        if self.instance.pk:
            # Kayıtlı görevde seçim yoksa görev türünün varsayılanı gösterilir.
            self.initial["requires_accounting"] = "yes" if self.instance.needs_accounting else "no"
            self.initial["requires_document"] = "yes" if self.instance.needs_document else "no"
        types = TaskType.objects.filter(is_active=True).exclude(name__iexact=HEARING_TASK_TYPE_NAME)
        cases = Case.objects.exclude(status=CaseStatus.CLOSED)
        if self.instance.pk:
            if not self.keep_notes_and_documents:
                self.fields.pop("notes")
                self.fields.pop("document")
            # Pasife alınmış tür/kapanmış dosya/pasif kullanıcı mevcut görevde seçili kalabilsin.
            types = types | TaskType.objects.filter(pk=self.instance.task_type_id)
            cases = cases | Case.objects.filter(pk=self.instance.case_id)
            self.fields["client"].initial = self.instance.client_id
        self.fields["task_type"].queryset = types
        categories = (
            "Dava İşlemleri",
            "İcra İşlemleri",
            "Evrak ve Tebligat İşlemleri",
            "Müvekkil İşlemleri",
            "Mali İşlemler",
            "Arabuluculuk ve Uzlaşma İşlemleri",
            "Ceza ve Soruşturma İşlemleri",
            "Ofis İçi İşlemler",
            "Diğer",
        )
        groups = {name: [] for name in categories}
        for task_type in types:
            for category in task_type.categories or ["Diğer görevler"]:
                if category == "Ofis İçi, Araştırma ve Diğer İşlemler":
                    category = "Ofis İçi İşlemler"
                groups.setdefault(category, []).append((task_type.pk, task_type.name))
        self.fields["task_type"].choices = [
            ("", "Seçiniz…"),
            *[(name, options) for name, options in groups.items() if options],
        ]
        if user is not None:
            # Kısıtlı görünürlükte yalnızca erişilebilen dosya ve müvekkiller seçilebilir.
            cases = filter_visible_cases(cases, user)
            self.fields["client"].queryset = filter_visible_clients(Client.objects.all(), user)
        self.fields["case"].queryset = cases.select_related("client").order_by("-created_at")
        kept = (
            (self.instance.assignee_id, self.instance.reviewer_id, self.instance.second_reviewer_id)
            if self.instance.pk
            else ()
        )
        # Sorumlu yönetici, kontrolcü stajyer olamaz; mevcut kayıttaki kişiler seçili kalır.
        self.fields["assignee"].queryset = assignee_choices(kept)
        self.fields["reviewer"].queryset = reviewer_choices(kept)
        self.fields["second_reviewer"].queryset = reviewer_choices(kept)
        self.fields["second_reviewer"].required = False
        self.fields["second_reviewer"].empty_label = "2. kontrolcü yok"
        self.fields["client"].widget.attrs["x-ref"] = "client"
        self.fields["case"].widget.attrs["x-ref"] = "case"
        self.fields["client"].widget.attrs["data-searchable"] = "Müvekkil ara"
        self.fields["case"].widget.attrs["data-searchable"] = "Dosya ara"
        self.fields["client"].widget.attrs["@change"] = "filterCases()"
        self.fields["case"].widget.attrs["@change"] = "caseChanged()"
        self.fields["assignee"].widget.attrs["@change"] = "assigneeChanged()"
        self.fields["task_type"].widget.attrs["@change"] = "taskTypeChanged($event)"
        self.fields["task_type"].widget.attrs["data-searchable"] = "Görev türü ara"
        self.fields["title"].widget.attrs["class"] += " text-uppercase-input"
        # Sorumlu seçilince kontrolcü, sorumlunun kontrolcüsü olarak önerilir (değiştirilebilir).
        self.document_type_ids = list(
            types.filter(requires_document=True).values_list("pk", flat=True)
        )
        self.accounting_type_ids = list(
            types.filter(requires_accounting=True).values_list("pk", flat=True)
        )
        self.supervisor_map = dict(
            User.objects.filter(supervisor__isnull=False).values_list("pk", "supervisor_id")
        )

    def clean_document(self):
        document = self.cleaned_data.get("document")
        for item in document:
            validate_upload(item)
        return document

    def clean(self):
        data = super().clean()
        client, case = data.get("client"), data.get("case")
        if case and not case.client_id:
            self.add_error(
                "case", "Bu dosyanın müvekkili henüz seçilmemiş. Önce dosyadan müvekkil seçin."
            )
        elif client and case and case.client_id != client.pk:
            self.add_error("case", "Seçilen dosya bu müvekkile ait değil.")
        a, r = data.get("assignee"), data.get("reviewer")
        r2 = data.get("second_reviewer")
        if r2:
            if not r:
                self.add_error("second_reviewer", "Önce 1. kontrolcüyü seçin.")
            elif r2 in (a, r):
                self.add_error(
                    "second_reviewer", "2. kontrolcü, sorumlu ve 1. kontrolcüden farklı olmalı."
                )
        if a and r and a == r:
            self.add_error("reviewer", "Kontrolcü, sorumludan farklı biri olmalı.")
        elif (
            self.task_review_mode == OfficeSettings.TaskReviewMode.ASSISTANTS_ONLY
            and a
            and not a.is_lawyer_or_above
            and not r
        ):
            self.add_error(
                "reviewer", "Yardımcı personel görevlerinde kontrolcü seçimi zorunludur."
            )
        if not case:
            data["requires_accounting"] = False  # ofis içi görevde müvekkil gelir/gideri olmaz
        return data


class ActionForm(forms.Form):
    action = forms.CharField()
    comment = forms.CharField(required=False, widget=forms.Textarea)


class CommentForm(BootstrapMixin, forms.Form):
    comment = forms.CharField(label="Yorum", widget=forms.Textarea(attrs={"rows": 2}))
