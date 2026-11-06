import logging

from django.core.cache import cache

from .seizures import create_due_tasks

logger = logging.getLogger(__name__)


class SeizureTaskMiddleware:
    """Açık oturumlarda da tarih kontrolü yapar; ana çalışma zamanlanmış görevdir.

    Hata bu istekteki kullanıcıya yansıtılmaz: loglanır ve kontrol bir sonraki
    denemede (önbellek süresi dolduktan sonra) yeniden yapılır.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated and cache.add("seizure-tasks-check", True, 60):
            try:
                create_due_tasks()
            except Exception:
                logger.exception("Haciz yenileme görevleri kontrol edilemedi")
        return self.get_response(request)
