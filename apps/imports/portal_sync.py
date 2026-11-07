"""Deneme eklentisinin yalnızca yerel ve yetkili aktarım uçları."""

import base64
import binascii
import hashlib
import ipaddress
import json
import secrets
import unicodedata
from datetime import UTC, datetime, timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_not_required, login_required, user_passes_test
from django.db import transaction
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.accounts.models import User

from .models import (
    PortalCapture,
    PortalCase,
    PortalConnection,
    PortalLawyerAccess,
    PortalNotice,
    PortalNoticeDocument,
)
from .portal_ingest import (
    DocumentRejected,
    check_import_access,
    clean,
    digest,
    import_captures,
    import_notice_document,
    import_uyap_document,
    merge_portal_data,
)

UYAP_PATHS = {
    "/search_phrase_detayli.ajx",
    "/dosyaAyrintiBilgileri_brd.ajx",
    "/dosya_taraf_bilgileri_brd.ajx",
    "/list_dosya_evraklar.ajx",
    "/avukat_durusma_sorgula_brd.ajx",
    "/dosya_tahsilat_reddiyat_bilgileri_brd.ajx",
}


def normalized_lawyer_name(value):
    """Türkçe harflerin büyük ve küçük biçimlerini eşitle."""
    if not isinstance(value, str) or not value or len(value) > 200:
        return ""
    return unicodedata.normalize("NFC", value).replace("I", "ı").replace("İ", "i").lower()


def find_name_permission(name, permission):
    """İzinli avukatlarda tek bir tam ad eşleşmesi bulunursa döndür."""
    normalized = normalized_lawyer_name(name)
    if not normalized:
        return None
    candidates = (
        PortalLawyerAccess.objects.select_related("user")
        .select_for_update()
        .filter(
            user__is_active=True,
            user__role__in=[User.Role.ADMIN, User.Role.SENIOR, User.Role.LAWYER],
            **{permission: True},
        )
    )
    matches = [
        p for p in candidates if normalized_lawyer_name(p.user.get_full_name()) == normalized
    ]
    return matches[0] if len(matches) == 1 else None


def local_request(request):
    try:
        ip = ipaddress.ip_address(request.META.get("REMOTE_ADDR", ""))
        if ip.is_loopback:
            return True
        # Özel ofis ağı (RFC 1918: 10.x, 172.16-31.x, 192.168.x)
        return (
            ip in ipaddress.ip_network("10.0.0.0/8")
            or ip in ipaddress.ip_network("172.16.0.0/12")
            or ip in ipaddress.ip_network("192.168.0.0/16")
        )
    except ValueError:
        return False


def can_pair(user):
    """Eklenti yalnızca ana bilgisayarda, yönetici tarafından eşleştirilir."""
    try:
        check_import_access(user)
    except RuntimeError:
        return False
    return True


@login_required
@never_cache
def pair(request):
    if not local_request(request) or not can_pair(request.user):
        raise Http404
    key = None
    if request.method == "POST":
        key = secrets.token_urlsafe(32)
        PortalConnection.objects.create(
            owner=request.user, key_hash=hashlib.sha256(key.encode("ascii")).hexdigest()
        )
    return render(request, "imports/portal_pair.html", {"pair_key": key})


@login_required
@never_cache
def indicator(request):
    """Üst çubuk göstergesini yenileyen parça (HTMX ile dakikada bir çağrılır)."""
    from .portal_status import portal_indicator

    return render(request, "imports/_portal_indicator.html", portal_indicator(request.user))


HEALTH_STATES = {
    "bekliyor",
    "basladi",
    "tamamlandi",
    "eksik",
    "oturum_yok",
    "sunucu_yok",
    "sekme_hazir_degil",
    "sekme_yok",
    "durduruldu",
    "izin_yok",
}


def health_time(value, now):
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        return None
    try:
        result = datetime.fromtimestamp(value / 1000, tz=UTC)
    except (OverflowError, ValueError, OSError):
        return None
    return result if result <= now + timedelta(minutes=1) else None


