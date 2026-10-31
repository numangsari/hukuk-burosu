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
            if isinstance(w, forms.Textarea):
                w.attrs.setdefault("rows", 3)


class DateInput(forms.DateInput):
    input_type = "date"

    def __init__(self, **kwargs):
        super().__init__(format="%Y-%m-%d", **kwargs)


class DateTimeInput(forms.DateTimeInput):
    input_type = "datetime-local"

    def __init__(self, **kwargs):
        super().__init__(format="%Y-%m-%dT%H:%M", **kwargs)
