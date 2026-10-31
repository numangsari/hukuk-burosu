from django import forms

from apps.clients.models import Party
from apps.core.forms import BootstrapMixin, DateInput, DateTimeInput

from .models import Case, CaseEvent, CaseParty, Document, Hearing, PartyRole, Service


class CaseForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = Case
        fields = [
            "client",
            "case_type",
            "archive_no",
            "official_no",
            "authority",
            "subject",
            "value",
            "status",
            "stage",
            "enforcement_type",
            "crime",
            "mediator",
            "responsible_lawyer",
            "responsible_intern",
            "opened_on",
            "closed_on",
            "notes",
            "folder_name",
        ]
        widgets = {"opened_on": DateInput(), "closed_on": DateInput()}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["case_type"].widget.attrs["x-model"] = "caseType"
        self.fields["authority"].widget.attrs["list"] = "authority-options"
        self.fields["client"].queryset = self.fields["client"].queryset.filter(is_active=True)
        if self.instance.pk:
            # Pasif müvekkilin mevcut dosyası düzenlenebilsin.
            self.fields["client"].queryset |= type(self.instance.client).objects.filter(
                pk=self.instance.client_id
            )

    def clean_archive_no(self):
        value = self.cleaned_data["archive_no"].strip()
        qs = Case.objects.filter(archive_no__iexact=value)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError(f"{value} arşiv numarası başka bir dosyada kullanılıyor.")
        return value

    def clean(self):
        data = super().clean()
        case = Case(case_type=data.get("case_type") or "civil")
        if not case.is_litigation:
            data["stage"] = ""
        if data.get("case_type") != "enforcement":
            data["enforcement_type"] = ""
        if data.get("case_type") not in ("criminal", "investigation"):
            data["crime"] = ""
        if data.get("case_type") != "mediation":
            data["mediator"] = ""
        return data


class CasePartyForm(BootstrapMixin, forms.ModelForm):
    """Dosyaya yeni karşı taraf ekler. Aynı kimlik no'lu kayıt varsa yeniden kullanılır."""

    role = forms.ChoiceField(label="rol", choices=PartyRole.choices)
    confirm_conflict = forms.BooleanField(
        label="Bu kişi müvekkilimiz, yine de karşı taraf olarak ekle", required=False
    )

    class Meta:
        model = Party
        fields = ["kind", "name", "identity_no", "lawyer", "address"]
        widgets = {"address": forms.Textarea(attrs={"rows": 1})}


class ExistingPartyForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = CaseParty
        fields = ["party", "role"]


class DocumentForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = Document
        fields = ["title", "category", "file", "notes"]
        widgets = {"notes": forms.Textarea(attrs={"rows": 1})}

    def clean_file(self):
        f = self.cleaned_data["file"]
        if f and f.size > 50 * 1024 * 1024:
            raise forms.ValidationError("Belge 50 MB'tan büyük olamaz.")
        return f


class HearingForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = Hearing
        fields = ["kind", "starts_at", "authority", "room", "notes"]
        widgets = {"starts_at": DateTimeInput(), "notes": forms.Textarea(attrs={"rows": 1})}


class HearingResultForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = Hearing
        fields = ["status", "result"]
        widgets = {"result": forms.Textarea(attrs={"rows": 2})}


class ServiceForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = Service
        fields = ["kind", "subject", "served_on", "deadline", "notes"]
        widgets = {
            "served_on": DateInput(),
            "deadline": DateInput(),
            "notes": forms.Textarea(attrs={"rows": 1}),
        }

    def clean(self):
        data = super().clean()
        if data.get("deadline") and data.get("served_on") and data["deadline"] < data["served_on"]:
            self.add_error("deadline", "Son gün, tebliğ tarihinden önce olamaz.")
        return data


class CaseEventForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = CaseEvent
        fields = ["date", "title", "description"]
        widgets = {"date": DateInput(), "description": forms.Textarea(attrs={"rows": 1})}
