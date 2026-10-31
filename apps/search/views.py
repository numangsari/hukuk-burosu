"""Global arama: müvekkil, dosya, karşı taraf, görev ve belge.

Türkçe karakter ve büyük/küçük harf farkı gözetilmez: kayıtlı `search_key` alanları
`fold()` ile, diğer alanlar PostgreSQL `unaccent` ile karşılaştırılır.
"""

from django.contrib.postgres.search import TrigramWordSimilarity
from django.db.models import Q
from django.shortcuts import render
from django.views import View

from apps.cases.models import Case, Document
from apps.clients.models import Client, Party
from apps.core.text import fold
from apps.tasks.models import Task

LIMIT = 8


def search(q: str, limit: int = LIMIT) -> dict:
    q = q.strip()
    if len(q) < 2:
        return {}
    key = fold(q)
    clients = (
        Client.objects.filter(Q(search_key__contains=key) | Q(tckn=q) | Q(vkn=q))
        .select_related("responsible_lawyer")
        .order_by("-is_active", "name")[:limit]
    )
    if not clients and len(key) >= 4:
        # Yazım hatalarına tolerans: trigram benzerliği
        clients = (
            Client.objects.annotate(sim=TrigramWordSimilarity(key, "search_key"))
            .filter(sim__gt=0.45)
            .order_by("-sim")[:limit]
        )
    cases = (
        Case.objects.filter(
            Q(archive_no__unaccent__icontains=q)
            | Q(official_no__unaccent__icontains=q)
            | Q(subject__unaccent__icontains=q)
            | Q(authority__unaccent__icontains=q)
            | Q(client__search_key__contains=key)
        )
        .select_related("client")
        .order_by("-created_at")[:limit]
    )
    parties = (
        Party.objects.filter(Q(search_key__contains=key) | Q(identity_no=q))
        .prefetch_related("case_links__case")
        .order_by("name")[:limit]
    )
    tasks = (
        Task.objects.filter(Q(title__unaccent__icontains=q) | Q(notes__unaccent__icontains=q))
        .select_related("case", "assignee")
        .order_by("status", "due_date")[:limit]
    )
    documents = (
        Document.objects.filter(
            Q(title__unaccent__icontains=q) | Q(original_name__unaccent__icontains=q)
        )
        .select_related("case")
        .order_by("-created_at")[:limit]
    )
    return {
        "clients": list(clients),
        "cases": list(cases),
        "parties": list(parties),
        "tasks": list(tasks),
        "documents": list(documents),
    }


class SearchView(View):
    def get(self, request):
        q = request.GET.get("q", "")
        if request.htmx and request.GET.get("canli"):
            results = search(q, limit=5)
            return render(request, "search/_dropdown.html", {"q": q, "r": results})
        results = search(q, limit=50)
        total = sum(len(v) for v in results.values())
        return render(request, "search/results.html", {"q": q, "r": results, "total": total})
