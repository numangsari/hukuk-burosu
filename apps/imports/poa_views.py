from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views import View

from apps.clients.models import Client
from apps.core.permissions import AdminRequiredMixin
from apps.core.text import fold

from . import poa_review
from .poa_forms import PowerOfAttorneyReviewForm


def _source():
    source_hash, rows = poa_review.read_source()
    return source_hash, poa_review.mark_processed(source_hash, rows)


class PowerOfAttorneyReviewListView(AdminRequiredMixin, View):
    def get(self, request):
        try:
            _, rows = _source()
        except ValueError as exc:
            template = "imports/_poa_list.html" if request.htmx else "imports/poa_list.html"
            return render(request, template, {"source_error": str(exc)})
        pending = sum(row.status != "done" for row in rows)
        completed = len(rows) - pending
        status = request.GET.get("durum", "pending")
        if status not in ("pending", "done", "all"):
            status = "pending"
        query = request.GET.get("q", "").strip()
        if status == "pending":
            rows = [row for row in rows if row.status != "done"]
        elif status == "done":
            rows = [row for row in rows if row.status == "done"]
        if query:
            term = fold(query)
            rows = [row for row in rows if term in fold(f"{row.reference} {row.name} {row.note}")]
        paginator = Paginator(rows, 25)
        page = paginator.get_page(request.GET.get("page"))
        context = {
            "rows": page.object_list,
            "page_obj": page,
            "paginator": paginator,
            "pending": pending,
            "completed": completed,
            "status": status,
            "query": query,
        }
        template = "imports/_poa_list.html" if request.htmx else "imports/poa_list.html"
        return render(request, template, context)


class PowerOfAttorneyReviewDetailView(AdminRequiredMixin, View):
    def _context(self, source_hash, rows, row, form=None):
        matches = Client.objects.filter(search_key__in=poa_review.row_match_keys(row))
        if row.status == "incomplete":
            matches = matches.exclude(pk__in=row.client_ids)
        linked_clients = (
            Client.objects.filter(pk__in=row.client_ids)
            if row.status in ("done", "incomplete")
            else Client.objects.none()
        )
        number_owners = (
            Client.objects.filter(poa_no=row.poa_no).exclude(
                pk__in=row.client_ids if row.status == "incomplete" else []
            )
            if row.status in ("conflict", "incomplete") and row.poa_no
            else Client.objects.none()
        )
        number_owner = number_owners.first()
        return {
            "source_hash": source_hash,
            "row": row,
            "form": form,
            "matches": matches,
            "number_owner": number_owner,
            "number_owners": number_owners,
            "linked_clients": linked_clients,
            "pending": sum(item.status != "done" for item in rows),
        }

    def _load(self, row_number):
        source_hash, rows = _source()
        row = next((item for item in rows if item.number == row_number), None)
        if row is None:
            raise Http404
        return source_hash, rows, row

    def get(self, request, row_number):
        try:
            source_hash, rows, row = self._load(row_number)
            teams = poa_review.get_teams()
        except (ValueError, ValidationError) as exc:
            messages.error(request, str(exc))
            return redirect("imports:poa_review")
        initial = {
            "title": row.name,
            "poa_no": row.poa_no,
            "notes": f"Kaynak notu: {row.note}" if row.note and row.note != "." else "",
            "team": "auto",
        }
        form = (
            PowerOfAttorneyReviewForm(initial=initial, teams=teams)
            if row.status != "done"
            else None
        )
        return render(
            request, "imports/poa_detail.html", self._context(source_hash, rows, row, form)
        )

    def post(self, request, row_number):
        try:
            source_hash, rows, row = self._load(row_number)
            teams = poa_review.get_teams()
        except (ValueError, ValidationError) as exc:
            messages.error(request, str(exc))
            return redirect("imports:poa_review")
        form = PowerOfAttorneyReviewForm(request.POST, teams=teams)
        if request.POST.get("source_hash") != source_hash:
            if request.POST.get("action") == "link":
                messages.error(request, "Kaynak liste değişmiş. Satırı yeniden inceleyin.")
                return redirect("imports:poa_review_detail", row_number=row.number)
            form.add_error(
                None, "Kaynak liste değişmiş. Sayfayı yenileyip satırı yeniden inceleyin."
            )
        elif request.POST.get("action") == "link":
            try:
                client_id = int(request.POST.get("client_id", ""))
                poa_review.link_existing(
                    client_id=client_id, source_hash=source_hash, row=row, user=request.user
                )
            except (ValueError, ValidationError):
                messages.error(
                    request, "Satır ilişkilendirilemedi. Listeyi yenileyip tekrar deneyin."
                )
                return redirect("imports:poa_review_detail", row_number=row.number)
            except IntegrityError:
                messages.error(request, "Bu satır başka bir işlemde kaydedildi. Listeyi yenileyin.")
                return redirect("imports:poa_review_detail", row_number=row.number)
            else:
                messages.success(request, "Satır mevcut müvekkille ilişkilendirildi.")
                return redirect("imports:poa_review")
        elif form.is_valid():
            try:
                poa_review.save_review(
                    form=form, source_hash=source_hash, row=row, user=request.user
                )
            except ValidationError as exc:
                form.add_error(None, exc.messages[0])
            except IntegrityError:
                form.add_error(
                    None, "Bu numara veya satır başka bir işlemde kullanıldı. Sayfayı yenileyin."
                )
            else:
                messages.success(request, "Müvekkil kaydedildi.")
                _, updated = _source()
                pending = [item for item in updated if item.status != "done"]
                next_row = next((item for item in pending if item.number > row.number), None)
                next_row = next_row or (pending[0] if pending else None)
                if next_row:
                    return redirect(reverse("imports:poa_review_detail", args=[next_row.number]))
                return redirect("imports:poa_review")
        return render(
            request, "imports/poa_detail.html", self._context(source_hash, rows, row, form)
        )
