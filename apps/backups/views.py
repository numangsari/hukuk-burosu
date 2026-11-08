from pathlib import Path

from django.contrib import messages
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.views import View

from apps.core.permissions import AdminRequiredMixin

from .models import BackupRecord
from .services import BackupError, dump_database, local_dir, run_backup


class BackupNowView(AdminRequiredMixin, View):
    def post(self, request):
        rec = run_backup(BackupRecord.Kind.MANUAL)
        if rec.status == BackupRecord.Status.OK:
            messages.success(request, f"Yedek alındı: {rec.file_name}")
            if rec.message:
                messages.warning(request, rec.message)
        else:
            messages.error(request, f"Yedek alınamadı: {rec.message}")
        target_section = request.POST.get("return_section", "klasor")
        if target_section not in {"klasor", "veri_aktarim", "monitor"}:
            target_section = "klasor"
        return redirect(f"{reverse('accounts:settings')}?bolum={target_section}")


class BackupDownloadView(AdminRequiredMixin, View):
    def get(self, request, pk):
        rec = get_object_or_404(BackupRecord, pk=pk, status=BackupRecord.Status.OK)
        if not rec.file_name or Path(rec.file_name).name != rec.file_name:
            raise Http404
        path = local_dir() / rec.file_name
        if not path.is_file() and rec.copied_to:
            alt = Path(rec.copied_to) / rec.file_name
            if alt.is_file():
                path = alt
        if not path.is_file():
            messages.error(request, "Yedek dosyası diskte bulunamadı.")
            return redirect(f"{reverse('accounts:settings')}?bolum=veri_aktarim")
        return FileResponse(path.open("rb"), as_attachment=True, filename=rec.file_name)


class ExportAllListsZipView(AdminRequiredMixin, View):
    def get(self, request):
        from apps.core.office_lists import export_all_lists_zip
        from apps.office.models import OfficeSettings

        data = export_all_lists_zip()
        stamp = timezone.localtime().strftime("%Y%m%d-%H%M")
        slug = OfficeSettings.load().slug
        response = HttpResponse(data, content_type="application/zip")
        response["Content-Disposition"] = f'attachment; filename="{slug}-tum-tablolar-{stamp}.zip"'
        return response


class ExportDatabaseDumpView(AdminRequiredMixin, View):
    """Veritabanının güncel dökümünü (`db.dump`, pg_dump özel biçimi) indirir."""

    def get(self, request):
        import os
        import tempfile

        fd, name = tempfile.mkstemp(prefix="db-", suffix=".dump")
        os.close(fd)
        path = Path(name)
        try:
            dump_database(path)
        except BackupError as e:
            path.unlink(missing_ok=True)
            messages.error(request, f"Veritabanı dökümü alınamadı: {e}")
            return redirect(f"{reverse('accounts:settings')}?bolum=veri_aktarim")
        try:
            data = path.read_bytes()
        finally:
            path.unlink(missing_ok=True)
        response = HttpResponse(data, content_type="application/octet-stream")
        response["Content-Disposition"] = 'attachment; filename="db.dump"'
        response["Cache-Control"] = "private, no-store"
        return response


class TriggerMonitorTaskView(AdminRequiredMixin, View):
    def post(self, request):
        task = request.POST.get("task", "")
        if task == "office_lists":
            from apps.core.office_lists import OfficeListsError, update_office_lists

            try:
                res = update_office_lists()
                if res.get("busy"):
                    messages.info(request, "Liste güncellemesi zaten çalışıyor.")
                elif res.get("issues"):
                    messages.warning(
                        request,
                        f"Listeler yenilendi ancak {len(res['issues'])} dosyada uyarı var.",
                    )
                else:
                    messages.success(request, "Güncel sistem listeleri yenilendi.")
            except OfficeListsError as exc:
                messages.error(request, f"Listeler yenilenemedi: {exc}")
        elif task == "seizure_tasks":
            from apps.cases.seizures import create_due_tasks

            created, skipped = create_due_tasks()
            messages.success(
                request,
                f"Haciz takibi kontrol edildi: {len(created)} yeni görev oluşturuldu"
                + (f", {skipped} dosya pasif sorumlu nedeniyle atlandı." if skipped else "."),
            )
        return redirect(f"{reverse('accounts:settings')}?bolum=monitor")
