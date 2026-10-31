from django import forms

from apps.cases.models import Case
from apps.clients.models import Client
from apps.core.forms import BootstrapMixin, DateInput
from apps.core.templatetags.ui import tl

from .models import EntryKind, LedgerEntry


class CaseChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return f"{obj.archive_no} — {obj.subject}"


class LedgerEntryForm(BootstrapMixin, forms.ModelForm):
    client = forms.ModelChoiceField(label="müvekkil", queryset=Client.objects.all(), required=False)
    case = CaseChoiceField(
        label="dosya", queryset=Case.objects.select_related("client"), required=False
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

    def clean(self):
        data = super().clean()
        client, case = data.get("client"), data.get("case")
        if case and client and case.client_id != client.pk:
            self.add_error("case", "Seçilen dosya bu müvekkile ait değil.")
        if case and not client:
            data["client"] = client = case.client
        if not client:
            self.add_error("client", "Müvekkil veya dosya seçin.")
            return data
        kind, amount = data.get("kind"), data.get("amount")
        if kind in (EntryKind.TRUST_OUT, EntryKind.OFFSET) and amount:
            trust = LedgerEntry.objects.filter(client=client).balances()["trust"]
            if amount > trust:
                self.add_error(
                    "amount",
                    f"Müvekkilin emanet bakiyesi {tl(trust)}; bundan fazlası "
                    f"{'ödenemez' if kind == EntryKind.TRUST_OUT else 'mahsup edilemez'}.",
                )
        return data

    def save(self, commit=True):
        self.instance.client = self.cleaned_data["client"]
        return super().save(commit)


class CancelForm(forms.Form):
    reason = forms.CharField(label="İptal nedeni", max_length=300)
