from decimal import Decimal

from django import forms
from django.db.models import Q
from django.utils import timezone

from apps.accounts.models import User
from apps.clients.models import Client, Party
from apps.core.forms import BootstrapMixin, DateInput, DateTimeInput
from apps.core.text import tr_upper
from apps.core.uploads import validate_upload
from apps.imports.portal_forms import PreserveExistingAssigneeMixin

from . import stages
from .archive_categories import category_for_case, natural_sort_key, validate_case_placement
from .archive_locations import available_archive_slots, validate_archive_location
from .models import (
    LIST_KINDS,
    RESULT_KINDS,
    ArchiveCategory,
    ArchiveFolder,
    Case,
    CaseEvent,
    CaseParty,
    CaseStatus,
    Document,
    Hearing,
    HearingKind,
    PartyRole,
    Seizure,
)
from .party_roles import PARTY_ROLES


class ArchiveFolderForm(BootstrapMixin, forms.Form):
    category = forms.ModelChoiceField(label="Klasör türü", queryset=ArchiveCategory.objects.all())
    physical_state = forms.ChoiceField(
        label="Fiziki durum", choices=ArchiveFolder.PhysicalState.choices
    )
    capacity = forms.IntegerField(label="Kapasite", min_value=1, max_value=32767)

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        categories = ArchiveCategory.objects.filter(
            Q(client__isnull=True) | Q(client__physical_archive_enabled=True)
        )
        if user is not None:
            from apps.clients.models import Client
            from apps.core.permissions import filter_visible_clients

            categories = categories.filter(
                Q(client__isnull=True)
                | Q(client__in=filter_visible_clients(Client.objects.all(), user))
            )
        self.fields["category"].queryset = categories
        self.fields["category"].widget.attrs["data-folder-category"] = ""
        self.fields["physical_state"].widget.attrs["data-folder-state"] = ""

    def clean(self):
        data = super().clean()
        category, state = data.get("category"), data.get("physical_state")
        if category and state:
            valid = state in ("open", "closed") if category.tracks_state else state == "single"
            if not valid:
                self.add_error("physical_state", "Bu tür için geçerli bir durum seçin.")
        return data


