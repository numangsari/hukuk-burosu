from django import forms

from apps.accounts.models import User
from apps.cases.models import Case, CaseStatus
from apps.clients.models import Client
from apps.core.forms import BootstrapMixin, DateInput
from apps.office.models import TaskType

from .models import Task


class CaseChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return f"{obj.archive_no} — {obj.subject} ({obj.client})"


class TaskForm(BootstrapMixin, forms.ModelForm):
    # Yalnızca dosya listesini süzmek için; kaydedilen müvekkil her zaman dosyanın müvekkilidir.
    client = forms.ModelChoiceField(
        label="müvekkil", queryset=Client.objects.filter(is_active=True), required=False
    )
    case = CaseChoiceField(label="dosya", queryset=Case.objects.none())

    class Meta:
        model = Task
        fields = ["task_type", "title", "case", "assignee", "reviewer", "due_date", "notes"]
        widgets = {"due_date": DateInput()}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        types = TaskType.objects.filter(is_active=True)
        cases = Case.objects.exclude(status=CaseStatus.CLOSED)
        users = User.objects.filter(is_active=True)
        if self.instance.pk:
            # Pasife alınmış tür/kapanmış dosya/pasif kullanıcı mevcut görevde seçili kalabilsin.
            types = types | TaskType.objects.filter(pk=self.instance.task_type_id)
            cases = cases | Case.objects.filter(pk=self.instance.case_id)
            users = users | User.objects.filter(
                pk__in=[self.instance.assignee_id, self.instance.reviewer_id]
            )
            self.fields["client"].initial = self.instance.client_id
        self.fields["task_type"].queryset = types
        self.fields["case"].queryset = cases.select_related("client").order_by("-created_at")
        self.fields["assignee"].queryset = users.distinct()
        self.fields["reviewer"].queryset = users.distinct()
        self.fields["client"].widget.attrs["x-ref"] = "client"
        self.fields["case"].widget.attrs["x-ref"] = "case"
        self.fields["client"].widget.attrs["@change"] = "filterCases()"
        self.fields["case"].widget.attrs["@change"] = "caseChanged()"

    def clean(self):
        data = super().clean()
        client, case = data.get("client"), data.get("case")
        if client and case and case.client_id != client.pk:
            self.add_error("case", "Seçilen dosya bu müvekkile ait değil.")
        a, r = data.get("assignee"), data.get("reviewer")
        if a and r and a == r:
            self.add_error("reviewer", "Kontrolcü, sorumludan farklı biri olmalı.")
        return data


class ActionForm(forms.Form):
    action = forms.CharField()
    comment = forms.CharField(required=False, widget=forms.Textarea)


class CommentForm(BootstrapMixin, forms.Form):
    comment = forms.CharField(label="Yorum", widget=forms.Textarea(attrs={"rows": 2}))
