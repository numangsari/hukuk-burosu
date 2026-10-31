from django import forms
from django.contrib.auth import password_validation
from django.contrib.auth.forms import AuthenticationForm

from apps.core.forms import BootstrapMixin


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
            f.widget.attrs.update(inputmode="numeric", autocomplete="off", maxlength=8)

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
