"""Global arama: müvekkil, dosya, karşı taraf, görev ve belge.

Türkçe karakter ve büyük/küçük harf farkı gözetilmez: kayıtlı `search_key` alanları
`fold()` ile, diğer alanlar PostgreSQL `unaccent` ile karşılaştırılır.
"""

from urllib.parse import urlencode

from django.contrib.postgres.search import TrigramWordSimilarity
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import render
from django.views import View

from apps.cases.models import Case, Document
from apps.clients.models import Client, Party
from apps.core.pagination import page_size
from apps.core.permissions import filter_visible_cases, filter_visible_clients
from apps.core.text import fold
from apps.tasks.models import Task

LIMIT = 8
PREVIEW_LIMIT = 10  # "Tümü" sekmesinde her türden gösterilen sonuç

# Sonuç sayfasındaki tür süzgeci: (anahtar, URL değeri, etiket)
KINDS = [
    ("clients", "muvekkil", "Müvekkiller"),
    ("cases", "dosya", "Dosyalar"),
    ("tasks", "gorev", "Görevler"),
    ("parties", "karsi", "Karşı taraflar"),
    ("documents", "belge", "Belgeler"),
]
SORTS = {"alaka": "En alakalı", "ad": "Ada göre (A–Z)", "yeni": "En yeni", "eski": "En eski"}
# "Ada göre" sıralamasında her türün ad alanı
NAME_FIELD = {
    "clients": "name",
    "cases": "archive_no",
    "tasks": "title",
    "parties": "name",
    "documents": "title",
}


def search_querysets(q: str, user=None) -> dict:
    """Her tür için sınırlanmamış sorgular; varsayılan sıra "en alakalı" sıradır."""
    q = q.strip()
    if len(q) < 2:
        return {}
    key = fold(q)
    base_clients = Client.objects.all()
    base_cases = Case.objects.all()
    if user is not None:
        base_clients = filter_visible_clients(base_clients, user)
        base_cases = filter_visible_cases(base_cases, user)
    clients = (
        base_clients.filter(Q(search_key__contains=key) | Q(tckn=q) | Q(vkn=q))
        .select_related("responsible_lawyer")
        .order_by("name")
    )
    if len(key) >= 4 and not clients.exists():
        # Yazım hatalarına tolerans: trigram benzerliği
        clients = (
            base_clients.annotate(sim=TrigramWordSimilarity(key, "search_key"))
            .filter(sim__gt=0.45)
            .order_by("-sim")
        )
    cases = (
        base_cases.filter(
            Q(archive_no__unaccent__icontains=q)
            | Q(archive_folder_no__unaccent__icontains=q)
            | Q(official_no__unaccent__icontains=q)
            | Q(subject__unaccent__icontains=q)
            | Q(authority__unaccent__icontains=q)
            | Q(client__search_key__contains=key)
            | Q(co_clients__search_key__contains=key)
        )
        .distinct()
        .select_related("client")
        .order_by("-created_at")
    )
    return {
        "clients": clients,
        "cases": cases,
        "parties": Party.objects.filter(Q(search_key__contains=key) | Q(identity_no=q))
        .prefetch_related("case_links__case")
        .order_by("name"),
        "tasks": Task.objects.filter(
            Q(title__unaccent__icontains=q) | Q(notes__unaccent__icontains=q)
        )
        .select_related("case", "assignee")
        .order_by("status", "due_date"),
        "documents": Document.objects.filter(
            Q(title__unaccent__icontains=q) | Q(original_name__unaccent__icontains=q)
        )
        .select_related("case")
        .order_by("-created_at"),
    }


def apply_sort(name: str, qs, sort: str):
    if sort == "ad":
        return qs.order_by(NAME_FIELD[name], "pk")
    if sort == "yeni":
        return qs.order_by("-created_at", "-pk")
    if sort == "eski":
        return qs.order_by("created_at", "pk")
    return qs


def search(q: str, limit: int = LIMIT, sort: str = "alaka", user=None) -> dict:
    return {
        name: list(apply_sort(name, qs, sort)[:limit])
        for name, qs in search_querysets(q, user=user).items()
    }


class SearchView(View):
    def get(self, request):
        q = request.GET.get("q", "")
        if request.htmx and request.GET.get("canli"):
            results = search(q, limit=5, user=request.user)
            return render(request, "search/_dropdown.html", {"q": q, "r": results})

        sort = request.GET.get("sirala", "alaka")
        if sort not in SORTS:
            sort = "alaka"
        kind_by_param = {param: name for name, param, _ in KINDS}
        kind = request.GET.get("tur", "")
        selected = kind_by_param.get(kind)
        querysets = search_querysets(q, user=request.user)
        counts = {name: qs.count() for name, qs in querysets.items()}
        page_obj = paginator = None
        more = {}
        if selected:
            # Tek tür: tüm sonuçlar sayfa sayfa.
            paginator = Paginator(
                apply_sort(selected, querysets[selected], sort), page_size(request)
            )
            page_obj = paginator.get_page(request.GET.get("page"))
            results = {selected: list(page_obj.object_list)}
        else:
            # Tümü: her türden ilk sonuçlar; fazlası için o türün sekmesine bağlantı.
            results = {
                name: list(apply_sort(name, qs, sort)[:PREVIEW_LIMIT])
                for name, qs in querysets.items()
            }
            more = {
                name: (counts[name], "?" + urlencode({"q": q, "tur": param, "sirala": sort}))
                for name, param, _ in KINDS
                if counts.get(name, 0) > PREVIEW_LIMIT
            }
        ctx = {
            "q": q,
            "r": results,
            "total": sum(counts.values()),
            "shown": sum(counts[n] for n in results),
            "kind": kind if selected else "",
            "kinds": [(param, label, counts.get(name, 0)) for name, param, label in KINDS],
            "sort": sort,
            "sorts": SORTS.items(),
            "more": more,
            "page_obj": page_obj,
            "paginator": paginator,
        }
        template = "search/_results_body.html" if request.htmx else "search/results.html"
        return render(request, template, ctx)
