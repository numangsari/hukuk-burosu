def app_context(request):
    from apps.office.models import OfficeSettings

    return {"office": OfficeSettings.load()}
