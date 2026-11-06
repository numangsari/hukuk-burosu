import logging

from django.core.cache import cache

from .seizures import create_due_tasks

logger = logging.getLogger(__name__)


class SeizureTaskMiddleware:
    """Açık oturumlarda da tarih kontrolü yapar; ana çalışma zamanlanmış görevdir.

    Haciz görevi üretimi başarısız olursa kullanıcının açtığı sayfa etkilenmez: hata
    günlüğe yazılır ve işlem 60 saniye sonraki ilk istekte yeniden denenir.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated and cache.add("seizure-tasks-check", True, 60):
            try:
                create_due_tasks()
            except Exception:
                logger.exception("Haciz yenileme görevleri üretilemedi")
        return self.get_response(request)
