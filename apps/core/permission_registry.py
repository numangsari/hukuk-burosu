"""Rol bazlı yetki matrisi: hangi rolün hangi işi yapabileceği.

Ayarlar > "Yetkiler ve çalışma düzeni" ekranındaki tek liste bu kayıt defterinden çizilir.
Seçimler `OfficeSettings.role_permissions` içinde saklanır ({yetki: [roller ve ilişkiler]});
kaydı olmayan yetki için buradaki varsayılan roller geçerlidir. Yönetici her yetkide her zaman
yetkilidir ve ekranda kilitlidir.

Dosya/müvekkil/muhasebe yetkilerinde (`scoped`) rolün yanında ilişki de seçilebilir: "responsible"
(sorumlu) ve "assistant" (yardımcı sorumlu) işaretliyse, rolü yetkisiz olsa bile kişi yalnızca
sorumlu olduğu dosya veya müvekkilde bu yetkiyi kullanır (`has_perm(user, anahtar, nesne)`).
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
# Nesne bazlı ilişkiler: kaydedilen anahtar, ekran etiketi.
RELATIONS = [("responsible", "Sorumlu"), ("assistant", "Yardımcı sorumlu")]
RELATION_KEYS = [key for key, _ in RELATIONS]


@dataclass(frozen=True)
class Permission:
    key: str
    group: str
    label: str
    help: str
    default: tuple
    scoped: bool = False  # Sorumlu / yardımcı sorumlu seçeneği olan (dosya bazlı) yetki


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
        scoped=True,
    ),
    Permission(
        "cases.remove_party",
        "Dosya ve müvekkil",
        "Dosyadan taraf çıkarma",
        "",
        tuple(ADMIN_ONLY),
        scoped=True,
    ),
    Permission(
        "cases.delete", "Dosya ve müvekkil", "Dosya silme", "", tuple(ADMIN_ONLY), scoped=True
    ),
    Permission(
        "clients.delete", "Dosya ve müvekkil", "Müvekkil silme", "", tuple(ADMIN_ONLY), scoped=True
    ),
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
        "notices.undo_no_task",
        "Tebligat",
        "Tebligatta görev yok işlemini geri alma",
        "Geri alınınca tebligat yeniden işlenmemiş olur; dosyaya kopyalanan belgeler silinmez.",
        ("admin", "senior"),
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
        scoped=True,
    ),
    Permission(
        "accounting.balances",
        "Muhasebe",
        "Bakiye, cari hesap ve finansal raporları görme",
        "Müvekkil bakiyesi, borçlu süzgeci, cari hesap ekstresi ve mali raporlar.",
        ("admin", "accountant"),
        scoped=True,
    ),
    Permission(
        "accounting.exclude_portal",
        "Muhasebe",
        "UYAP kaynaklı muhasebe kaydını hesap dışı bırakma",
        "Hatalı aktarılan UYAP kaydı silinmeden bakiyeden çıkarılır; yetkili geri alabilir.",
        ("admin", "senior"),
        scoped=True,
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


def allowed_relations(saved: dict | None, key: str) -> set:
    """Yetkiyi nesne bazlı kullanabilen ilişkiler (sorumlu, yardımcı sorumlu); varsayılan yok."""
    if not BY_KEY[key].scoped:
        return set()
    return set((saved or {}).get(key) or []) & set(RELATION_KEYS)


def relations_to(user, obj) -> set:
    """Kullanıcının dosya, müvekkil veya hareketle ilişkisi ({"responsible", "assistant"}).

    Dosyada dosyanın ve müvekkilinin sorumlusu/yardımcısı sayılır; müvekkilde müvekkilin.
    """
    if obj is None:
        return set()
    from apps.accounting.models import LedgerEntry

    if isinstance(obj, LedgerEntry):
        # Muhasebe hareketi: dosyası varsa dosya, yoksa müvekkil.
        obj = obj.case if obj.case_id else obj.client
    holders = [obj]
    client = getattr(obj, "client", None)
    if client is not None and client is not obj:
        holders.append(client)
    found = set()
    for holder in holders:
        if getattr(holder, "responsible_lawyer_id", None) == user.pk:
            found.add("responsible")
        if getattr(holder, "responsible_intern_id", None) == user.pk:
            found.add("assistant")
    return found


def has_perm(user, key: str, obj=None) -> bool:
    """Kullanıcının rolü bu yetkiye sahip mi (yönetici ve süper kullanıcı her zaman).

    `obj` (dosya, müvekkil veya muhasebe hareketi) verilirse ve yetki `scoped` ise, rolü yetkisiz
    olsa bile o nesnede işaretli ilişkiye (sorumlu / yardımcı sorumlu) sahip kişi yetkilidir.
    """
    if not (user and getattr(user, "is_authenticated", False) and user.is_active):
        return False
    if user.is_superuser or user.role == "admin":
        return True
    from apps.office.models import OfficeSettings

    saved = OfficeSettings.load().role_permissions
    if user.role in allowed_roles(saved, key):
        return True
    if obj is not None:
        return bool(allowed_relations(saved, key) & relations_to(user, obj))
    return False


def role_has_perm(role: str, key: str) -> bool:
    """Bir rol için aynı denetim (kullanıcı nesnesi olmadan; örn. formdaki sorumlu rolü)."""
    if role == "admin":
        return True
    from apps.office.models import OfficeSettings

    return role in allowed_roles(OfficeSettings.load().role_permissions, key)
