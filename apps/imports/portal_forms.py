from django.contrib.auth import get_user_model


class PreserveExistingAssigneeMixin:
    """Deneme kayıtlarındaki mevcut geçici sorumlunun değiştirilmeden korunmasını sağlar."""

    def keep_existing_assignee(self):
        self.original_intern_id = self.instance.responsible_intern_id if self.instance.pk else None
        if self.original_intern_id and "responsible_intern" in self.fields:
            field = self.fields["responsible_intern"]
            field.queryset = field.queryset | get_user_model().objects.filter(
                pk=self.original_intern_id
            )

    def _get_validation_exclusions(self):
        excluded = super()._get_validation_exclusions()
        assigned = self.cleaned_data.get("responsible_intern")
        if (
            assigned
            and assigned.pk == self.original_intern_id
            and assigned.role not in ("intern", "paralegal")
        ):
            excluded.add("responsible_intern")
        return excluded
