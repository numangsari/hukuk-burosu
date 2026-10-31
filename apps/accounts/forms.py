from django import forms
from django.contrib.auth import password_validation
from django.contrib.auth.forms import AuthenticationForm

from apps.core.forms import BootstrapMixin

from .models import User


class PinLoginForm(AuthenticationForm):
    """Kullanıcı kartı seçilir (gizli username), PIN password alanında gelir."""

    error_messages = {
        "invalid_login": "PIN hatalı. 5 hatalı denemeden sonra giriş 15 dakika kilitlenir.",
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
        elif new:
            try:
                password_validation.validate_password(new, self.user)
            except forms.ValidationError as e:
                self.add_error("new_pin", e)
        return data

    def save(self):
        self.user.set_password(self.cleaned_data["new_pin"])
        self.user.save(update_fields=["password"])
        return self.user


class ProfileForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = User
        fields = ["first_name", "last_name", "email", "phone", "theme", "page_size"]
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
        fields = ["first_name", "last_name", "role", "title", "order", "is_active"]
        labels = {"first_name": "Ad", "last_name": "Soyad", "is_active": "Aktif"}

    def __init__(self, *args, editor=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.editor = editor
        self.fields["first_name"].required = True
        self.fields["last_name"].required = True

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
        if commit:
            user.save()
        return user