class ArchiveCategoryForm(BootstrapMixin, forms.Form):
    name = forms.CharField(label="Klasör türü adı", max_length=320)
    capacity = forms.IntegerField(label="İlk klasörlerin kapasitesi", min_value=1, max_value=32767)
    tracks_state = forms.BooleanField(
        label="Açık / kapalı ayrımı kullan", required=False, initial=True
    )
    is_client_specific = forms.BooleanField(label="Müvekkile özel klasör türü", required=False)
    client = forms.ModelChoiceField(
        label="İlgili Müvekkil",
        queryset=Client.objects.all().order_by("name"),
        required=False,
        help_text="Bu klasör türü belirli bir müvekkile mi ait?",
    )

    def clean(self):
        data = super().clean()
        is_client = data.get("is_client_specific")
        client = data.get("client")
        if is_client and not client:
            self.add_error("client", "Müvekkile özel klasör türü için lütfen müvekkil seçin.")
        elif is_client and client:
            if ArchiveCategory.objects.filter(client=client).exists():
                self.add_error(
                    "client",
                    "Bu müvekkilin zaten tanımlı özel bir fiziki klasör türü bulunmaktadır.",
                )
        else:
            data["client"] = None
        return data

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        for prefix in ("Açık ", "Kapalı ", "açık ", "kapalı "):
            if name.startswith(prefix):
                name = name[len(prefix) :].strip()
                break
        if not name or "/" in name or "\\" in name:
            raise forms.ValidationError("Geçerli bir tür adı girin; / ve \\ kullanmayın.")
        if len(f"Kapalı {name} 1") > 340:
            raise forms.ValidationError("Tür adı çok uzun.")
        if ArchiveCategory.objects.filter(name__iexact=name).exists():
            raise forms.ValidationError("Bu klasör türü zaten var.")
        return name


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

    def __init__(self, *args, can_remove_parties=False, related_case=None, user=None, **kwargs):
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
        if user is not None:
            from apps.core.permissions import filter_visible_clients

            self.fields["client"].queryset = filter_visible_clients(
                self.fields["client"].queryset, user
            )
        selected_client = (
            self.data.get("client", "")
            if self.is_bound
            else self.initial.get("client", self.instance.client_id)
        )
        selected_client = getattr(selected_client, "pk", selected_client) or ""
        names = list(
            ArchiveFolder.objects.filter(is_active=True)
            .filter(
                Q(category__client__isnull=True)
                | Q(category__client_id=selected_client if str(selected_client).isdigit() else None)
            )
            .values_list("name", flat=True)
        )
        names.sort(key=natural_sort_key)
        if (
            self.instance.pk
            and self.instance.archive_folder_no
            and self.instance.archive_folder_no not in names
        ):
            names.append(self.instance.archive_folder_no)
        selected_folder = (
            self.data.get("archive_folder_no", "")
            if self.is_bound
            else self.initial.get("archive_folder_no", self.instance.archive_folder_no)
        )
        slots, folder = available_archive_slots(
            selected_folder or "", self.instance, client_id=selected_client
        )
        self.fields["archive_folder_no"].widget = forms.Select(
            choices=[("", "Klasör seçiniz…"), *((name, name) for name in names)],
            attrs={
                "class": "form-select",
                "data-archive-folder": "",
                "data-searchable": "Klasör ara…",
                "data-case-id": self.instance.pk or "",
                "data-client-id": selected_client,
            },
        )
        self.fields["archive_folder_no"].help_text = "Kayıtlı fiziki klasörlerden birini seçin."
        self.fields["archive_no"].widget = forms.Select(
            choices=[("", "Boş yer seçiniz…"), *((slot, slot) for slot in slots)],
            attrs={"class": "form-select", "data-archive-slot": ""},
        )
        self.fields["archive_no"].help_text = (
            "Klasör kapasitesi belirlenmeli."
            if folder and folder.capacity is None
            else "Yalnızca boş numaralar listelenir."
        )
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
        self.fields["client"].widget.attrs["data-archive-client"] = ""
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

    def clean(self):
        data = super().clean()
        folder = data.get("archive_folder_no", "").strip()
        number = data.get("archive_no", "").strip()
        data["archive_folder_no"] = folder
        data["archive_no"] = number
        try:
            selected_client = data.get("client")
            validate_archive_location(
                folder,
                number,
                self.instance,
                client_id=selected_client.pk if selected_client else "",
            )
            if (
                number
                and number.isascii()
                and number.isdigit()
                and ArchiveFolder.objects.filter(
                    name__iexact=folder, capacity__isnull=False
                ).exists()
            ):
                number = str(int(number))
                data["archive_no"] = number
        except forms.ValidationError as error:
            for field, errors in error.message_dict.items():
                for message in errors:
                    self.add_error(field, message)
        if number:
            same = set(
                Case.objects.filter(archive_folder_no__iexact=folder, archive_no__iexact=number)
                .exclude(pk=self.instance.pk)
                .values_list("pk", flat=True)
            )
            unchanged = bool(
                self.instance.pk
                and Case.objects.filter(
                    pk=self.instance.pk, archive_folder_no__iexact=folder, archive_no__iexact=number
                ).exists()
            )
            if same and not unchanged:
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


ATTENDANCE_CHOICES = [
    ("attend", "Katılınacak"),
    ("remote", "E-duruşma"),
    ("excuse", "Mazeret"),
]


