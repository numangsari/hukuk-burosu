from django import forms

from apps.core.forms import BootstrapMixin, DateInput

from .models import (
    Client,
    ClientContact,
    ClientIban,
    ClientRepresentative,
    Party,
    PersonKind,
    PowerOfAttorney,
)


class ClientForm(BootstrapMixin, forms.ModelForm):
    confirm_conflict = forms.BooleanField(
        label="Çıkar çatışması uyarısını gördüm, yine de kaydet", required=False
    )

    class Meta:
        model = Client
        fields = [
            "kind",
            "first_name",
            "last_name",
            "tckn",
            "title",
            "vkn",
            "tax_office",
            "mersis_no",
            "responsible_lawyer",
            "responsible_intern",
            "notes",
            "is_active",
            "folder_name",
        ]
        widgets = {"kind": forms.RadioSelect}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["kind"].choices = PersonKind.choices  # boş seçenek olmasın
        self.fields["kind"].widget.attrs["class"] = "form-check-input"
        self.fields["kind"].widget.attrs["x-model"] = "kind"
        self.conflicts = []


class ContactForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = ClientContact
        fields = ["kind", "label", "value", "is_primary"]
        widgets = {"value": forms.Textarea(attrs={"rows": 1})}


class IbanForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = ClientIban
        fields = ["iban", "bank", "holder", "is_primary"]


class RepresentativeForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = ClientRepresentative
        fields = ["name", "position", "phone", "email"]


class PowerOfAttorneyForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = PowerOfAttorney
        fields = ["notary", "date", "journal_no", "archive_no", "pdf", "notes"]
        widgets = {"date": DateInput(), "notes": forms.Textarea(attrs={"rows": 1})}


class PartyForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = Party
        fields = ["kind", "name", "identity_no", "lawyer", "address", "notes"]
        widgets = {
            "address": forms.Textarea(attrs={"rows": 2}),
            "notes": forms.Textarea(attrs={"rows": 2}),
        }


# Müvekkil detayındaki satır içi alt kayıtlar: url anahtarı -> (form, ilişki adı, başlık)
SUBRECORDS = {
    "iletisim": (ContactForm, "contacts", "İletişim bilgisi"),
    "iban": (IbanForm, "ibans", "IBAN"),
    "yetkili": (RepresentativeForm, "representatives", "Yetkili kişi"),
    "vekalet": (PowerOfAttorneyForm, "powers_of_attorney", "Vekalet"),
}
