"""Görev dilekçe şablonlarını koruyarak hazırlama yardımcıları."""

import io
import re
import zipfile
from xml.etree import ElementTree

from django.core.exceptions import ValidationError


def fill_udf(data: bytes, values: dict[str, str], required: set[str] | None = None) -> bytes:
    """İmzalanmamış UDF içinde boş, tanınan alanları doldurur."""
    try:
        source = zipfile.ZipFile(io.BytesIO(data))
        if any(name.lower().endswith(".sgn") for name in source.namelist()):
            raise ValidationError("İmzalı belge şablon olarak kullanılamaz.")
        if source.getinfo("content.xml").file_size > 10 * 1024 * 1024:
            raise ValidationError("Şablon içeriği çok büyük.")
        if sum(item.file_size for item in source.infolist()) > 50 * 1024 * 1024:
            raise ValidationError("Şablon içeriği çok büyük.")
        raw = source.read("content.xml")
        root = ElementTree.fromstring(raw)
    except (zipfile.BadZipFile, KeyError, ElementTree.ParseError) as exc:
        raise ValidationError("UDF şablonu okunamadı.") from exc
    content = root.find("content")
    elements = root.find("elements")
    if content is None or elements is None or content.text is None:
        raise ValidationError("UDF şablonunun düzeni tanınmadı.")
    text = content.text
    # Adres alanı, hemen üzerindeki taraf satırına aittir.
    insertions = []
    filled = set()
    previous = None
    labels = {
        "DAVACI": "davaci",
        "DAVALI": "davali",
        "MAHKEME": "mahkeme",
        "DOSYA NO": "dosya_no",
        "ESAS NO": "dosya_no",
        "ESAS NUMARASI": "dosya_no",
        "KONU": "konu",
    }
    for match in re.finditer(r"(?m)^([^:\n]+):([^\n]*)", text):
        label = " ".join(match.group(1).split()).upper()
        if label in labels:
            previous = labels[label]
            key = previous
        elif label == "ADRES" and previous in ("davaci", "davali"):
            key = previous + "_adres"
        else:
            previous = None
            continue
        if not match.group(2).strip() and values.get(key):
            insertions.append((match.end(2), values[key].replace("\n", " ").strip()))
            filled.add(key)
    if required and not required.issubset(filled):
        raise ValidationError(
            "Şablonda gerekli alanlar bulunamadı veya dosyada mahkeme ve numara bilgisi eksik."
        )
    if not insertions:
        raise ValidationError("Şablonda doldurulabilecek boş alan bulunamadı.")
    spans = list(elements.iter("content"))
    for position, value in reversed(insertions):
        offset = len(text[:position].encode("utf-16-le")) // 2
        size = len(value.encode("utf-16-le")) // 2
        target = next(
            (
                s
                for s in spans
                if int(s.get("startOffset", "-1"))
                <= offset
                < int(s.get("startOffset", "-1")) + int(s.get("length", "0"))
            ),
            None,
        )
        if target is None:
            raise ValidationError("Şablondaki bir alanın biçimi tanınmadı.")
        for span in spans:
            start = int(span.get("startOffset", "0"))
            if span is target:
                span.set("length", str(int(span.get("length", "0")) + size))
            elif start > offset:
                span.set("startOffset", str(start + size))
        text = text[:position] + value + text[position:]
    # UDF yazıcısı kök metni CDATA olarak saklar; diğer XML bölümlerini korur.
    if "]] >".replace(" ", "") in text:
        raise ValidationError("Şablon alanında desteklenmeyen karakter dizisi var.")
    escaped = text.encode("utf-8")
    # Alan aralıklarını güncellemek için XML yazılır, ardından CDATA geri konur.
    content.text = "UDF_CONTENT_MARKER"
    xml = ElementTree.tostring(root, encoding="utf-8", xml_declaration=True)
    xml = xml.replace(b"UDF_CONTENT_MARKER", b"<![CDATA[" + escaped + b"]]>", 1)
    output = io.BytesIO()
    with source, zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for item in source.infolist():
            archive.writestr(
                item, xml if item.filename == "content.xml" else source.read(item.filename)
            )
    return output.getvalue()


def fill_docx(data: bytes, values: dict[str, str], required: set[str] | None = None) -> bytes:
    """Word belgesindeki tanınan boş alanları doldurur."""
    from xml.dom import minidom
    from xml.parsers.expat import ExpatError

    namespace = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    try:
        source = zipfile.ZipFile(io.BytesIO(data))
        if any(name.startswith("_xmlsignatures/") for name in source.namelist()):
            raise ValidationError("İmzalı belge şablon olarak kullanılamaz.")
        if sum(item.file_size for item in source.infolist()) > 50 * 1024 * 1024:
            raise ValidationError("Şablon içeriği çok büyük.")
        raw = source.read("word/document.xml")
        root = minidom.parseString(raw)
    except (zipfile.BadZipFile, KeyError, ExpatError) as exc:
        raise ValidationError("Word şablonu okunamadı.") from exc
    labels = {
        "DAVACI": "davaci",
        "DAVALI": "davali",
        "MAHKEME": "mahkeme",
        "DOSYA NO": "dosya_no",
        "ESAS NO": "dosya_no",
        "ESAS NUMARASI": "dosya_no",
        "KONU": "konu",
    }
    previous = None
    filled = set()
    for paragraph in root.getElementsByTagNameNS(namespace, "p"):
        nodes = list(paragraph.getElementsByTagNameNS(namespace, "t"))
        if not nodes:
            continue
        line = "".join(
            "".join(child.data for child in node.childNodes if child.nodeType == child.TEXT_NODE)
            for node in nodes
        )
        match = re.fullmatch(r"\s*([^:\n]+):([^\n]*)", line)
        if not match:
            if line.strip():
                previous = None
            continue
        label = " ".join(match.group(1).split()).upper()
        if label in labels:
            previous = labels[label]
            key = previous
        elif label == "ADRES" and previous in ("davaci", "davali"):
            key = previous + "_adres"
        else:
            previous = None
            continue
        if not match.group(2).strip() and values.get(key):
            nodes[-1].appendChild(root.createTextNode(" " + values[key].replace("\n", " ").strip()))
            nodes[-1].setAttribute("xml:space", "preserve")
            filled.add(key)
    if required and not required.issubset(filled):
        raise ValidationError("Şablonda gerekli alanlar bulunamadı veya dosya bilgileri eksik.")
    if not filled:
        raise ValidationError("Şablonda doldurulabilecek boş alan bulunamadı.")
    xml = root.toxml(encoding="utf-8")
    output = io.BytesIO()
    with source, zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for item in source.infolist():
            archive.writestr(
                item, xml if item.filename == "word/document.xml" else source.read(item.filename)
            )
    return output.getvalue()


def person_name(first_name: str, last_name: str) -> str:
    """Adı Türkçe kuralla baş harfleri büyük, soyadı bütünüyle büyük gösterir."""
    from apps.core.text import tr_capitalize_words, tr_lower, tr_upper

    return f"{tr_capitalize_words(tr_lower(first_name))} {tr_upper(last_name)}".strip()


def party_name(party) -> str:
    """Gerçek kişide son sözcüğü soyadı kabul eder; tüzel unvanı korur."""
    if party.kind != "person":
        return party.name
    words = party.name.strip().split()
    return person_name(" ".join(words[:-1]), words[-1]) if words else ""


def client_name(client) -> str:
    """Gerçek kişide ayrı tutulan ad ve soyadı kullanır; tüzel unvanı korur."""
    return (
        person_name(client.first_name, client.last_name) if client.kind == "person" else client.name
    )
