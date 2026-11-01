import re
from decimal import Decimal

from django import forms
from django.utils import timezone

from apps.clients.models import Party
from apps.core.forms import BootstrapMixin, DateInput, DateTimeInput
from apps.core.text import tr_upper
from apps.core.uploads import validate_upload

from . import decisions, stages
from .models import Case, CaseEvent, CaseParty, CaseStep, Document, Hearing, PartyRole
from .party_roles import PARTY_ROLES


class CaseForm(BootstrapMixin, forms.ModelForm):
    official_year = forms.IntegerField(
        label="Yıl",
        min_value=1000,
        max_value=9999,
        required=False,
        widget=forms.TextInput(
            attrs={
                "inputmode": "numeric",
                "maxlength": "4",
                "pattern": "[0-9]{4}",
                "placeholder": "Yıl",
            }
        ),
    )
    official_sequence = forms.IntegerField(
        label="Numara", min_value=1, max_value=999999999999, required=False
    )

    class Meta:
        model = Case
        fields = [
            "client",
            "case_type",
            "archive_folder_no",
            "archive_no",
            "official_year",
            "official_sequence",
            "client_role",
            "authority",
            "subject",
            "enforcement_type",
            "crime",
            "mediator",
            "responsible_lawyer",
            "responsible_intern",
            "opened_on",
            "notes",
            "folder_name",
        ]
        widgets = {"opened_on": DateInput()}

    def __init__(self, *args, can_remove_parties=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["archive_folder_no"].required = not self.instance.pk
        self.fields["opened_on"].required = True
        for name in ("responsible_lawyer", "responsible_intern"):
            self.fields[name].required = False
        kind = (
            self.data.get("case_type")
            if self.is_bound
            else self.initial.get("case_type", self.instance.case_type or "civil")
        )
        self.fields["client_role"].choices = [("", "Seçiniz…"), *PARTY_ROLES.get(kind, [])]
        self.fields["client_role"].widget.attrs["data-party-role"] = ""
        self.fields["client_role"].required = True
        self.existing_party_rows = []
        if self.instance.pk:
            for link in self.instance.party_links.select_related("party"):
                name = f"party_role_{link.pk}"
                choices = list(PARTY_ROLES.get(kind, []))
                if kind == self.instance.case_type and link.role not in dict(choices):
                    choices.append((link.role, link.get_role_display()))
                self.fields[name] = forms.ChoiceField(
                    label="Taraf sıfatı",
                    choices=choices,
                    initial=link.role,
                    widget=forms.Select(attrs={"class": "form-select", "data-party-role": ""}),
                )
                self.existing_party_rows.append((link, self[name]))
                if can_remove_parties:
                    # Dosyadan çıkarma yalnızca yöneticide; kayıt tek hamlede işlenir.
                    remove_name = f"party_remove_{link.pk}"
                    self.fields[remove_name] = forms.BooleanField(required=False)
                    link.remove_field = self[remove_name]
        self.fields["authority"].widget.attrs["class"] += " text-uppercase-input"
        self.initial.setdefault("official_year", timezone.localdate().year)
        if self.instance.pk:
            import re

            match = re.fullmatch(r"([0-9]{4})/([0-9]+)", self.instance.official_no)
            if match:
                self.initial.update(official_year=int(match[1]), official_sequence=int(match[2]))
            elif self.instance.official_no:
                self.fields[
                    "official_sequence"
                ].help_text = f"Eski dosya numarası: {self.instance.official_no}"
        for name in ("authority", "official_year", "official_sequence"):
            self.fields[name].widget.attrs[":required"] = "Boolean(labels.authority)"
        self.fields["case_type"].widget.attrs["x-model"] = "caseType"
        self.fields["authority"].widget.attrs["list"] = "authority-options"
        self.fields["folder_name"].help_text = (
            "Boşsa dosya numarası, arşiv numarası ve konusuyla ayrı bir klasör oluşturulur. "
            "Kaydedilmiş klasörler taşınmaz."
        )
        self.fields["subject"].widget.attrs["class"] += " text-uppercase-input"
        # Avukat seçilince bağlı stajyeri (Ayarlar > Kullanıcılar) otomatik seçilir.
        self.fields["responsible_lawyer"].widget.attrs["@change"] = "lawyerChanged($event)"
        from apps.clients.views import intern_by_lawyer

        self.intern_map = intern_by_lawyer()

    def clean_client(self):
        client = self.cleaned_data["client"]
        if (
            self.instance.pk
            and client.pk != self.instance.client_id
            and (self.instance.tasks.exists() or self.instance.ledger_entries.exists())
        ):
            raise forms.ValidationError(
                "Bu dosyaya bağlı görev veya muhasebe hareketi var; müvekkili değiştirilemez."
            )
        return client

    def clean(self):
        data = super().clean()
        folder = data.get("archive_folder_no", "").strip()
        number = data.get("archive_no", "").strip()
        data["archive_folder_no"] = folder
        data["archive_no"] = number
        if (
            number
            and Case.objects.filter(archive_folder_no__iexact=folder, archive_no__iexact=number)
            .exclude(pk=self.instance.pk)
            .exists()
        ):
            self.add_error("archive_no", "Bu klasörde aynı dosya numarası zaten kullanılıyor.")
        client = data.get("client")
        if client:
            for name in ("responsible_lawyer", "responsible_intern"):
                if not data.get(name):
                    data[name] = getattr(client, name)
        case_type = data.get("case_type")
        if case_type not in ("consultancy", "other"):
            for name, label in (("official_year", "Yıl"), ("official_sequence", "Numara")):
                if data.get(name) is None and name not in self.errors:
                    self.add_error(name, f"{label} zorunludur.")
            if data.get("official_year") and data.get("official_sequence"):
                data["official_no"] = f"{data['official_year']}/{data['official_sequence']}"
                self.instance.official_no = data["official_no"]
        if data.get("authority"):
            data["authority"] = tr_upper(data["authority"]).strip()
        if case_type in ("consultancy", "other"):
            # Eski kayıtlardaki gizlenen bilgiler korunur.
            for name in ("authority", "official_no"):
                data[name] = getattr(self.instance, name)
        else:
            for name, label in (("authority", "Kurum adı"),):
                if not data.get(name):
                    self.add_error(name, f"{label} zorunludur.")
        if data.get("case_type") != "enforcement":
            data["enforcement_type"] = ""
        if data.get("case_type") not in ("criminal", "investigation"):
            data["crime"] = ""
        if data.get("case_type") != "mediation":
            data["mediator"] = ""
        return data


class CasePartyForm(BootstrapMixin, forms.ModelForm):
    """Dosyaya yeni karşı taraf ekler. Aynı kimlik no'lu kayıt varsa yeniden kullanılır."""

    role = forms.ChoiceField(label="taraf sıfatı", choices=PartyRole.choices)

    def __init__(self, *args, case_type="civil", **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["role"].choices = [("", "Seçiniz…"), *PARTY_ROLES.get(case_type, [])]
        self.fields["role"].widget.attrs["data-party-role"] = ""

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
        validate_upload(f)
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


class CaseEventForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = CaseEvent
        fields = ["date", "title", "description"]
        widgets = {"date": DateInput(), "description": forms.Textarea(attrs={"rows": 1})}


class CasePartyFormSet(forms.BaseFormSet):
    def clean(self):
        super().clean()
        if any(self.errors):
            return
        identities = [
            f.cleaned_data.get("identity_no")
            for f in self.forms
            if f.cleaned_data and not f.cleaned_data.get("DELETE")
        ]
        identities = [value for value in identities if value]
        if len(identities) != len(set(identities)):
            raise forms.ValidationError(
                "Aynı kimlik numarası birden fazla taraf satırında kullanılamaz."
            )


PartyFormSet = forms.formset_factory(
    CasePartyForm, formset=CasePartyFormSet, extra=0, max_num=50, validate_max=True, can_delete=True
)


class CaseStageForm(forms.Form):
    stage = forms.ChoiceField(label="Aşama")

    def __init__(self, *args, case, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["stage"].choices = stages.open_stages(case.case_type)
        self.fields["stage"].widget.attrs["class"] = "form-select"
        self.fields["stage"].widget.attrs["aria-label"] = "Aşama"
        self.initial.setdefault("stage", case.stage)


class CaseCloseForm(BootstrapMixin, forms.Form):
    """Dosyayı kapatır. Karar ve tutar alanları türe ve kapanma nedenine göre istenir."""

    closing_reason = forms.ChoiceField(label="Kapanma nedeni")
    closed_on = forms.DateField(label="Kapanış tarihi", widget=DateInput())
    closing_note = forms.CharField(
        label="Not", required=False, widget=forms.Textarea(attrs={"rows": 3})
    )
    decision_date = forms.DateField(label="Karar tarihi", required=False, widget=DateInput())
    decision_year = forms.IntegerField(
        label="Karar yılı",
        min_value=1000,
        max_value=9999,
        required=False,
        widget=forms.TextInput(
            attrs={
                "inputmode": "numeric",
                "maxlength": "4",
                "pattern": "[0-9]{4}",
                "placeholder": "Yıl",
            }
        ),
    )
    decision_sequence = forms.IntegerField(
        label="Karar numarası", min_value=1, max_value=999999999, required=False
    )
    closing_amount = forms.DecimalField(
        label="Tahsil / ödeme tutarı (TL)",
        required=False,
        min_value=Decimal("0.01"),
        max_digits=16,
        decimal_places=2,
    )
    closing_amount_date = forms.DateField(
        label="Tahsil / ödeme tarihi", required=False, widget=DateInput()
    )
    closing_accounted = forms.TypedChoiceField(
        label="Bu tutar muhasebeye kaydedildi mi?",
        required=False,
        choices=[("", "Seçiniz…"), ("1", "Evet, kaydedildi"), ("0", "Hayır, henüz kaydedilmedi")],
        coerce=lambda value: value == "1",
        empty_value=None,
    )

    def __init__(self, *args, case, **kwargs):
        super().__init__(*args, **kwargs)
        self.case = case
        reasons = stages.closing_reasons(case.case_type)
        self.fields["closing_reason"].choices = [
            ("", "Seçiniz…"),
            *((c.key, c.label) for c in reasons),
        ]
        self.initial.setdefault("closed_on", timezone.localdate())
        self.initial.setdefault("decision_year", timezone.localdate().year)
        self.has_decision = case.case_type in stages.DECISION_TYPES
        if not self.has_decision:
            del self.fields["decision_date"], self.fields["decision_year"]
            del self.fields["decision_sequence"]
        # Alanların hangi kapanma nedeninde görüneceğini sayfadaki betik bu haritadan okur.
        self.flags = {c.key: c.flags for c in reasons}

    def clean(self):
        data = super().clean()
        year, sequence = data.get("decision_year"), data.get("decision_sequence")
        # Yıl varsayılan olarak dolu gelir; numara boşsa karar numarası girilmemiş sayılır.
        if sequence and not year:
            self.add_error("decision_year", "Karar numarası için yıl girilmelidir.")
        data["decision_no"] = f"{year}/{sequence}" if year and sequence else ""
        reason = data.get("closing_reason")
        if not reason:
            return data
        flags = self.flags.get(reason, "")
        if "n" in flags and not data.get("closing_note", "").strip():
            self.add_error("closing_note", "Bu kapanma nedeninde açıklama yazılmalıdır.")
        if "m" not in flags:
            data["closing_amount"] = data["closing_amount_date"] = None
            data["closing_accounted"] = None
        elif data.get("closing_amount"):
            if not data.get("closing_amount_date"):
                self.add_error("closing_amount_date", "Tutar girildiyse tarih de girilmelidir.")
            if data.get("closing_accounted") is None:
                self.add_error("closing_accounted", "Muhasebeye kaydedilip kaydedilmediğini seçin.")
        elif data.get("closing_amount_date"):
            self.add_error("closing_amount", "Tarih girildiyse tutar da girilmelidir.")
        return data


YEAR_WIDGET = {"inputmode": "numeric", "maxlength": "4", "pattern": "[0-9]{4}"}


class CaseStepForm(BootstrapMixin, forms.ModelForm):
    """Safahat adımı. Dosya ve karar numaraları yıl + numara olarak girilir."""

    official_year = forms.IntegerField(
        label="Yıl",
        min_value=1000,
        max_value=9999,
        required=False,
        widget=forms.TextInput(attrs={**YEAR_WIDGET, "placeholder": "Yıl"}),
    )
    official_sequence = forms.IntegerField(
        label="Numara", min_value=1, max_value=999999999, required=False
    )
    decision_year = forms.IntegerField(
        label="Yıl",
        min_value=1000,
        max_value=9999,
        required=False,
        widget=forms.TextInput(attrs={**YEAR_WIDGET, "placeholder": "Yıl"}),
    )
    decision_sequence = forms.IntegerField(
        label="Numara", min_value=1, max_value=999999999, required=False
    )
    decision = forms.ChoiceField(label="Karar", choices=[], widget=forms.Select())
    apply_to_case = forms.BooleanField(
        label="Esas dosyadaki kurum adı ve dosya numarasını bu adıma göre güncelle",
        required=False,
    )

    class Meta:
        model = CaseStep
        fields = ["authority", "decision_date", "decision", "note"]
        labels = {"decision_date": "Karar tarihi", "decision": "Karar", "note": "Not"}
        widgets = {"decision_date": DateInput(), "note": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *args, case, **kwargs):
        super().__init__(*args, **kwargs)
        self.case = case
        self.fields["decision"].choices = [
            ("", "Seçiniz…"),
            *decisions.decisions_for(case.case_type),
        ]
        self.fields["authority"].widget.attrs["class"] += " text-uppercase-input"
        self.fields["authority"].widget.attrs["list"] = "authority-options"
        year = timezone.localdate().year
        self.initial.setdefault("official_year", year)
        self.initial.setdefault("decision_year", year)
        if self.instance.pk:
            for prefix, value in (
                ("official", self.instance.official_no),
                ("decision", self.instance.decision_no),
            ):
                match = re.fullmatch(r"([0-9]{4})/([0-9]+)", value or "")
                if match:
                    self.initial[f"{prefix}_year"] = int(match[1])
                    self.initial[f"{prefix}_sequence"] = int(match[2])
                elif value:
                    self.initial[f"{prefix}_year"] = None

    def clean(self):
        data = super().clean()
        for prefix, label in (("official", "Dosya numarası"), ("decision", "Karar numarası")):
            if data.get(f"{prefix}_sequence") and not data.get(f"{prefix}_year"):
                self.add_error(f"{prefix}_year", f"{label} için yıl girilmelidir.")
        if data.get("decision") == "other" and not (data.get("note") or "").strip():
            self.add_error("note", 'Karar "Diğer" ise açıklama yazılmalıdır.')
        return data

    def save(self, commit=True):
        step = super().save(commit=False)
        year, seq = (
            self.cleaned_data.get("official_year"),
            self.cleaned_data.get("official_sequence"),
        )
        step.official_no = f"{year}/{seq}" if year and seq else ""
        year, seq = (
            self.cleaned_data.get("decision_year"),
            self.cleaned_data.get("decision_sequence"),
        )
        step.decision_no = f"{year}/{seq}" if year and seq else ""
        if commit:
            step.save()
        return step
