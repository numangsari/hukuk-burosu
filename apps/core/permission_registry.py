"""Rol bazlı yetki matrisi: hangi rolün hangi işi yapabileceği.

Ayarlar > "Yetkiler ve çalışma düzeni" ekranındaki tek liste bu kayıt defterinden çizilir.
Seçimler `OfficeSettings.role_permissions` içinde saklanır ({yetki: [roller]}); kaydı olmayan
yetki için buradaki varsayılan roller geçerlidir. Yönetici her yetkide her zaman yetkilidir
ve ekranda kilitlidir.
"""

from dataclasses import dataclass

ROLES = [
    ("admin", "Yönetici"),
    ("senior", "Kıdemli Avukat"),
    ("lawyer", "Avukat"),
    ("intern", "Stajyer"),
    ("paralegal", "İcra Katibi"),
    ("secretary", "Sekreter"),
    ("accountant", "Muhasebe"),
]
ALL_ROLES = [key for key, _ in ROLES]
LAWYERS = ["admin", "senior", "lawyer"]
ADMIN_ONLY = ["admin"]


@dataclass(frozen=True)
class Permission:
    key: str
    group: str
    label: str
    help: str
    default: tuple


PERMISSIONS = [
    Permission(
        "cases.view_all",
        "Dosya ve müvekkil",
        "Tüm dosya ve müvekkilleri görme",
        "İşaretli olmayan roller yalnızca sorumlu veya görevli olduğu dosya ve müvekkilleri görür.",
        tuple(ALL_ROLES),
    ),
    Permission(
        "cases.reopen",
        "Dosya ve müvekkil",
        "Kapalı dosyayı yeniden açma",
        "",
        tuple(ADMIN_ONLY),
    ),
    Permission(
        "cases.remove_party", "Dosya ve müvekkil", "Dosyadan taraf çıkarma", "", tuple(ADMIN_ONLY)
    ),
    Permission("cases.delete", "Dosya ve müvekkil", "Dosya silme", "", tuple(ADMIN_ONLY)),
    Permission("clients.delete", "Dosya ve müvekkil", "Müvekkil silme", "", tuple(ADMIN_ONLY)),
    Permission(
        "tasks.close_without_review",
        "Görev",
        "Görevi kontrolcü onayı olmadan kapatma",
        "İşaretli rollere atanan görevde kontrolcü zorunlu değildir ve görev doğrudan kapanabilir; "
        "işaretsiz rollerde kontrolcü zorunludur.",
        tuple(),
    ),
    Permission(
        "tasks.edit_any",
        "Görev",
        "Başkasının açtığı görevi düzenleme",
        "Görevi oluşturan kişi kendi görevini her zaman düzenler.",
        ("admin", "senior"),
    ),
    Permission(
        "tasks.delete_any",
        "Görev",
        "Başkasının açtığı görevi silme",
        "Görevi oluşturan kişi kendi görevini her zaman silebilir.",
        tuple(ADMIN_ONLY),
    ),
    Permission(
        "tasks.routines",
        "Görev",
        "Rutin görev kurallarını yönetme",
        "",
        ("admin", "senior"),
    ),
    Permission(
        "notices.create_task",
        "Tebligat",
        "Tebligattan görev oluşturma",
        "",
        tuple(ALL_ROLES),
    ),
    Permission(
        "notices.no_task",
        "Tebligat",
        "Tebligatı görev yok diye işleme (yok sayma)",
        "",
        tuple(ALL_ROLES),
    ),
    Permission(
        "hearings.create_manual",
        "Duruşma",
        "Duruşmayı elle ekleme (duruşma, ön inceleme, keşif)",
        "Duruşmalar UYAP'tan otomatik gelir; elle ekleme UYAP kesintisi veya UYAP'ta olmayan "
        "kayıtlar içindir. Etkinlikler (toplantı, görüşme vb.) herkes tarafından eklenir.",
        tuple(ADMIN_ONLY),
    ),
    Permission("hearings.delete", "Duruşma", "Duruşma silme", "", tuple(ADMIN_ONLY)),
    Permission(
        "accounting.edit",
        "Muhasebe",
        "Muhasebe kaydı ekleme ve iptal etme",
        "Tahsilat, masraf ve vekalet ücreti hareketleri.",
        tuple(ALL_ROLES),
    ),
    Permission(
        "accounting.balances",
        "Muhasebe",
        "Bakiye, cari hesap ve finansal raporları görme",
        "Müvekkil bakiyesi, borçlu süzgeci, cari hesap ekstresi ve mali raporlar.",
        ("admin", "accountant"),
    ),
    Permission(
        "petition_pool.delete_any",
        "Dilekçe havuzu",
        "Başkasının yüklediği dilekçeyi silme",
        "Yükleyen kişi kendi dilekçesini her zaman silebilir.",
        tuple(ADMIN_ONLY),
    ),
]
BY_KEY = {p.key: p for p in PERMISSIONS}


def groups():
    """Ekranda gösterim için (grup adı, [yetkiler]) listesi; sıra kayıt defterindeki sıradır."""
    result: dict[str, list[Permission]] = {}
    for perm in PERMISSIONS:
        result.setdefault(perm.group, []).append(perm)
    return list(result.items())


def allowed_roles(saved: dict | None, key: str) -> set:
    """Yetkiye sahip roller: kayıtlı seçim, yoksa varsayılan. Yönetici her zaman vardır."""
    perm = BY_KEY[key]
    roles = (saved or {}).get(key)
    chosen = set(perm.default if roles is None else roles)
    chosen.add("admin")
    return chosen & set(ALL_ROLES)


def has_perm(user, key: str) -> bool:
    """Kullanıcının rolü bu yetkiye sahip mi (yönetici ve süper kullanıcı her zaman)."""
    if not (user and getattr(user, "is_authenticated", False) and user.is_active):
        return False
    if user.is_superuser or user.role == "admin":
        return True
    from apps.office.models import OfficeSettings

    return user.role in allowed_roles(OfficeSettings.load().role_permissions, key)


def role_has_perm(role: str, key: str) -> bool:
    """Bir rol için aynı denetim (kullanıcı nesnesi olmadan; örn. formdaki sorumlu rolü)."""
    if role == "admin":
        return True
    from apps.office.models import OfficeSettings

    return role in allowed_roles(OfficeSettings.load().role_permissions, key)
