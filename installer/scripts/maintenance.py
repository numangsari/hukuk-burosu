"""Güncelleme sırasında port 80'de "Güncelleniyor" sayfası sunar.

updater.ps1 uygulama servisini durdurduktan sonra bu betiği, kurulumdan etkilenmeyen yedek
Python kopyasıyla çalıştırır. Her adrese aynı sayfayı 503 koduyla döndürür; sayfa 15 saniyede
bir kendini yeniler, uygulama yeniden açılınca kullanıcı normal ekrana geçer.
Kullanım: python -I maintenance.py [port]
"""

import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PAGE = """<!doctype html>
<html lang="tr"><head><meta charset="utf-8">
<meta http-equiv="refresh" content="15">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Güncelleniyor</title>
<style>
body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
background:#eef2f6;color:#1f2937;font-family:Segoe UI,Arial,sans-serif}
main{background:#fff;border-radius:12px;box-shadow:0 2px 12px rgba(31,58,99,.12);
padding:32px 40px;max-width:460px;text-align:center}
h1{color:#1F3A63;font-size:1.4rem;margin:0 0 12px}
p{margin:6px 0;line-height:1.5}
</style></head>
<body><main>
<h1>Program güncelleniyor</h1>
<p>Hukuk Bürosu Otomasyonu yeni sürüme geçiyor. Bu birkaç dakika sürer.</p>
<p>Sayfa kendiliğinden yenilenecek; bir şey yapmanıza gerek yok.</p>
</main></body></html>
""".encode()


class MaintenanceHandler(BaseHTTPRequestHandler):
    def _send(self, body: bool) -> None:
        self.send_response(503)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(PAGE)))
        self.send_header("Retry-After", "15")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if body:
            self.wfile.write(PAGE)

    def do_GET(self):  # noqa: N802 - http.server adlandırması
        self._send(body=True)

    def do_HEAD(self):  # noqa: N802
        self._send(body=False)

    do_POST = do_GET

    def log_message(self, format, *args):  # noqa: A002 - istek günlüğü tutulmaz
        pass


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 80
    ThreadingHTTPServer(("0.0.0.0", port), MaintenanceHandler).serve_forever()


if __name__ == "__main__":
    main()
