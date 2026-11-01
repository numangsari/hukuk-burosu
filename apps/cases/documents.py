"""Belgelerin ofis klasörüne kopyalanması ve görev belgelerinin dosyaya aktarılması."""

import logging
from pathlib import Path

from django.core.files.base import ContentFile
from django.utils import timezone

from apps.core import folders

from .models import Document, DocumentCategory

log = logging.getLogger(__name__)

NOT_CONFIGURED = (
    "Ofis klasörü ayarlanmadığı için belge klasöre kopyalanmadı (Ayarlar > Belge klasörü)."
)

TYPE_CATEGORY = {"dilekçe": DocumentCategory.PETITION, "bilirkişi": DocumentCategory.EXPERT}


def mirror_document(doc: Document, filename: str | None = None) -> str:
    """Dosya belgesini dosya klasörüne kopyalar. Uyarı metni döner (sorun yoksa boş)."""
    if folders.root() is None:
        return NOT_CONFIGURED
    try:
        target = folders.copy_file(
            doc.file, folders.case_dir(doc.case), filename or doc.original_name
        )
    except folders.FolderError as e:
        log.warning("Belge klasöre kopyalanamadı: %s", e)
        return str(e)
    doc.folder_path = str(target)
    Document.objects.filter(pk=doc.pk).update(folder_path=doc.folder_path)
    return ""


def mirror_poa(poa) -> str:
    """Vekalet PDF'ini müvekkilin Vekaletler klasörüne kopyalar."""
    if not poa.pdf:
        return ""
    if folders.root() is None:
        return NOT_CONFIGURED
    name = f"{poa.date:%Y-%m-%d} {poa.notary} {poa.journal_no}{Path(poa.pdf.name).suffix}"
    try:
        target = folders.copy_file(poa.pdf, folders.poa_dir(poa.client), name)
    except folders.FolderError as e:
        log.warning("Vekalet klasöre kopyalanamadı: %s", e)
        return str(e)
    type(poa).objects.filter(pk=poa.pk).update(folder_path=str(target))
    return ""


def mirror_retainer(agreement) -> str:
    """Avukatlık sözleşmesi PDF'ini müvekkilin Sözleşmeler klasörüne kopyalar."""
    if not agreement.pdf:
        return ""
    if folders.root() is None:
        return NOT_CONFIGURED
    name = f"{agreement.signed_on:%Y-%m-%d} Avukatlık sözleşmesi{Path(agreement.pdf.name).suffix}"
    try:
        target = folders.copy_file(agreement.pdf, folders.retainer_dir(agreement.client), name)
    except folders.FolderError as e:
        log.warning("Avukatlık sözleşmesi klasöre kopyalanamadı: %s", e)
        return str(e)
    type(agreement).objects.filter(pk=agreement.pk).update(folder_path=str(target))
    return ""


def publish_task_documents(task, user) -> tuple[list[Document], list[str]]:
    """Onaylanan görevin güncel belgelerini dosyanın Belgeler'ine ekler ve klasöre kopyalar."""
    current = list(task.documents.filter(is_current=True).order_by("created_at"))
    category = next(
        (c for key, c in TYPE_CATEGORY.items() if key in task.task_type.name.lower()),
        DocumentCategory.OTHER,
    )
    created, warnings = [], []
    date = timezone.localdate()
    for td in current:
        suffix = Path(td.original_name).suffix.lower()
        title = task.title if len(current) == 1 else f"{task.title} - {Path(td.original_name).stem}"
        td.file.open("rb")
        try:
            content = td.file.read()
        finally:
            td.file.close()
        doc = Document(
            case=task.case,
            title=title[:300],
            category=category,
            original_name=td.original_name,
            notes=f"Görevden: {task.title} (onaylayan {user})",
            created_by=td.uploaded_by,
        )
        doc.file.save(td.original_name, ContentFile(content), save=False)
        doc.save()
        created.append(doc)
        warn = mirror_document(doc, f"{date:%Y-%m-%d} {title}{suffix}")
        if warn and warn not in warnings:
            warnings.append(warn)
    return created, warnings
