"""Sandbox testinde GitHub Releases API'sinin yerine geçen küçük sunucu.

Kök klasördeki dosyaları sunar; uzantısız dosyalar (ör. releases/latest) JSON olarak döner.
Kullanım: python -I fakeapi.py <kök klasör> <port>
"""

import functools
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer


class Handler(SimpleHTTPRequestHandler):
    extensions_map = {"": "application/json", ".exe": "application/octet-stream"}

    def log_message(self, format, *args):  # noqa: A002
        pass


if __name__ == "__main__":
    root, port = sys.argv[1], int(sys.argv[2])
    handler = functools.partial(Handler, directory=root)
    ThreadingHTTPServer(("127.0.0.1", port), handler).serve_forever()
