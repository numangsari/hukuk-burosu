from django import forms
from django.contrib.auth import password_validation
from django.contrib.auth.forms import AuthenticationForm

from apps.core.forms import BootstrapMixin
from apps.office.models import OfficeSettings

from .models import User


class PinLoginForm(AuthenticationForm):
    """Kullanıcı kartı seçilir (gizli username), PIN password alanında gelir."""

    error_messages = {
        "invalid_login": "PIN hatalı. Tekrar deneyin.",
        "inactive": "Bu kullanıcı pasif.",
    }


class PinChangeForm(BootstrapMixin, forms.Form):
    old_pin = forms.CharField(label="Mevcut PIN", widget=forms.PasswordInput)
    new_pin = forms.CharField(label="Yeni PIN", widget=forms.PasswordInput)
    new_pin2 = forms.CharField(label="Yeni PIN (tekrar)", widget=forms.PasswordInput)

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
        for f in self.fields.values():
            f.widget.attrs.update(inputmode="numeric", autocomplete="off", maxlength=4)

    def clean_old_pin(self):
        pin = self.cleaned_data["old_pin"]
        if not self.user.check_password(pin):
            raise forms.ValidationError("Mevcut PIN hatalı.")
        return pin

    def clean(self):
        data = super().clean()
        new, new2 = data.get("new_pin"), data.get("new_pin2")
        if new and new2 and new != new2:
            self.add_error("new_pin2", "PIN'ler eşleşmiyor.")
        elif new and new == data.get("old_pin"):
            self.add_error("new_pin", "Yeni PIN mevcut PIN'den farklı olmalı.")
        elif new:
            try:
                password_validation.validate_password(new, self.user)
            except forms.ValidationError as e:
                self.add_error("new_pin", e)
        return data

    def save(self):
        self.user.set_password(self.cleaned_data["new_pin"])
        self.user.must_change_pin = False
        self.user.save(update_fields=["password", "must_change_pin"])
        return self.user


class ProfileForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = User
        fields = ["first_name", "last_name", "email", "phone", "theme"]
        labels = {"first_name": "Ad", "last_name": "Soyad", "email": "E-posta"}


