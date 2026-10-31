"""Resmî WhatsApp hizmetine erişim. Erişim bilgileri yalnızca ortamdan okunur."""

import http.client
import json
import os
import re
import urllib.error
import urllib.request

from django.conf import settings


def config(name):
    return str(os.environ.get(name) or getattr(settings, name, "") or "").strip()


def configured():
    return bool(
        all(
            config(name)
            for name in ("WHATSAPP_ACCESS_TOKEN", "WHATSAPP_APP_SECRET", "WHATSAPP_VERIFY_TOKEN")
        )
        and re.fullmatch(r"[0-9]+", config("WHATSAPP_PHONE_NUMBER_ID"))
        and re.fullmatch(r"v[0-9]+\.[0-9]+", config("WHATSAPP_API_VERSION"))
    )


class DeliveryError(Exception):
    def __init__(self, message, *, uncertain=False):
        super().__init__(message)
        self.uncertain = uncertain


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def deliver(message, language):
    if not configured():
        raise DeliveryError("Resmî WhatsApp bağlantısı henüz kurulmadı.")
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": message.phone_number,
    }
    if message.template_name:
        template = {"name": message.template_name, "language": {"code": language}}
        if message.template_parameters:
            template["components"] = [
                {
                    "type": "body",
                    "parameters": [
                        {"type": "text", "text": value} for value in message.template_parameters
                    ],
                }
            ]
        payload.update(type="template", template=template)
    else:
        payload.update(type="text", text={"body": message.body, "preview_url": False})
    request = urllib.request.Request(
        "https://graph.facebook.com/"
        f"{config('WHATSAPP_API_VERSION')}/{config('WHATSAPP_PHONE_NUMBER_ID')}/messages",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": "Bearer " + config("WHATSAPP_ACCESS_TOKEN"),
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        opener = urllib.request.build_opener(NoRedirect)
        with opener.open(request, timeout=15) as response:
            data = response.read(1024 * 1024 + 1)
    except urllib.error.HTTPError as exc:
        # Hizmetin ham yanıtı numara/metin içerebilir; ekrana veya kayda yazılmaz.
        raise DeliveryError(
            "WhatsApp gönderimi kabul etmedi. Bağlantıyı ve onaylı mesajları kontrol edin.",
            uncertain=exc.code >= 500,
        ) from None
    except (OSError, http.client.HTTPException):
        raise DeliveryError(
            "Bağlantı kesildi; mesajın gidip gitmediği kontrol edilmeli. "
            "Otomatik tekrar gönderilmedi.",
            uncertain=True,
        ) from None
    try:
        if len(data) > 1024 * 1024:
            raise ValueError
        external_id = json.loads(data)["messages"][0]["id"]
        if not isinstance(external_id, str) or not external_id or len(external_id) > 200:
            raise ValueError
        return external_id
    except (ValueError, TypeError, KeyError, IndexError):
        raise DeliveryError(
            "Gönderim yanıtı okunamadı; WhatsApp üzerinden kontrol edin.", uncertain=True
        ) from None
