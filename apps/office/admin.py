from django.contrib import admin

from .models import Court, OfficeSettings, TaskType

admin.site.register(OfficeSettings)


@admin.register(TaskType)
class TaskTypeAdmin(admin.ModelAdmin):
    list_display = ("name", "order", "is_active")
    list_editable = ("order", "is_active")


@admin.register(Court)
class CourtAdmin(admin.ModelAdmin):
    list_display = ("name", "kind", "is_active")
    list_filter = ("kind", "is_active")
    search_fields = ("name",)
