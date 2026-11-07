from .models import request_cache


class RequestSettingsCacheMiddleware:
    """Ofis ayarlarını istek boyunca bir kez okutur (`OfficeSettings.load`)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        token = request_cache.set({})
        try:
            return self.get_response(request)
        finally:
            request_cache.reset(token)
