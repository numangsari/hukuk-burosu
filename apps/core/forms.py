from django import forms


class BootstrapMixin:
    """Form alanlarına Bootstrap sınıflarını ekler."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            w = field.widget
            if isinstance(w, forms.CheckboxInput):
                css = "form-check-input"
            elif isinstance(w, forms.Select | forms.SelectMultiple):
                css = "form-select"
            else:
                css = "form-control"
            w.attrs["class"] = f"{w.attrs.get('class', '')} {css}".strip()
            if isinstance(w, forms.Textarea) and str(w.attrs.get("rows")) == "10":
                w.attrs["rows"] = 3  # Django varsayılanı (10) form için çok uzun
            # Boş seçenek "---------" yerine anlaşılır metin
            if hasattr(field, "empty_label") and field.empty_label is not None:
                field.empty_label = "Seçiniz…"
            elif isinstance(field, forms.ChoiceField) and not isinstance(w, forms.RadioSelect):
                field.choices = [
                    ("", "Seçiniz…") if value == "" else (value, label)
                    for value, label in field.choices
                ]


class DateInput(forms.DateInput):
    input_type = "date"

    def __init__(self, **kwargs):
        super().__init__(format="%Y-%m-%d", **kwargs)


class DateTimeInput(forms.DateTimeInput):
    input_type = "datetime-local"

    def __init__(self, **kwargs):
        super().__init__(format="%Y-%m-%dT%H:%M", **kwargs)
