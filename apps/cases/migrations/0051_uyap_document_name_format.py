import re
from pathlib import PurePath

from django.db import migrations

_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def reformat_uyap_document_names(apps, schema_editor):
    """UYAP evraklarının başlığını "Kapalı Tebligat · 14/10/2026", dosya adını
    "14-10-2026 Kapalı Tebligat.pdf" biçimine getirir (dosya adında "/" kullanılamaz)."""
    Document = apps.get_model("cases", "Document")
    for document in Document.objects.filter(source="uyap"):
        kind = _UNSAFE.sub("-", document.uyap_type or "").strip()
        date_value = document.document_date
        title = kind or "UYAP evrakı"
        if date_value:
            title = f"{kind or 'UYAP evrakı'} · {date_value:%d/%m/%Y}"
        stem = f"{date_value:%d-%m-%Y} {kind}".strip() if date_value else (kind or "UYAP evrakı")
        stem = re.sub(r"\s+", " ", stem).strip(" .")[:150] or "UYAP evrakı"
        suffix = PurePath(document.original_name or "").suffix.lower() or ".pdf"
        Document.objects.filter(pk=document.pk).update(
            title=title[:300], original_name=(stem + suffix)[:300]
        )


class Migration(migrations.Migration):
    dependencies = [
        ("cases", "0050_document_source"),
    ]

    operations = [
        migrations.RunPython(reformat_uyap_document_names, migrations.RunPython.noop),
    ]
