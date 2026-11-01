from decimal import Decimal

from django import forms
from django.db.models import Q
from django.utils import timezone

from apps.clients.models import Client, Party
from apps.core.forms import BootstrapMixin, DateInput, DateTimeInput
from apps.core.text import tr_upper
from apps.core.uploads import validate_upload

from . import stages
from .models import Case, CaseEvent, CaseParty, Document, Hearing, PartyRole
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

    def __init__(self, *args, can_remove_parties=False, related_case=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.related_case = related_case
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
            "Boşsa kurum adı ve dosya numarası kullanılır; bunlar yoksa konu kullanılır. "
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

    def _linked_case_ids(self) -> set:
        """Bu dosyayla bağlı (veya bağlanacak) dosyaların kimlikleri."""
        anchor = self.related_case or (self.instance if self.instance.pk else None)
        if anchor is None:
            return set()
        ids = {anchor.pk}
        if anchor.flow_id:
            ids |= set(Case.objects.filter(flow_id=anchor.flow_id).values_list("pk", flat=True))
        return ids

    def clean(self):
        data = super().clean()
        folder = data.get("archive_folder_no", "").strip()
        number = data.get("archive_no", "").strip()
        data["archive_folder_no"] = folder
        data["archive_no"] = number
        if number:
            same = set(
                Case.objects.filter(archive_folder_no__iexact=folder, archive_no__iexact=number)
                .exclude(pk=self.instance.pk)
                .values_list("pk", flat=True)
            )
            # Aynı hukuki olayın bağlı dosyaları aynı fiziki arşiv yerini paylaşabilir.
            if same - self._linked_case_ids():
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

    # "İlgili dosya oluştur" ile önceki dosyanın tarafı olduğu gibi aktarılırken kullanılır.
    existing_party = forms.IntegerField(required=False, widget=forms.HiddenInput())

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


class CaseLinkForm(BootstrapMixin, forms.Form):
    """Dosyaya başka bir dosya bağlar. İki dosyanın en az bir ortak müvekkili olmalıdır."""

    related = forms.ModelChoiceField(label="Bağlanacak dosya", queryset=Case.objects.none())
    note = forms.CharField(label="Not", required=False, widget=forms.Textarea(attrs={"rows": 2}))

    def __init__(self, *args, case, **kwargs):
        super().__init__(*args, **kwargs)
        self.case = case
        excluded = Case.objects.filter(pk=case.pk)
        if case.flow_id:
            excluded = Case.objects.filter(flow_id=case.flow_id) | excluded
        ids = case.client_ids()
        self.fields["related"].queryset = (
            Case.objects.filter(Q(client_id__in=ids) | Q(co_clients__in=ids))
            .exclude(pk__in=excluded.values("pk"))
            .select_related("client")
            .distinct()
            .order_by("-created_at")
        )
        self.fields["related"].label_from_instance = lambda c: (
            f"{c.archive_reference} · {c.display_name} · {c.client.name}"
        )
        self.fields["related"].empty_label = "Dosya seçin…"
        self.fields["related"].help_text = "En az bir ortak müvekkili olan dosyalar listelenir."


class CaseCoClientForm(BootstrapMixin, forms.Form):
    """Dosyadaki ek müvekkil satırı: müvekkil ve onun sıfatı (asıl müvekkil gibi)."""

    client = forms.ModelChoiceField(
        label="Müvekkil",
        queryset=Client.objects.all(),
        required=False,
        widget=forms.Select(attrs={"aria-label": "Müvekkil"}),
    )
    role = forms.ChoiceField(label="Müvekkilin sıfatı", required=False)

    def __init__(self, *args, case_type="civil", **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["role"].choices = [("", "Seçiniz…"), *PARTY_ROLES.get(case_type, [])]
        self.fields["role"].widget.attrs.update(
            {"data-party-role": "", "aria-label": "Müvekkilin sıfatı"}
        )

    def clean(self):
        data = super().clean()
        client, role = data.get("client"), data.get("role")
        if client and not role:
            self.add_error("role", "Müvekkilin sıfatını seçin.")
        if role and not client:
            self.add_error("client", "Müvekkili seçin.")
        return data


class BaseCoClientFormSet(forms.BaseFormSet):
    """Ek müvekkiller: asıl müvekkil tekrar eklenemez, aynı müvekkil bir kez yazılır.
    Görünüme `primary_id` ve (düzenlemede) `case` verilir."""

    primary_id = None
    case = None

    def clean(self):
        super().clean()
        if any(self.errors):
            return
        chosen = [f.cleaned_data["client"] for f in self.forms if f.cleaned_data.get("client")]
        ids = [c.pk for c in chosen]
        if self.primary_id and self.primary_id in ids:
            raise forms.ValidationError("Asıl müvekkil ek müvekkil olarak tekrar eklenemez.")
        if len(ids) != len(set(ids)):
            raise forms.ValidationError("Aynı müvekkil birden fazla kez eklenemiş.")
        if self.case is not None and self.case.pk:
            removed = self.case.co_clients.exclude(pk__in=ids)
            blocked = removed.filter(ledger_entries__case=self.case).distinct()
            if blocked.exists():
                names = ", ".join(c.name for c in blocked)
                raise forms.ValidationError(
                    f"Bu dosyada muhasebe hareketi olan müvekkil çıkarılamaz: {names}."
                )


CoClientFormSet = forms.formset_factory(
    CaseCoClientForm, formset=BaseCoClientFormSet, extra=0, max_num=20, validate_max=True
)