@login_not_required
@csrf_exempt
@require_POST
def health(request):
    if not local_request(request) or request.content_type != "application/json":
        raise Http404
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer ") or len(auth) > 128:
        return JsonResponse({"error": "Bağlantı yetkisi yok."}, status=403)
    key_hash = hashlib.sha256(auth[7:].encode("utf-8")).hexdigest()
    connection = (
        PortalConnection.objects.select_related("owner")
        .filter(key_hash=key_hash, active=True)
        .first()
    )
    if not connection or not connection.owner.is_active:
        return JsonResponse({"error": "Bağlantı yetkisi yok."}, status=403)
    try:
        check_import_access(connection.owner)
        if int(request.META.get("CONTENT_LENGTH") or 0) > 4096:
            raise ValueError
        body = json.loads(request.body)
        if not isinstance(body, dict):
            raise ValueError
        now = timezone.now()
        connection.last_seen = now
        fields = ["last_seen"]
        for source in ("uyap", "uets"):
            state = body.get(source)
            if not isinstance(state, dict) or state.get("status", "bekliyor") not in HEALTH_STATES:
                raise ValueError
            setattr(connection, f"{source}_status", state.get("status", "bekliyor"))
            fields.append(f"{source}_status")
            for key, suffix in (("attempted", "attempt_at"), ("completed", "success_at")):
                stamp = health_time(state.get(key), now)
                if stamp:
                    field = f"{source}_{suffix}"
                    current = getattr(connection, field)
                    if not current or stamp > current:
                        setattr(connection, field, stamp)
                        fields.append(field)
            session = state.get("session")
            if isinstance(session, dict) and isinstance(session.get("ok"), bool):
                stamp = health_time(session.get("at"), now)
                if stamp:
                    setattr(connection, f"{source}_session_ok", session["ok"])
                    setattr(connection, f"{source}_session_at", stamp)
                    fields += [f"{source}_session_ok", f"{source}_session_at"]
                    # Tarayıcıda açık hesap, izinli avukatlardan biriyle eşleşiyorsa ona bağlanır.
                    name = session.get("name")
                    account = None
                    if isinstance(name, str) and 0 < len(name) <= 200:
                        with transaction.atomic():
                            account = find_name_permission(name, f"{source}_enabled")
                    setattr(connection, f"{source}_account", account)
                    fields.append(f"{source}_account")
        # Sık durum bildirimleri kullanıcı işlem geçmişini gereksiz doldurmaz.
        updated = PortalConnection.objects.filter(pk=connection.pk, active=True).update(
            **{field: getattr(connection, field) for field in fields}
        )
        if not updated:
            return JsonResponse({"error": "Bağlantı yetkisi yok."}, status=403)
    except (ValueError, TypeError, UnicodeDecodeError, RuntimeError):
        return JsonResponse({"error": "Durum bilgisi doğrulanamadı."}, status=400)
    return JsonResponse({"ok": True, "sync_enabled": True})


@login_not_required
@csrf_exempt
@require_POST
def check_name(request):
    if not local_request(request) or request.content_type != "application/json":
        raise Http404
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer ") or len(auth) > 128:
        return JsonResponse({"ok": False}, status=403)
    key_hash = hashlib.sha256(auth[7:].encode("utf-8")).hexdigest()
    connection = (
        PortalConnection.objects.select_related("owner")
        .filter(key_hash=key_hash, active=True, owner__is_active=True)
        .first()
    )
    if not connection:
        return JsonResponse({"ok": False}, status=403)
    try:
        check_import_access(connection.owner)
        if int(request.META.get("CONTENT_LENGTH") or 0) > 4096:
            raise ValueError
        body = json.loads(request.body)
        if not isinstance(body, dict) or body.get("source") not in {"uyap", "uets"}:
            raise ValueError
        with transaction.atomic():
            allowed = find_name_permission(body.get("name"), body["source"] + "_enabled")
            return JsonResponse({"ok": bool(allowed)})
    except (ValueError, TypeError, UnicodeDecodeError, RuntimeError):
        return JsonResponse({"ok": False}, status=400)


@login_required
@user_passes_test(lambda user: user.is_office_admin)
@require_POST
def toggle_access(request, pk, source):
    if source not in {"uyap", "uets"}:
        raise Http404
    with transaction.atomic():
        access = get_object_or_404(PortalLawyerAccess.objects.select_for_update(), pk=pk)
        field = f"{source}_enabled"
        setattr(access, field, not getattr(access, field))
        access.save(update_fields=[field])
    messages.success(request, "Kişi izni güncellendi.")
    return redirect("/hesap/ayarlar/?bolum=eklenti")


@login_required
@user_passes_test(lambda user: user.is_office_admin)
@never_cache
def remove_access(request, pk):
    access = get_object_or_404(PortalLawyerAccess.objects.select_related("user"), pk=pk)
    if request.method == "GET":
        return render(request, "imports/portal_remove_access.html", {"access": access})
    if request.method != "POST" or request.POST.get("choice") not in {"keep", "delete"}:
        raise Http404
    with transaction.atomic():
        access = get_object_or_404(
            PortalLawyerAccess.objects.select_for_update().select_related("user"), pk=pk
        )
        if request.POST["choice"] == "delete":
            for model in (PortalCapture, PortalCase, PortalNotice):
                records = model.objects.select_for_update().filter(source_users=access.user)
                for record in records:
                    shared = (
                        record.source_unknown
                        or record.source_users.exclude(pk=access.user_id).exists()
                    )
                    if shared:
                        record.source_users.remove(access.user)
                        continue
                    if isinstance(record, PortalNotice):
                        for doc in PortalNoticeDocument.objects.filter(notice=record):
                            storage, name = doc.file.storage, doc.file.name
                            doc.delete()
                            if name and not PortalNoticeDocument.objects.filter(file=name).exists():
                                transaction.on_commit(
                                    lambda storage=storage, name=name: storage.delete(name),
                                    robust=True,
                                )
                    record.delete()
        access.delete()
    messages.success(request, "Kişi izni kaldırıldı.")
    return redirect("/hesap/ayarlar/?bolum=eklenti")


