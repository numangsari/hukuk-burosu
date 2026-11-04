"""Eşleştirilmiş tebligat belgelerini dosya klasöründe saklar."""

import hashlib
import logging
from pathlib import Path

from django.contrib import messages
from django.db import transaction

from apps.core import folders

log = logging.getLogger(__name__)


def schedule_notice_copy(notice, request=None):
    if not notice.resolution_case_id:
        return

    def copy_after_commit():
        try:
            copy_notice_documents(notice)
        except folders.FolderError as error:
            log.warning("Tebligat belgeleri ofis klasörüne kopyalanamadı.")
            if request is not None:
                messages.warning(request, str(error))

    transaction.on_commit(copy_after_commit)


def copy_notice_documents(notice):
    if not notice.resolution_case_id:
        return 0
    directory = folders.notice_dir(notice.resolution_case)
    count = 0
    for document in notice.documents.all().order_by("pk"):
        name = Path(document.original_name.replace("\\", "/"))
        filename = (
            f"{notice.pk}-{document.pk} {folders.sanitize(name.stem, 100)}{name.suffix.lower()}"
        )
        target = directory / filename
        if target.is_symlink():
            raise folders.FolderError("Tebligat hedefi güvenli değil.")
        try:
            with document.file.open("rb") as source:
                content = source.read()
            if target.exists():
                if (
                    not target.is_file()
                    or hashlib.sha256(target.read_bytes()).digest()
                    != hashlib.sha256(content).digest()
                ):
                    raise folders.FolderError(
                        "Tebligat klasöründe farklı içerikli aynı adlı dosya var."
                    )
            else:
                created = False
                try:
                    with target.open("xb") as output:
                        created = True
                        output.write(content)
                except OSError:
                    if created:
                        target.unlink(missing_ok=True)
                    raise
        except FileNotFoundError as e:
            raise folders.FolderError("Tebligatın kaynak belgesi bulunamadı.") from e
        except (OSError, ValueError) as e:
            raise folders.FolderError("Tebligat belgesi klasöre kopyalanamadı.") from e
        count += 1
    return count
