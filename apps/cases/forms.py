from decimal import Decimal

from django import forms
from django.db.models import Q
from django.utils import timezone

from apps.clients.models import Client, Party
from apps.core.forms import BootstrapMixin, DateInput, DateTimeInput
from apps.core.text import tr_upper
from apps.core.uploads import validate_upload
from apps.imports.portal_forms import PreserveExistingAssigneeMixin

from . import stages
from .models import (
    Case,
    CaseEvent,
    CaseParty,
    CaseStatus,
    Document,
    Hearing,
    PartyRole,
    Seizure,
)
from .party_roles import PARTY_ROLES


class CaseForm(PreserveExistingAssigneeMixin, BootstrapMixin, forms.ModelForm):
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
                "@input": r"$el.value = $el.value.replace(/\D/g, '')",
            }
        ),
    )
    official_sequence = forms.IntegerField(
        label="Numara",
        min_value=1,
        max_value=999999999999,
        required=False,
        widget=forms.TextInput(
            attrs={
                "inputmode": "numeric",
                "pattern": "[0-9]*",
                "maxlength": "12",
                "placeholder": "Sıra No",
                "@input": r"$el.value = $el.value.replace(/\D/g, '')",
            }
        ),
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
            "official_no_kind",
            "official_date",
            "notice_service_no",
            "notice_served",
            "notice_served_on",
            "client_role",
            "authority",
            "subject",
            "enforcement_type",
            "enforcement_basis",
            "enforcement_amount",
            "crime",
            "mediator",
            "responsible_lawyer",
            "responsible_intern",
            "opened_on",
            "notes",
            "folder_name",
        ]
        widgets = {
            "opened_on": DateInput(),
            "official_date": DateInput(),
            "notice_served_on": DateInput(),
        }

    def __init__(self, *args, can_remove_parties=False, related_case=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.keep_existing_assignee()
        self.related_case = related_case
        self.has_uyap = bool(self.instance.pk and getattr(self.instance, "portalcase", None))
        imported = bool(
            self.instance.pk and (self.instance.office_sources.exists() or self.has_uyap)
        )
        self.imported_incomplete = imported
        self.fields["client"].required = True
        self.fields["archive_folder_no"].required = not self.instance.pk
        self.fields["archive_no"].required = not self.instance.pk
        self.fields["subject"].required = not self.instance.pk
        self.fields["official_no_kind"].required = False
        self.fields["official_date"].required = False
        self.fields["official_date"].label = "Tarih"
        self.fields["official_no_kind"].initial = "esas"
        self.fields["opened_on"].required = True
        if imported:
            for name in ("archive_no", "opened_on", "subject", "client_role"):
                if not getattr(self.instance, name):
                    self.fields[name].required = False
        self.fields["client"].widget.attrs["data-searchable"] = "Müvekkil ara"
        self.fields["enforcement_amount"].min_value = Decimal("0")
        self.fields["enforcement_basis"].widget.attrs["rows"] = 2
        from apps.office.models import OfficeSettings

        self.use_assistant = OfficeSettings.load().use_assistant_assignee
        for name in ("responsible_lawyer", "responsible_intern"):
            self.fields[name].required = False
        if not self.use_assistant:
            self.fields.pop("responsible_intern", None)
        kind = (
            (self.data.get("case_type") if (self.is_bound and self.data.get("case_type")) else None)
            or getattr(self.instance, "case_type", None)
            or self.initial.get("case_type")
            or "civil"
        )
        client_choices = [("", "Seçiniz…"), *PARTY_ROLES.get(kind, [])]
        if self.instance.client_role and self.instance.client_role not in dict(client_choices):
            client_choices.append(
                (self.instance.client_role, self.instance.get_client_role_display())
            )
        self.fields["client_role"].choices = client_choices
        self.fields["client_role"].widget.attrs["data-party-role"] = ""
        self.fields["client_role"].required = not (imported and not self.instance.client_role)
        self.existing_party_rows = []
        if self.instance.pk:
            for link in self.instance.party_links.select_related("party"):
                name = f"party_role_{link.pk}"
                choices = list(PARTY_ROLES.get(kind, []))
                if link.role and link.role not in dict(choices):
                    choices.append((link.role, link.get_role_display()))
                self.fields[name] = forms.ChoiceField(
                    label="Taraf sıfatı",
                    choices=choices,
                    initial=link.role,
                    disabled=link.from_uyap,
                    required=not link.from_uyap,
                    widget=forms.Select(attrs={"class": "form-select", "data-party-role": ""}),
                )
                self.existing_party_rows.append((link, self[name]))
                if can_remove_parties and not link.from_uyap:
                    # Dosyadan çıkarma yalnızca yöneticide; UYAP tarafları salt okunurdur.
                    remove_name = f"party_remove_{link.pk}"
                    self.fields[remove_name] = forms.BooleanField(required=False)
                    link.remove_field = self[remove_name]
        self.fields["authority"].widget.attrs["class"] += " text-uppercase-input"
        if not imported:
            self.initial.setdefault("official_year", timezone.localdate().year)
        if self.instance.pk:
            import re

            match = re.fullmatch(r"([0-9]{4})/([0-9]+)", self.instance.official_no)
            if match:
                self.initial.update(official_year=int(match[1]), official_sequence=int(match[2]))
            elif self.instance.case_type == "notice" and self.instance.official_no.isdigit():
                self.initial.update(
                    official_year=None, official_sequence=int(self.instance.official_no)
                )
            elif self.instance.official_no:
                self.fields[
                    "official_sequence"
                ].help_text = f"Eski dosya numarası: {self.instance.official_no}"
        for name in ("authority", "official_year", "official_sequence"):
            if not imported:
                self.fields[name].widget.attrs[":required"] = (
                    "Boolean(labels.authority) && caseType !== 'notice'"
                    if name == "official_year"
                    else "Boolean(labels.authority)"
                )
        if imported and not self.instance.authority:
            self.fields["authority"].required = False
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
        if self.has_uyap:
            # UYAP'tan gelen alanlar (tarihler dahil) salt okunurdur; kullanıcı değiştiremez.
            for name in (
                "case_type",
                "opened_on",
                "authority",
                "official_year",
                "official_sequence",
                "official_no_kind",
                "enforcement_type",
                "enforcement_amount",
                "mediator",
            ):
                self.fields[name].disabled = True
                self.fields[name].required = False

    def clean_client(self):
        client = self.cleaned_data["client"]
        if (
            self.instance.pk
            and self.instance.client_id
            and client
            and client.pk != self.instance.client_id
            and (self.instance.tasks.exists() or self.instance.ledger_entries.exists())
        ):
            raise forms.ValidationError(
                "Bu dosyaya bağlı görev veya muhasebe hareketi var; müvekkili değiştirilemez."
            )
        return client

    def clean_enforcement_amount(self):
        amount = self.cleaned_data.get("enforcement_amount")
        if amount is not None and amount < 0:
            raise forms.ValidationError("Miktar negatif olamaz.")
        return amount

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
                if name == "responsible_intern" and not getattr(self, "use_assistant", True):
                    continue
                if not data.get(name):
                    data[name] = getattr(client, name)
        case_type = data.get("case_type")
        if case_type not in ("consultancy", "other"):
            for name, label in (("official_year", "Yıl"), ("official_sequence", "Numara")):
                if case_type == "notice" and name == "official_year":
                    continue  # İhtarnamede yıl yok, yalnızca yevmiye numarası girilir.
                empty_pair = not data.get("official_year") and not data.get("official_sequence")
                if (
                    data.get(name) is None
                    and name not in self.errors
                    and not (self.imported_incomplete and empty_pair)
                ):
                    self.add_error(name, f"{label} zorunludur.")
            if case_type == "notice":
                if not data.get("official_date") and not (
                    self.instance.pk and not self.instance.official_date
                ):
                    self.add_error("official_date", "Tarih zorunludur.")
                if data.get("official_sequence"):
                    data["official_no"] = str(data["official_sequence"])
                    self.instance.official_no = data["official_no"]
            elif data.get("official_year") and data.get("official_sequence"):
                data["official_no"] = f"{data['official_year']}/{data['official_sequence']}"
                self.instance.official_no = data["official_no"]
        if case_type != "notice":
            data["official_date"] = None
            data["notice_service_no"] = ""
            data["notice_served"] = False
        if case_type != "notice" or not data.get("notice_served"):
            data["notice_served_on"] = None
        if case_type not in ("civil", "criminal", "administrative") or not data.get(
            "official_no_kind"
        ):
            data["official_no_kind"] = "esas"
        if data.get("authority"):
            data["authority"] = tr_upper(data["authority"]).strip()
        if case_type in ("consultancy", "other"):
            # Eski kayıtlardaki gizlenen bilgiler korunur.
            for name in ("authority", "official_no"):
                data[name] = getattr(self.instance, name)
        else:
            for name, label in (("authority", "Kurum adı"),):
                if not data.get(name) and not (
                    self.imported_incomplete and not getattr(self.instance, name)
                ):
                    self.add_error(name, f"{label} zorunludur.")
        if data.get("case_type") != "enforcement":
            data["enforcement_type"] = ""
            data["enforcement_basis"] = self.instance.enforcement_basis
            data["enforcement_amount"] = self.instance.enforcement_amount
        if data.get("case_type") not in ("criminal", "investigation"):
            data["crime"] = ""
        if data.get("case_type") != "mediation":
            data["mediator"] = ""
        if self.has_uyap:
            for name in (
                "case_type",
                "opened_on",
                "authority",
                "official_no",
                "official_no_kind",
                "enforcement_type",
                "enforcement_amount",
                "mediator",
            ):
                data[name] = getattr(self.instance, name)
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


class HearingStandaloneForm(BootstrapMixin, forms.ModelForm):
    case = forms.ModelChoiceField(
        label="Dosya",
        queryset=Case.objects.none(),
        required=False,
        widget=forms.Select(
            attrs={"data-searchable": "true", "data-placeholder": "Dosya seçin (isteğe bağlı)..."}
        ),
    )
    client = forms.ModelChoiceField(
        label="Müvekkil",
        queryset=Client.objects.all(),
        required=False,
        widget=forms.Select(
            attrs={"data-searchable": "true", "data-placeholder": "Müvekkil seçin..."}
        ),
    )

    class Meta:
        model = Hearing
        fields = [
            "title",
            "kind",
            "case",
            "client",
            "assigned_to",
            "starts_at",
            "ends_at",
            "authority",
            "room",
            "notes",
        ]
        widgets = {
            "starts_at": DateTimeInput(),
            "ends_at": DateTimeInput(),
            "notes": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.core.permissions import filter_visible_cases

        qs = Case.objects.filter(status=CaseStatus.OPEN).select_related("client")
        if user:
            qs = filter_visible_cases(qs, user)
        self.fields["case"].queryset = qs

        def _label(obj):
            client_name = obj.client.name if obj.client else "Müvekkilsiz"
            return f"{obj.archive_reference or '-'} · {obj.display_name} · {client_name}"

        self.fields["case"].label_from_instance = _label

    def clean(self):
        cleaned_data = super().clean()
        case = cleaned_data.get("case")
        client = cleaned_data.get("client")
        title = cleaned_data.get("title")

        if case and not client:
            cleaned_data["client"] = case.client

        if not case and not client and not title:
            raise forms.ValidationError(
                "Lütfen bir dosya, müvekkil veya etkinlik başlığı belirtiniz."
            )
        return cleaned_data


class HearingResultForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = Hearing
        fields = ["status", "result"]
        widgets = {"result": forms.Textarea(attrs={"rows": 2})}


class HearingTaskCreateForm(BootstrapMixin, forms.ModelForm):
    excuse_submitted = forms.BooleanField(
        label="Mazeret sunulacak",
        required=False,
        help_text=(
            "Bu duruşmaya mazeret sunulacaksa işaretleyin "
            "(Google Takvim'e ve ajandaya Mazeret olarak yansır)."
        ),
    )
    client = forms.ModelChoiceField(
        label="Müvekkil",
        queryset=Client.objects.all(),
        required=False,
    )
    case = forms.ModelChoiceField(
        label="Dosya",
        queryset=Case.objects.exclude(status=CaseStatus.CLOSED),
        required=False,
    )

    class Meta:
        from apps.tasks.models import Task

        model = Task
        fields = [
            "task_type",
            "title",
            "case",
            "assignee",
            "reviewer",
            "due_date",
            "notes",
        ]
        widgets = {
            "due_date": DateInput(),
            "notes": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, hearing=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.hearing = hearing
        self.fields["assignee"].required = True
        self.fields["reviewer"].required = False
        self.fields["reviewer"].empty_label = "Kontrolcü yok (Doğrudan kapanır)"
        self.fields["title"].widget.attrs["class"] += " text-uppercase-input"
        if hearing:
            self.initial.setdefault("excuse_submitted", hearing.excuse_submitted)

    def clean(self):
        cleaned_data = super().clean()
        case = cleaned_data.get("case")
        client = cleaned_data.get("client")
        if case and case.client:
            cleaned_data["client"] = case.client
        elif case and not case.client:
            self.add_error(
                "case", "Bu dosyanın müvekkili henüz seçilmemiş. Önce dosyadan müvekkil seçin."
            )
        elif not case and not client:
            self.add_error("client", "Müvekkil seçimi zorunludur.")

        a = cleaned_data.get("assignee")
        r = cleaned_data.get("reviewer")
        if a and r and a == r:
            self.add_error("reviewer", "Kontrolcü, sorumludan farklı biri olmalı.")
        return cleaned_data


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
        if not self.fields["stage"].choices:
            self.fields["stage"].required = False
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
        self.is_enforcement = case.case_type == "enforcement"
        if self.is_enforcement:
            for name in ("closing_amount", "closing_amount_date", "closing_accounted"):
                del self.fields[name]
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
        if self.is_enforcement:
            return data
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
        if ids:
            qs = Case.objects.filter(
                Q(client_id__in=ids) | Q(co_clients__in=ids) | Q(client__isnull=True)
            )
            help_text = "Ortak müvekkili olan veya henüz müvekkili seçilmemiş dosyalar listelenir."
        else:
            qs = Case.objects.all()
            help_text = "Henüz müvekkil seçilmediği için tüm dosyalar listelenir."
        self.fields["related"].queryset = (
            qs.exclude(pk__in=excluded.values("pk"))
            .select_related("client")
            .distinct()
            .order_by("-created_at")
        )
        self.fields["related"].label_from_instance = lambda c: (
            f"{c.archive_reference} · {c.display_name} · "
            f"{c.client.name if c.client_id else 'Müvekkil eksik'}"
        )
        self.fields["related"].empty_label = "Dosya seçin…"
        self.fields["related"].help_text = help_text


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


class ClosingCollectionForm(BootstrapMixin, forms.Form):
    amount = forms.DecimalField(
        label="Tahsilat tutarı (TL)", min_value=Decimal("0.01"), max_digits=16, decimal_places=2
    )
    date = forms.DateField(label="Tahsilat tarihi", widget=DateInput())
    description = forms.CharField(label="Açıklama", max_length=300, required=False)


class ClosingCollectionFormSet(forms.BaseFormSet):
    def clean(self):
        super().clean()
        if any(self.errors):
            return
        total = sum(
            row.cleaned_data.get("amount", Decimal("0"))
            for row in self.forms
            if row.cleaned_data and not row.cleaned_data.get("DELETE")
        )
        if total > Decimal("99999999999999.99"):
            raise forms.ValidationError("Tahsilat toplamı izin verilen tutarı aşıyor.")


CollectionFormSet = forms.formset_factory(
    ClosingCollectionForm,
    formset=ClosingCollectionFormSet,
    extra=1,
    can_delete=True,
    max_num=100,
    validate_max=True,
    absolute_max=100,
)


class SeizureForm(BootstrapMixin, forms.ModelForm):
    debtor = forms.ChoiceField(label="Borçlu", choices=[])
    state = forms.ChoiceField(label="Durum", choices=[])

    class Meta:
        model = Seizure
        fields = [
            "debtor",
            "kind",
            "state",
            "employer",
            "bank_name",
            "plate",
            "property_info",
            "address",
            "notice_stage",
            "recipient",
            "related_case_info",
            "seized_on",
            "renewal_on",
            "is_active",
            "notes",
        ]
        widgets = {
            "seized_on": DateInput(),
            "renewal_on": DateInput(),
            "address": forms.Textarea(attrs={"rows": 2}),
            "notes": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        from . import seizure_types

        super().__init__(*args, **kwargs)
        self.case = self.instance.case
        self.borrowers = {}
        for link in self.case.party_links.filter(role="debtor").select_related("party"):
            self.borrowers[f"party:{link.party_id}"] = ("party", link.party)
        if self.case.client_id and self.case.client_role == "debtor":
            self.borrowers[f"client:{self.case.client_id}"] = ("client", self.case.client)
        for link in self.case.co_client_links.filter(role="debtor").select_related("client"):
            self.borrowers[f"client:{link.client_id}"] = ("client", link.client)
        self.fields["debtor"].choices = [
            ("", "Seçiniz…"),
            *[(key, record.name) for key, (_, record) in self.borrowers.items()],
        ]
        if self.instance.debtor_party_id:
            self.initial["debtor"] = f"party:{self.instance.debtor_party_id}"
        elif self.instance.debtor_client_id:
            self.initial["debtor"] = f"client:{self.instance.debtor_client_id}"
        else:
            self.initial["debtor"] = ""
        self.fields["kind"].required = True
        kind = (
            self.data.get("kind", "")
            if self.is_bound
            else self.initial.get("kind", self.instance.kind)
        )
        state = self.data.get("state", "") if self.is_bound else self.instance.state
        self.fields["state"].choices = [("", "Seçiniz…"), *seizure_types.STATES.get(kind, [])]
        self.fields["seized_on"].required = state in seizure_types.SEIZED_STATES
        self.fields["bank_name"].label = "Banka adı"
        self.fields["plate"].label = "Plaka (tek araç)"
        self.fields["property_info"].label = "Taşınmaz bilgisi (il, ilçe, ada/parsel)"
        self.fields["related_case_info"].label = "Alacaklı olduğu dosya (kurum ve numara)"
        self.fields["employer"].label = "İşveren / işyeri (varsa)"
        self.fields["recipient"].label = "İhbarname muhatabı (varsa)"
        self.fields["notice_stage"].required = kind == "notice"
        self.fields["debtor"].widget.attrs["x-model"] = "debtor"
        self.fields["kind"].widget.attrs["x-model"] = "kind"
        self.fields["state"].widget.attrs.update({"x-model": "state", "x-ref": "state"})
        self.fields["seized_on"].widget.attrs.update(
            {"x-model": "seized", ":required": "hasSeizure"}
        )
        self.fields["renewal_on"].widget.attrs.update(
            {"x-model": "renewal", ":required": "annualRenewal"}
        )
        for field in (
            "bank_name",
            "plate",
            "property_info",
            "address",
            "notice_stage",
            "related_case_info",
        ):
            self.fields[field].widget.attrs[":required"] = f"requiredDetail('{field}')"
        self.config = {
            "states": seizure_types.STATES,
            "seized_states": sorted(seizure_types.SEIZED_STATES),
            "renewal_states": sorted(seizure_types.RENEWAL_STATES),
            "kind": kind,
            "state": state,
            "debtor": self.data.get("debtor", "") if self.is_bound else self.initial["debtor"],
            "seized": self["seized_on"].value(),
            "renewal": self["renewal_on"].value(),
        }
        for key in ("seized", "renewal"):
            value = self.config[key]
            self.config[key] = value.isoformat() if hasattr(value, "isoformat") else (value or "")

    def clean_bank_name(self):
        value = self.cleaned_data.get("bank_name", "")
        if value and any(not name.strip() for name in value.split(",")):
            raise forms.ValidationError("Banka adlarını virgülle ayırın; boş ad bırakmayın.")
        return value

    def clean(self):
        import re

        from . import seizure_types

        data = super().clean()
        selected = self.borrowers.get(data.get("debtor"))
        if selected:
            category, record = selected
            data["debtor"] = record.name
            self.instance.debtor_party = record if category == "party" else None
            self.instance.debtor_client = record if category == "client" else None
        kind, state = data.get("kind"), data.get("state")
        if kind not in dict(seizure_types.KINDS):
            return data
        for field in set().union(*seizure_types.DETAIL_FIELDS.values()):
            if field not in seizure_types.DETAIL_FIELDS[kind]:
                data[field] = ""
        if state in {"vehicle_none", "property_none", "claim_none"}:
            for field in seizure_types.DETAIL_FIELDS[kind]:
                data[field] = ""
        if state not in seizure_types.SEIZED_STATES:
            data["seized_on"] = None
        if state not in seizure_types.RENEWAL_STATES:
            data["renewal_on"] = None
        elif (
            kind in {"vehicle", "property"} and data.get("seized_on") and not data.get("renewal_on")
        ):
            data["renewal_on"] = seizure_types.suggested_renewal(data["seized_on"])
        if kind == "bank" and any(
            separator in data.get("bank_name", "") for separator in (";", "\n", "\r")
        ):
            self.add_error("bank_name", "Banka adlarını virgülle ayırın.")
        if kind == "vehicle" and state != "vehicle_none":
            plate = data.get("plate", "").upper().replace("İ", "I").strip()
            data["plate"] = re.sub(r"\s+", " ", plate)
            if (
                any(separator in plate for separator in (",", ";", "/", "\n", "\r"))
                or len(re.findall(r"\b\d{2}\s*[A-Z]{1,3}\s*\d{1,4}\b", plate)) > 1
            ):
                self.add_error("plate", "Her araç için ayrı kayıt açıp tek plaka girin.")
        return data
