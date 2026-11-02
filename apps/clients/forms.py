from django import forms

from apps.core.forms import BootstrapMixin, DateInput
from apps.core.uploads import PDF_OR_IMAGE, validate_upload

from .models import (
    Client,
    ClientContact,
    ClientIban,
    ClientRepresentative,
    Party,
    PersonKind,
    PowerOfAttorney,
    RetainerAgreement,
)


class ClientForm(BootstrapMixin, forms.ModelForm):
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
            "poa_no",
            "responsible_lawyer",
            "responsible_intern",
            "notes",
            "folder_name",
        ]
        widgets = {"kind": forms.RadioSelect, "notes": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["kind"].choices = PersonKind.choices  # boş seçenek olmasın
        self.fields["kind"].widget.attrs["class"] = "form-check-input"
        self.fields["kind"].widget.attrs["x-model"] = "kind"
        for name in ("first_name", "last_name", "title"):
            self.fields[name].widget.attrs["class"] += " text-uppercase-input"
        self.fields["poa_no"].help_text = (
            f"Boş bırakılırsa vekalet eklendiğinde sıradaki numara (V-{Client.suggest_poa_no()}) "
            "verilir. Aynı vekaleti paylaşan müvekkiller aynı numarayı kullanabilir."
        )
        self.fields["responsible_lawyer"].widget.attrs["x-on:change"] = "lawyerChanged($event)"
        self.fields["responsible_intern"].widget.attrs["x-ref"] = "intern"
        self.fields["folder_name"].help_text = (
            "Boşsa ad-soyad veya unvan kullanılır; aynı ad varsa (2) eklenir. "
            "Kaydedilmiş klasörler taşınmaz."
        )


class OptionalRowMixin:
    """Müvekkil formundaki alt kayıt satırı: boş satır zorunlu değildir; satıra bir şey
    yazılınca zorunlu alanlar (yıldızsız gösterilir) istenir."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.row_required = [name for name, f in self.fields.items() if f.required]
        for name in self.row_required:
            self.fields[name].required = False

    def clean(self):
        data = super().clean()
        if self.has_changed() and not data.get("DELETE"):
            for name in self.row_required:
                if not data.get(name) and name not in self.errors:
                    self.add_error(name, "Bu alanı doldurun.")
        return data


class ContactForm(OptionalRowMixin, BootstrapMixin, forms.ModelForm):
    class Meta:
        model = ClientContact
        fields = ["kind", "label", "value", "is_primary"]
        widgets = {"value": forms.Textarea(attrs={"rows": 1})}


class IbanForm(OptionalRowMixin, BootstrapMixin, forms.ModelForm):
    class Meta:
        model = ClientIban
        fields = ["iban", "bank", "holder", "is_primary"]


class RepresentativeForm(OptionalRowMixin, BootstrapMixin, forms.ModelForm):
    class Meta:
        model = ClientRepresentative
        fields = ["name", "position", "phone", "email"]


class PowerOfAttorneyForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = PowerOfAttorney
        fields = ["notary", "date", "journal_no", "archive_no", "pdf", "notes"]
        widgets = {"date": DateInput(), "notes": forms.Textarea(attrs={"rows": 1})}

    def clean_pdf(self):
        f = self.cleaned_data.get("pdf")
        validate_upload(f, PDF_OR_IMAGE, 20 * 1024 * 1024)
        return f


class PartyForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = Party
        fields = ["kind", "name", "identity_no", "lawyer", "address", "notes"]
        widgets = {
            "address": forms.Textarea(attrs={"rows": 2}),
            "notes": forms.Textarea(attrs={"rows": 2}),
        }


class ClientPoaForm(OptionalRowMixin, PowerOfAttorneyForm):
    """Müvekkil formundaki vekalet satırı (fiziki yer müvekkilin V-numarasıyla tutulur)."""

    class Meta(PowerOfAttorneyForm.Meta):
        fields = ["notary", "date", "journal_no", "pdf", "notes"]


class RetainerAgreementForm(OptionalRowMixin, BootstrapMixin, forms.ModelForm):
    """Müvekkil formundaki avukatlık sözleşmesi satırı."""

    class Meta:
        model = RetainerAgreement
        fields = ["signed_on", "case", "fee_amount", "pdf", "notes"]
        widgets = {"signed_on": DateInput(), "notes": forms.Textarea(attrs={"rows": 1})}

    def clean_pdf(self):
        f = self.cleaned_data.get("pdf")
        validate_upload(f, PDF_OR_IMAGE, 20 * 1024 * 1024)
        return f


class RetainerFormSet(forms.BaseInlineFormSet):
    """İlişkili dosya seçeneği yalnızca müvekkilin kendi dosyalarıdır."""

    def add_fields(self, form, index):
        super().add_fields(form, index)
        if "case" in form.fields:
            from apps.cases.models import Case

            cases = (
                Case.objects.filter(client=self.instance)
                if self.instance.pk
                else Case.objects.none()
            )
            form.fields["case"].queryset = cases
            form.fields["case"].empty_label = "Dosyaya bağlı değil"


# Müvekkil oluşturma/düzenleme ekranındaki alt kayıt grupları: önek -> (model, satır formu)
CLIENT_SUBRECORDS = {
    "iletisim": (ClientContact, ContactForm),
    "iban": (ClientIban, IbanForm),
    "yetkili": (ClientRepresentative, RepresentativeForm),
    "vekalet": (PowerOfAttorney, ClientPoaForm),
    "sozlesme": (RetainerAgreement, RetainerAgreementForm),
}


# İletişimde bu türler için boş satır her zaman ekranda hazır gelir.
DEFAULT_CONTACT_KINDS = ["phone", "email", "address"]


def client_formset(prefix: str, can_delete: bool, extra: int = 1):
    """Alt kayıt grubu. Mevcut satırı yalnızca yönetici silebilir."""
    model, form = CLIENT_SUBRECORDS[prefix]
    kwargs = {"formset": RetainerFormSet} if prefix == "sozlesme" else {}
    return forms.inlineformset_factory(
        Client, model, form=form, extra=extra, can_delete=can_delete, **kwargs
    )