@login_required
@user_passes_test(lambda user: user.is_office_admin)
@require_POST
def disconnect(request, pk):
    connection = get_object_or_404(PortalConnection, pk=pk, active=True)
    connection.active = False
    connection.save(update_fields=["active"])
    messages.success(request, "Eklenti bağlantısı durduruldu.")
    return redirect("/hesap/ayarlar/?bolum=eklenti")


@login_not_required
@csrf_exempt
@require_POST
def receive(request):
    if not local_request(request) or request.content_type != "application/json":
        raise Http404
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer ") or len(auth) > 128:
        return JsonResponse({"error": "Bağlantı yetkisi yok."}, status=403)
    key_hash = hashlib.sha256(auth[7:].encode("utf-8")).hexdigest()
    connection = (
        PortalConnection.objects.select_related("owner")
        .filter(key_hash=key_hash, active=True)
        .first()
    )
    if not connection:
        return JsonResponse({"error": "Bağlantı yetkisi yok."}, status=403)
    try:
        check_import_access(connection.owner)
        if int(request.META.get("CONTENT_LENGTH") or 0) > 28_000_000:
            raise ValueError
        body = json.loads(request.body)
        if not isinstance(body, dict):
            raise ValueError
        source = body.get("type")
        identity = body.get("identity")
        if source not in {"uyap", "notice", "uyap_document"}:
            raise ValueError
        name = body.get("lawyer_name")
        permission = "uets_enabled" if source == "notice" else "uyap_enabled"
        with transaction.atomic():
            if name is not None:
                allowed = find_name_permission(name, permission)
            elif (
                isinstance(identity, str)
                and len(identity) == 11
                and identity.isascii()
                and identity.isdigit()
            ):
                allowed = (
                    PortalLawyerAccess.objects.select_related("user")
                    .select_for_update()
                    .filter(
                        identity_number=identity,
                        user__is_active=True,
                        user__role__in=[User.Role.ADMIN, User.Role.SENIOR, User.Role.LAWYER],
                        **{permission: True},
                    )
                    .first()
                )
            else:
                allowed = None
            if not allowed:
                return JsonResponse(
                    {"error": "Kişi için bu kaynaktan aktarım izni yok."}, status=403
                )
            if source == "uyap_document":
                if not getattr(settings, "PORTAL_UYAP_AUTOMATION_ENABLED", True):
                    return JsonResponse({"error": "UYAP otomatik taraması durduruldu."}, status=403)
                import_uyap_document(body, allowed.user)
            elif source == "uyap":
                if not getattr(settings, "PORTAL_UYAP_AUTOMATION_ENABLED", True):
                    return JsonResponse({"error": "UYAP otomatik taraması durduruldu."}, status=403)
                items = body.get("captures")
                if not isinstance(items, list) or not 1 <= len(items) <= 100:
                    raise ValueError
                if any(
                    not isinstance(item, dict)
                    or item.get("source") != "UYAP"
                    or item.get("path") not in UYAP_PATHS
                    for item in items
                ):
                    raise ValueError
                import_captures(items, connection.owner, source_user=allowed.user)
            elif body.get("type") == "notice":
                row, details = body.get("list"), body.get("details")
                if not isinstance(row, dict) or not isinstance(details, dict):
                    raise ValueError
                ident = row.get("id") or row.get("messages_id")
                if not ident or len(str(ident)) > 256:
                    raise ValueError
                import_captures(
                    [{"source": "UETS", "path": "/v1/messages", "data": [row]}],
                    connection.owner,
                    source_user=allowed.user,
                )
                notice = PortalNotice.objects.select_for_update().get(
                    fingerprint=digest(["UETS", str(ident)])
                )
                data = dict(notice.data) if isinstance(notice.data, dict) else {}
                data["ayrinti"] = merge_portal_data(data.get("ayrinti", {}), clean(details))
                notice.data = data
                notice.save(update_fields=["data"])
                document = body.get("document")
                if document is not None:
                    if not isinstance(document, dict) or not isinstance(
                        document.get("content"), str
                    ):
                        raise ValueError
                    content = base64.b64decode(document["content"], validate=True)
                    import_notice_document(
                        notice,
                        str(document.get("partId") or ""),
                        content,
                        document.get("name"),
                        connection.owner,
                    )
            else:
                raise ValueError
    except DocumentRejected as error:
        return JsonResponse({"error": str(error)}, status=error.status)
    except (ValueError, TypeError, KeyError, RuntimeError, binascii.Error):
        return JsonResponse({"error": "Aktarım doğrulanamadı."}, status=400)
    return JsonResponse({"ok": True})
