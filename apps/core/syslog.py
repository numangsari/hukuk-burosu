"""Uygulama günlüğünü (app.log) yönetici ekranı için ayrıştırır; yalnızca okur."""

import datetime as dt
import re
from dataclasses import dataclass, field
from pathlib import Path

# prod.py'deki biçim: "2026-11-09 14:02:11,123 ERROR django.request: ileti"
ENTRY_START = re.compile(
    r"^(?P<time>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})[,.]\d+ "
    r"(?P<level>[A-Z]+) (?P<logger>[\w.]+): ?(?P<text>.*)$"
)
MAX_READ_BYTES = 1_000_000
LEGACY_TITLE = "Eski biçimli kayıtlar (saat bilgisi yok)"


@dataclass
class LogEntry:
    time: dt.datetime | None
    level: str
    logger: str
    title: str
    lines: list[str] = field(default_factory=list)

    @property
    def detail(self) -> str:
        return "\n".join(self.lines)

    @property
    def summary(self) -> str:
        """Kısa neden: son satır (özel durum iletisi) varsa o, yoksa başlık."""
        for line in reversed(self.lines):
            if line.strip():
                return line.strip()[:300]
        return self.title[:300]


def _tail_text(path: Path, max_bytes: int) -> str:
    size = path.stat().st_size
    with path.open("rb") as handle:
        if size > max_bytes:
            handle.seek(size - max_bytes)
            handle.readline()  # yarım satırı at
        raw = handle.read()
    return raw.decode("utf-8", errors="replace")


def read_recent_entries(path, limit: int = 50, levels=("WARNING", "ERROR", "CRITICAL")):
    """Günlüğün sonundan en yeni `limit` kaydı, yeniden eskiye doğru döndürür.

    Dosya yoksa ya da okunamazsa boş liste döner (arayüz bunu "kayıt yok" gösterir).
    """
    path = Path(path)
    try:
        text = _tail_text(path, MAX_READ_BYTES)
    except OSError:
        return []
    entries: list[LogEntry] = []
    current: LogEntry | None = None
    for line in text.splitlines():
        match = ENTRY_START.match(line)
        if match:
            current = LogEntry(
                time=dt.datetime.strptime(match["time"], "%Y-%m-%d %H:%M:%S"),
                level=match["level"],
                logger=match["logger"],
                title=match["text"],
            )
            entries.append(current)
            continue
        if current is None:
            # Saat biçimi eklenmeden önce yazılmış satırlar tek bir blokta toplanır.
            current = LogEntry(time=None, level="", logger="", title=LEGACY_TITLE)
            entries.append(current)
        current.lines.append(line)
    wanted = [e for e in entries if not e.level or e.level in levels]
    wanted.reverse()
    return wanted[:limit]


def count_since(entries, since: dt.datetime, levels=("ERROR", "CRITICAL")) -> int:
    return sum(1 for e in entries if e.time and e.time >= since and e.level in levels)