class UserAdminForm(BootstrapMixin, forms.ModelForm):
    """Yöneticinin kullanıcı eklediği/düzenlediği form. PIN yalnızca girilirse değişir."""

    pin = forms.CharField(
        label="PIN",
        required=False,
        max_length=4,
        widget=forms.PasswordInput(attrs={"inputmode": "numeric", "autocomplete": "new-password"}),
        help_text="Yeni kullanıcıda zorunlu. Mevcut kullanıcıda boş bırakılırsa PIN değişmez.",
    )

    class Meta:
        model = User
        fields = ["first_name", "last_name", "role", "title", "supervisor", "order", "is_active"]
        labels = {"first_name": "Ad", "last_name": "Soyad", "is_active": "Aktif"}

    def __init__(self, *args, editor=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.editor = editor
        self.fields["first_name"].required = True
        self.fields["last_name"].required = True
        self.fields["supervisor"].help_text = (
            "Bu kişi görevde sorumlu olunca kontrolcü olarak bu kişi önerilir. Yardımcı sorumluda "
            "ayrıca müvekkil ve dosyada bu avukat seçilince yardımcı sorumlu otomatik dolar."
        )
        self.fields["role"].widget.attrs["x-model"] = "role"
        self.fields["supervisor"].queryset = User.objects.filter(
            role__in=[User.Role.ADMIN, User.Role.SENIOR, User.Role.LAWYER], is_active=True
        ).exclude(pk=self.instance.pk)

    def clean_pin(self):
        pin = self.cleaned_data.get("pin", "")
        if not pin and not self.instance.pk:
            raise forms.ValidationError("Yeni kullanıcı için PIN girin.")
        if pin:
            password_validation.validate_password(pin)
        return pin

    def clean(self):
        data = super().clean()
        if self.instance.pk and self.editor and self.instance.pk == self.editor.pk:
            if not data.get("is_active"):
                self.add_error("is_active", "Kendi hesabınızı pasife alamazsınız.")
            if data.get("role") != User.Role.ADMIN:
                self.add_error("role", "Kendi yönetici yetkinizi kaldıramazsınız.")
        return data

    def save(self, commit=True):
        from apps.core.text import fold

        user = super().save(commit=False)
        if not user.pk:
            base = ".".join(fold(f"{user.first_name} {user.last_name}").split()) or "kullanici"
            username, n = base, 2
            while User.objects.filter(username=username).exists():
                username, n = f"{base}{n}", n + 1
            user.username = username
            if user.role == User.Role.ACCOUNTANT:
                user.can_view_balances = True
                user.can_manage_accounting = True
        user.is_staff = user.is_superuser = user.role == User.Role.ADMIN
        if self.cleaned_data.get("pin"):
            user.set_password(self.cleaned_data["pin"])
            # Yöneticinin başkasına verdiği PIN geçicidir; kişi ilk girişte kendi PIN'ini belirler.
            user.must_change_pin = not (self.editor and user.pk == self.editor.pk)
        if commit:
            user.save()
        return user


class BalanceViewersForm(forms.Form):
    """Ayarlar > Yetkiler formu:
    1. Dosya ve müvekkil görünürlük kapsamı + istisna kullanıcılar
    2. Görevlerde kontrolcü onayı iş akışı
    3. Muhasebe kaydı ekleme/iptal yetkisi + bakiye görme yetkisi
    """

    case_visibility_mode = forms.ChoiceField(
        label="Dosya ve müvekkil görünürlüğü",
        choices=OfficeSettings.CaseVisibilityMode.choices,
        required=False,
        widget=forms.RadioSelect,
    )
    all_cases_viewers = forms.ModelMultipleChoiceField(
        label="Sorumlu bazlı modda tüm dosyaları görebilen ek kişiler",
        queryset=User.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )
    task_review_mode = forms.ChoiceField(
        label="Görevlerde kontrolcü onayı",
        choices=OfficeSettings.TaskReviewMode.choices,
        required=False,
        widget=forms.RadioSelect,
    )
    accounting_edit_mode = forms.ChoiceField(
        label="Muhasebe kaydı ekleme ve iptal etme yetkisi",
        choices=OfficeSettings.AccountingEditMode.choices,
        required=False,
        widget=forms.RadioSelect,
    )
    accounting_editors = forms.ModelMultipleChoiceField(
        label="Muhasebe kaydı ekleyebilen / iptal edebilen kişiler",
        queryset=User.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )
    viewers = forms.ModelMultipleChoiceField(
        label="Bakiyeleri görebilenler",
        queryset=User.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )

    def __init__(self, data=None, files=None):
        super().__init__(data)
        office = OfficeSettings.load()
        non_admin_qs = User.objects.filter(is_active=True).exclude(role=User.Role.ADMIN)
        restricted_case_roles_qs = non_admin_qs.filter(
            role__in=[User.Role.LAWYER, User.Role.INTERN, User.Role.PARALEGAL]
        )
        non_accountant_qs = non_admin_qs.exclude(role=User.Role.ACCOUNTANT)

        self.fields["viewers"].queryset = non_admin_qs
        self.fields["accounting_editors"].queryset = non_accountant_qs
        self.fields["all_cases_viewers"].queryset = restricted_case_roles_qs

        self.initial["case_visibility_mode"] = office.case_visibility_mode
        self.initial["task_review_mode"] = office.task_review_mode
        self.initial["accounting_edit_mode"] = office.accounting_edit_mode
        self.initial["viewers"] = list(non_admin_qs.filter(can_view_balances=True))
        self.initial["accounting_editors"] = list(
            non_accountant_qs.filter(can_manage_accounting=True)
        )
        self.initial["all_cases_viewers"] = list(
            restricted_case_roles_qs.filter(can_view_all_cases=True)
        )

    def save(self):
        office = OfficeSettings.load()
        update_office_fields = []
        for field_name in ("case_visibility_mode", "task_review_mode", "accounting_edit_mode"):
            val = self.cleaned_data.get(field_name)
            if val:
                setattr(office, field_name, val)
                update_office_fields.append(field_name)
        if update_office_fields:
            office.save(update_fields=update_office_fields)

        chosen_viewers = {u.pk for u in self.cleaned_data.get("viewers", [])}
        qs_viewers = self.fields["viewers"].queryset
        qs_viewers.filter(pk__in=chosen_viewers).update(can_view_balances=True)
        qs_viewers.exclude(pk__in=chosen_viewers).update(can_view_balances=False)

        if (
            self.data is None
            or "accounting_edit_mode" in self.data
            or "accounting_editors" in self.data
        ):
            chosen_editors = {u.pk for u in self.cleaned_data.get("accounting_editors", [])}
            qs_editors = self.fields["accounting_editors"].queryset
            qs_editors.filter(pk__in=chosen_editors).update(can_manage_accounting=True)
            qs_editors.exclude(pk__in=chosen_editors).update(can_manage_accounting=False)

        if (
            self.data is None
            or "case_visibility_mode" in self.data
            or "all_cases_viewers" in self.data
        ):
            chosen_all_cases = {u.pk for u in self.cleaned_data.get("all_cases_viewers", [])}
            qs_all_cases = self.fields["all_cases_viewers"].queryset
            qs_all_cases.filter(pk__in=chosen_all_cases).update(can_view_all_cases=True)
            qs_all_cases.exclude(pk__in=chosen_all_cases).update(can_view_all_cases=False)
        return None


class InitialSetupForm(BootstrapMixin, forms.Form):
    """Hiç kullanıcı yokken açılan Hukuk Bürosu İlk Kurulum sihirbazı formu."""

    office_name = forms.CharField(
        label="Ofis / Büro adı",
        max_length=200,
        widget=forms.TextInput(attrs={"placeholder": "Örn: Yılmaz Hukuk Bürosu"}),
    )
    phone = forms.CharField(label="Ofis telefonu (isteğe bağlı)", max_length=50, required=False)
    address = forms.CharField(
        label="Ofis adresi (isteğe bağlı)",
        required=False,
        widget=forms.Textarea(attrs={"rows": 2}),
    )
    documents_root = forms.CharField(
        label="Ofis belge klasörü (isteğe bağlı)",
        max_length=500,
        required=False,
        help_text=(
            r"Sunucu bilgisayarda belgelerin ve yedeklerin saklanacağı klasör "
            r"(örn: D:\Hukuk Ofis)."
        ),
    )
    use_assistant_assignee = forms.BooleanField(
        label="Yardımcı sorumlu (stajyer / katip) kullan",
        required=False,
        initial=True,
        help_text=(
            "Müvekkil ve dosyalarda sorumlu avukatın yanında yardımcı sorumlu da seçilsin mi?"
        ),
    )
    first_name = forms.CharField(label="Yönetici adı", max_length=150)
    last_name = forms.CharField(label="Yönetici soyadı", max_length=150)
    title = forms.CharField(
        label="Unvan",
        max_length=100,
        initial="Yönetici Avukat",
        required=False,
    )
    pin = forms.CharField(
        label="4 haneli giriş PIN kodu",
        max_length=4,
        widget=forms.PasswordInput(
            attrs={"inputmode": "numeric", "autocomplete": "new-password", "maxlength": "4"}
        ),
    )
    pin2 = forms.CharField(
        label="PIN kodu (tekrar)",
        max_length=4,
        widget=forms.PasswordInput(
            attrs={"inputmode": "numeric", "autocomplete": "new-password", "maxlength": "4"}
        ),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        office = OfficeSettings.load()
        if not self.is_bound:
            self.initial.setdefault("office_name", office.name)
            self.initial.setdefault("use_assistant_assignee", office.use_assistant_assignee)

    def clean_documents_root(self):
        from apps.core.folders import check_writable

        value = (self.cleaned_data.get("documents_root") or "").strip()
        if value and (error := check_writable(value)):
            raise forms.ValidationError(error)
        return value

    def clean(self):
        data = super().clean()
        pin = data.get("pin", "")
        pin2 = data.get("pin2", "")
        if pin:
            try:
                password_validation.validate_password(pin)
            except forms.ValidationError as e:
                self.add_error("pin", e)
        if pin and pin2 and pin != pin2:
            self.add_error("pin2", "PIN kodları eşleşmiyor.")
        return data

    def save(self):
        from django.db import transaction

        from apps.core.text import fold, tr_upper

        with transaction.atomic():
            office = OfficeSettings.load()
            office.name = self.cleaned_data["office_name"].strip()
            office.phone = (self.cleaned_data.get("phone") or "").strip()
            office.address = (self.cleaned_data.get("address") or "").strip()
            office.documents_root = (self.cleaned_data.get("documents_root") or "").strip()
            office.use_assistant_assignee = bool(self.cleaned_data.get("use_assistant_assignee"))
            office.save()

            first_name = self.cleaned_data["first_name"].strip()
            last_name = tr_upper(self.cleaned_data["last_name"].strip())
            base = ".".join(fold(f"{first_name} {last_name}").split()) or "yonetici"
            username, n = base, 2
            while User.objects.filter(username=username).exists():
                username, n = f"{base}{n}", n + 1

            user = User(
                username=username,
                first_name=first_name,
                last_name=last_name,
                role=User.Role.ADMIN,
                title=(self.cleaned_data.get("title") or "Yönetici Avukat").strip(),
                is_active=True,
                is_staff=True,
                is_superuser=True,
                must_change_pin=False,
                can_view_balances=True,
                can_manage_accounting=True,
                can_view_all_cases=True,
            )
            user.set_password(self.cleaned_data["pin"])
            user.save()
            return user
