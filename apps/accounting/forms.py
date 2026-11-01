from django import forms

from apps.cases.models import Case
from apps.clients.models import Client
from apps.core.forms import BootstrapMixin, DateInput
from apps.core.uploads import PDF_OR_IMAGE, validate_upload

from .models import EntryKind, LedgerEntry


class CaseChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return f"{obj.archive_reference} — {obj.display_name}"


class LedgerEntryForm(BootstrapMixin, forms.ModelForm):
    # Müvekkil zorunlu; dosya isteğe bağlı (dosyasız kayıt müvekkilin genel gelir/gideridir).
    client = forms.ModelChoiceField(
        label="müvekkil",
        queryset=Client.objects.all(),
        error_messages={"required": "Müvekkil seçin."},
    )
    case = CaseChoiceField(
        label="dosya",
        queryset=Case.objects.select_related("client"),
        required=False,
        help_text="Boş bırakılırsa kayıt müvekkilin genel gelir/gideri olur.",
    )

    class Meta:
        model = LedgerEntry
        fields = ["kind", "client", "case", "amount", "date", "description", "receipt"]
        widgets = {"kind": forms.RadioSelect, "date": DateInput()}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["kind"].choices = EntryKind.choices
        self.fields["kind"].widget.attrs.update({"class": "form-check-input", "x-model": "kind"})
        self.fields["client"].widget.attrs.update({"x-ref": "client", "@change": "filterCases()"})
        self.fields["case"].widget.attrs.update({"x-ref": "case", "@change": "caseChanged()"})
        self.fields["amount"].widget.attrs.update(
            {"step": "0.01", "min": "0.01", "inputmode": "decimal"}
        )

    def clean_receipt(self):
        f = self.cleaned_data.get("receipt")
        validate_upload(f, PDF_OR_IMAGE, 20 * 1024 * 1024)
        return f

    def clean(self):
        data = super().clean()
        client, case = data.get("client"), data.get("case")
        if case and client and case.client_id != client.pk:
            self.add_error("case", "Seçilen dosya bu müvekkile ait değil.")
        return data

    def save(self, commit=True):
        self.instance.client = self.cleaned_data["client"]
        return super().save(commit)


class CancelForm(forms.Form):
    reason = forms.CharField(label="İptal nedeni", max_length=300)
