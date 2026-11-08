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
        user.is_staff = user.is_superuser = user.role == User.Role.ADMIN
        if self.cleaned_data.get("pin"):
            user.set_password(self.cleaned_data["pin"])
            # Yöneticinin başkasına verdiği PIN geçicidir; kişi ilk girişte kendi PIN'ini belirler.
            user.must_change_pin = not (self.editor and user.pk == self.editor.pk)
        if commit:
            user.save()
        return user


class RolePermissionsForm(forms.Form):
    """Ayarlar > Yetkiler: rol × yetki matrisi. Yönetici sütunu kilitli ve hep işaretlidir."""

    def __init__(self, data=None, files=None):
        super().__init__(data)
        from apps.core import permission_registry as registry

        self.registry = registry
        saved = OfficeSettings.load().role_permissions
        self.roles = [(key, label) for key, label in registry.ROLES if key != "admin"]
        for perm in registry.PERMISSIONS:
            chosen = registry.allowed_roles(saved, perm.key)
            for role, _label in self.roles:
                name = self.field_name(perm.key, role)
                self.fields[name] = forms.BooleanField(required=False)
                self.initial[name] = role in chosen

    @staticmethod
    def field_name(key: str, role: str) -> str:
        return f"perm:{key}:{role}"

    @property
    def groups(self):
        """Ekran için: (grup, [(yetki, [hücre])]); hücre = rol, alan adı ve işaret durumu."""
        result = []
        for group, perms in self.registry.groups():
            rows = []
            for perm in perms:
                cells = []
                for role, label in self.roles:
                    bound = self[self.field_name(perm.key, role)]
                    cells.append({"role": role, "label": label, "field": bound})
                rows.append((perm, cells))
            result.append((group, rows))
        return result

    def save(self):
        office = OfficeSettings.load()
        saved = {}
        for perm in self.registry.PERMISSIONS:
            roles = [
                role
                for role, _label in self.roles
                if self.cleaned_data.get(self.field_name(perm.key, role))
            ]
            saved[perm.key] = ["admin", *roles]
        office.role_permissions = saved
        office.save(update_fields=["role_permissions"])


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
            )
            user.set_password(self.cleaned_data["pin"])
            user.save()
            return user
