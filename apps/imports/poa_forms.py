from django import forms

from apps.clients.models import Client, PersonKind
from apps.core.forms import BootstrapMixin


class PowerOfAttorneyReviewForm(BootstrapMixin, forms.ModelForm):
    kind = forms.ChoiceField(label="Kayıt türü", choices=[("", "Seçiniz"), *PersonKind.choices])
    team = forms.ChoiceField(label="Sorumlu ekip")
    confirm_duplicate = forms.BooleanField(
        label="Aynı adla kayıt varsa bunun farklı bir müvekkil olduğunu doğruluyorum",
        required=False,
    )
    confirm_shared_poa = forms.BooleanField(
        label="Numara başka müvekkillerde varsa aynı vekaleti paylaştıklarını onaylıyorum",
        required=False,
    )

    class Meta:
        model = Client
        fields = ["kind", "first_name", "last_name", "title", "poa_no", "notes"]
        widgets = {"notes": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *args, teams, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["team"].choices = [("auto", "İki ekip arasında dengeli dağıt")] + [
            (str(intern.pk), f"{lawyer} / {intern}") for lawyer, intern in teams
        ]
        self.fields["team"].initial = "auto"
        self.fields["kind"].widget.attrs["x-model"] = "kind"
        self.fields["first_name"].label = "Ad"
        self.fields["last_name"].label = "Soyad"
        self.fields["title"].label = "Şirket unvanı"
        self.fields["poa_no"].label = "Vekalet numarası"
        self.fields["poa_no"].widget.attrs["min"] = 1
        self.fields["poa_no"].help_text = "Yalnızca sayı girin; numara yoksa boş bırakın."
        for name in ("first_name", "last_name", "title"):
            self.fields[name].widget.attrs["class"] += " text-uppercase-input"

    def clean_first_name(self):
        return " ".join(self.cleaned_data["first_name"].split())

    def clean_last_name(self):
        return " ".join(self.cleaned_data["last_name"].split())

    def clean_title(self):
        return " ".join(self.cleaned_data["title"].split())

    def clean_poa_no(self):
        value = self.cleaned_data["poa_no"]
        if value is not None and value < 1:
            raise forms.ValidationError("Vekalet numarası 1 veya daha büyük olmalı.")
        return value
