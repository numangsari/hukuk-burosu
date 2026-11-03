"""Dosya detayındaki Özet sekmesi için hazırlanan özet veriler."""

from apps.tasks.models import OPEN_STATUSES

from .party_roles import PARTY_SIDES, party_lanes

UPCOMING_LIMIT = 6


def _fallback_side(role):
    """Dosya türünde bulunmayan eski bir sıfatın hangi yana ait olduğunu diğer türlerden bulur."""
    for _label, left, _label2, right in PARTY_SIDES.values():
        if role in left:
            return 0
        if role in right:
            return 1
    return 0


def party_groups(case, party_links, include_empty=False):
    """Taraflar, dosya türünün yanlarına (davacı/davalı vb.) göre gruplanır."""
    lanes = party_lanes().get(case.case_type) or party_lanes()["other"]
    groups = [{"label": lane["label"], "items": []} for lane in lanes]

    def lane_index(role):
        found = next((i for i, lane in enumerate(lanes) if role in lane["roles"]), None)
        if found is None:
            found = min(_fallback_side(role), len(lanes) - 1)
        return found

    if case.client_id and case.client_role:
        groups[lane_index(case.client_role)]["items"].append(
            {
                "name": case.client.name,
                "role": case.get_client_role_display(),
                "identity": "",
                "lawyer": "",
                "address": "",
                "is_client": True,
                "from_uyap": bool(getattr(case, "portalcase", None)),
                "url": case.client.get_absolute_url(),
                "link_pk": None,
            }
        )
    for extra in case.co_client_links.select_related("client"):
        # Ek müvekkiller asıl müvekkil gibi, kendi sıfatlarına göre ilgili yanda listelenir.
        groups[lane_index(extra.role)]["items"].append(
            {
                "name": extra.client.name,
                "role": extra.role_label,
                "identity": "",
                "lawyer": "",
                "address": "",
                "is_client": True,
                "from_uyap": bool(getattr(case, "portalcase", None)),
                "url": extra.client.get_absolute_url(),
                "link_pk": None,
            }
        )
    for link in party_links:
        groups[lane_index(link.role)]["items"].append(
            {
                "name": link.party.name,
                "role": link.get_role_display(),
                "identity": link.party.identity_no,
                "lawyer": link.party.lawyer,
                "address": link.party.address,
                "is_client": False,
                "from_uyap": link.from_uyap,
                "url": "",
                "link_pk": None if link.from_uyap else link.pk,
            }
        )
    # Boş kalan "Diğer ilgililer" bölümü gösterilmez; iki karşıt yan boş da olsa görünür.
    return [g for i, g in enumerate(groups) if g["items"] or (include_empty and i < 2)]


def build_summary(case, tasks, flow_members, documents, today):
    """Sayaçlar ve yaklaşan işler. Girdiler ayrıca sorgulanmaması için hazır listelerdir."""
    open_tasks = [t for t in tasks if t.status in OPEN_STATUSES]
    overdue_tasks = [t for t in open_tasks if t.due_date < today]
    upcoming = []
    for task in open_tasks:
        upcoming.append(
            {
                "icon": "bi-check2-square",
                "kind": "Görev",
                "title": task.title,
                "date": task.due_date,
                "tab": "#t-gorevler",
                "sub": str(task.assignee) if task.assignee_id else "",
            }
        )
    upcoming.sort(key=lambda item: item["date"])
    for item in upcoming:
        item["days"] = (item["date"] - today).days
    last_document = max((d.created_at for d in documents), default=None)
    age_end = case.closed_on if (not case.is_open and case.closed_on) else today
    return {
        "open_task_count": len(open_tasks),
        "overdue_task_count": len(overdue_tasks),
        "linked_count": len(flow_members) - 1,
        "document_count": len(documents),
        "last_document_at": last_document,
        "upcoming": upcoming[:UPCOMING_LIMIT],
        "upcoming_more": max(len(upcoming) - UPCOMING_LIMIT, 0),
        "age_days": (age_end - case.opened_on).days if case.opened_on else None,
    }