class HearingStandaloneForm(BootstrapMixin, forms.ModelForm):
    """Duruşma / etkinlik oluşturma ve düzenleme formu."""

    case = forms.ModelChoiceField(
        label="Dosya",
        queryset=Case.objects.none(),
        required=False,
        widget=forms.Select(attrs={"data-searchable": "Dosya ara…"}),
    )
    client = forms.ModelChoiceField(
        label="Müvekkil",
        queryset=Client.objects.all(),
        required=False,
        widget=forms.Select(attrs={"data-searchable": "Müvekkil ara…"}),
    )
    # Yalnızca duruşma, ön inceleme ve keşifte sorulur (clean ve şablondaki betik bunu uygular).
    attendance = forms.ChoiceField(
        label="Katılma durumu", choices=ATTENDANCE_CHOICES, initial="attend", required=False
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
            "notes",
        ]
        labels = {"assigned_to": "Sorumlu avukat"}
        widgets = {
            "starts_at": DateTimeInput(),
            "ends_at": DateTimeInput(),
            "notes": forms.Textarea(
                attrs={
                    "rows": 3,
                    "placeholder": "Örn. Duruşmada tanık listesi sunmak üzere süre isteyeceğiz.",
                }
            ),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.core.permissions import filter_visible_cases

        qs = Case.objects.filter(status=CaseStatus.OPEN).select_related("client")
        if self.instance.pk and self.instance.case_id:
            qs = qs | Case.objects.filter(pk=self.instance.case_id).select_related("client")
        if user:
            qs = filter_visible_cases(qs, user)
        self.fields["case"].queryset = qs

        def _label(obj):
            client_name = obj.client.name if obj.client else "Müvekkilsiz"
            parts = [obj.archive_reference, obj.display_name, client_name]
            return " · ".join(part for part in parts if part)

        self.fields["case"].label_from_instance = _label
        # Sorumlu avukat dosyadan otomatik gelmez; yönetici, kıdemli, avukat ve stajyer seçilebilir.
        self.fields["assigned_to"].queryset = User.objects.filter(
            is_active=True,
            role__in=[User.Role.ADMIN, User.Role.SENIOR, User.Role.LAWYER, User.Role.INTERN],
        ).order_by("first_name", "last_name")
        self.fields["assigned_to"].empty_label = "Seçiniz…"
        if self.instance.pk:
            self.initial["attendance"] = self.instance.attendance
            # Müvekkil kayıtta boşsa dosyanın müvekkili gösterilir.
            if not self.instance.client_id and self.instance.case_id:
                self.initial["client"] = self.instance.case.client_id
        else:
            # Yeni kayıtta tarih alanı bugünün tarihi ve içinde bulunulan saatle gelir.
            now = timezone.localtime().replace(minute=0, second=0, microsecond=0)
            self.initial.setdefault("starts_at", now)
        # Duruşma, ön inceleme ve keşif UYAP'tan gelir; elle eklemek ayrı bir yetkidir.
        from apps.core.permission_registry import has_perm

        keeps_list_kind = bool(self.instance.pk and self.instance.kind in LIST_KINDS)
        if not (keeps_list_kind or (user and has_perm(user, "hearings.create_manual"))):
            self.fields["kind"].choices = [
                choice for choice in self.fields["kind"].choices if choice[0] not in LIST_KINDS
            ]
        # Bilirkişi incelemesi yeni etkinlik türü olarak seçilemez (eski kayıt türünü korur).
        if not (self.instance.pk and self.instance.kind == HearingKind.EXPERT):
            self.fields["kind"].choices = [
                choice for choice in self.fields["kind"].choices if choice[0] != HearingKind.EXPERT
            ]
        # Kayıt açıldıktan sonra tür değiştirilemez (alanlar ve zorunluluklar türe bağlı).
        if self.instance.pk:
            self.fields["kind"].disabled = True
        # UYAP kaydının tarih, saat, mahkeme ve dosya bilgisi değiştirilemez; UYAP'tan güncellenir.
        if self.instance.pk and self.instance.portal_ref:
            for name in ("kind", "case", "client", "starts_at", "ends_at"):
                self.fields[name].disabled = True
                self.fields[name].help_text = "UYAP kaydı; UYAP'tan gelir, değiştirilemez."

    @property
    def is_listed(self) -> bool:
        """Seçili tür duruşma, ön inceleme veya keşif mi (başlık yok, katılma durumu var)."""
        if self.is_bound:
            kind = self.data.get(self.add_prefix("kind"))
        else:
            kind = self.initial.get("kind") or self.instance.kind
        return kind in LIST_KINDS

    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data.get("kind") in LIST_KINDS:
            cleaned_data["title"] = ""  # duruşma, ön inceleme ve keşifte etkinlik başlığı yok
            if not (self.instance.pk and self.instance.portal_ref):
                cleaned_data["ends_at"] = None  # bitiş saati de yok (UYAP kaydı korunur)
        case = cleaned_data.get("case")
        client = cleaned_data.get("client")
        title = cleaned_data.get("title")

        if case and not client:
            cleaned_data["client"] = case.client

        kind = cleaned_data.get("kind")
        if kind in LIST_KINDS:
            # Duruşma, ön inceleme ve keşifte dosya ve müvekkil zorunlu (eski dosyasız kayıt hariç).
            legacy = bool(self.instance.pk and not self.instance.case_id)
            if not case and not legacy:
                self.add_error("case", "Duruşma, ön inceleme ve keşifte dosya seçilmelidir.")
            elif not cleaned_data.get("client") and not legacy:
                self.add_error("client", "Dosyanın müvekkili yok; müvekkil seçin.")
            if not cleaned_data.get("attendance"):
                self.add_error("attendance", "Katılma durumunu seçin.")
        elif not case and not client and not title:
            raise forms.ValidationError(
                "Lütfen bir dosya, müvekkil veya etkinlik başlığı belirtiniz."
            )
        if kind in RESULT_KINDS and not cleaned_data.get("assigned_to"):
            self.add_error("assigned_to", "Duruşmaya girecek sorumlu avukatı seçin.")
        return cleaned_data

    def save(self, commit=True):
        hearing = super().save(commit=False)
        # Katılma durumu yalnızca duruşma, ön inceleme ve keşifte vardır.
        attendance = self.cleaned_data.get("attendance") if hearing.kind in LIST_KINDS else ""
        hearing.excuse_submitted = attendance == "excuse"
        hearing.is_remote = attendance == "remote"
        # Mahkeme dosyadan otomatik gelir.
        if hearing.case_id and hearing.kind in LIST_KINDS and not hearing.authority:
            hearing.authority = hearing.case.authority
        if commit:
            hearing.save()
        return hearing


class HearingResultForm(BootstrapMixin, forms.ModelForm):
    """Duruşma sonucu: verilen karar (zorunlu) ve isteğe bağlı sonraki duruşma tarihi."""

    next_hearing_at = forms.DateTimeField(
        label="Sonraki duruşma tarihi",
        required=False,
        widget=DateTimeInput(),
        help_text="Zorunlu değil; UYAP'tan da otomatik gelir. Girilirse takvime eklenir.",
    )

    class Meta:
        model = Hearing
        fields = ["result"]
        labels = {"result": "Duruşmada verilen karar / sonuç"}
        widgets = {
            "result": forms.Textarea(
                attrs={"rows": 5, "placeholder": "Duruşmada alınan ara kararlar veya sonuç..."}
            )
        }

    def clean_result(self):
        result = (self.cleaned_data.get("result") or "").strip()
        if not result:
            raise forms.ValidationError("Duruşmada verilen kararı yazın.")
        return result


class HearingClientNoteForm(BootstrapMixin, forms.ModelForm):
    """Müvekkile giden mesaja eklenen ayrı not (isteğe bağlı)."""

    class Meta:
        model = Hearing
        fields = ["client_note"]
        labels = {"client_note": "Müvekkile not"}
        widgets = {
            "client_note": forms.Textarea(
                attrs={"rows": 3, "placeholder": "Mesaja eklenecek açıklama (isteğe bağlı)..."}
            )
        }


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


class ArchivePlacementMixin:
    def setup_archive_placement(self, case, state):
        self.archive_case = case
        self.archive_state = state
        category = category_for_case(case)
        self.archive_required = not category or category.tracks_state
        self.archive_category_name = category.name if category else ""
        if not self.archive_required:
            return
        folders = (
            ArchiveFolder.objects.filter(
                category=category, physical_state=state, is_active=True
            ).order_by("number")
            if category
            else ArchiveFolder.objects.none()
        )
        choices = [("", "Klasör seçiniz…"), *((f.name, f.name) for f in folders)]
        selected = self.data.get("archive_folder_no", "") if self.is_bound else ""
        slots, _ = available_archive_slots(selected, case)
        self.fields["archive_folder_no"] = forms.ChoiceField(
            label="Fiziki klasör",
            choices=choices,
            required=False,
            widget=forms.Select(
                attrs={
                    "class": "form-select",
                    "data-archive-folder": "",
                    "data-case-id": case.pk,
                }
            ),
        )
        self.fields["archive_no"] = forms.ChoiceField(
            label="Boş dosya yeri",
            choices=[("", "Boş yer seçiniz…"), *((n, n) for n in slots)],
            required=False,
            widget=forms.Select(attrs={"class": "form-select", "data-archive-slot": ""}),
        )

    def clean_archive_placement(self, data):
        folder = data.get("archive_folder_no", "")
        number = data.get("archive_no", "")
        if not self.archive_required or (not folder and not number):
            return
        try:
            validate_case_placement(self.archive_case, self.archive_state, folder, number)
        except forms.ValidationError as error:
            self.add_error("archive_no", " ".join(error.messages))


class CaseArchivePlacementForm(ArchivePlacementMixin, BootstrapMixin, forms.Form):
    def __init__(self, *args, case, state, **kwargs):
        super().__init__(*args, **kwargs)
        self.setup_archive_placement(case, state)

    def clean(self):
        data = super().clean()
        self.clean_archive_placement(data)
        return data


class CaseCloseForm(ArchivePlacementMixin, BootstrapMixin, forms.Form):
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
        self.setup_archive_placement(case, "closed")
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
        self.clean_archive_placement(data)
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
