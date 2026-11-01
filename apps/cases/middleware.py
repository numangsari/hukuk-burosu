from django.core.cache import cache

from .seizures import create_due_tasks


class SeizureTaskMiddleware:
    """Açık oturumlarda da tarih kontrolü yapar; ana çalışma zamanlanmış görevdir."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated and cache.add("seizure-tasks-check", True, 60):
            try:
                create_due_tasks()
            except Exception:
                cache.delete("seizure-tasks-check")
                raise
        return self.get_response(request)
