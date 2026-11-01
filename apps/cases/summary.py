"""Dosya detayındaki Özet sekmesi için hazırlanan özet veriler."""

import datetime as dt

from apps.tasks.models import OPEN_STATUSES

from .models import HearingStatus
from .party_roles import party_lanes

UPCOMING_LIMIT = 6


def party_groups(case, party_links):
    """Taraflar, dosya türünün yanlarına (davacı/davalı vb.) göre gruplanır."""
    lanes = party_lanes().get(case.case_type) or party_lanes()["other"]
    groups = [{"label": lane["label"], "items": []} for lane in lanes]

    def lane_index(role):
        return next((i for i, lane in enumerate(lanes) if role in lane["roles"]), 0)

    if case.client_role:
        groups[lane_index(case.client_role)]["items"].append(
            {
                "name": case.client.name,
                "role": case.get_client_role_display(),
                "identity": "",
                "is_client": True,
                "url": case.client.get_absolute_url(),
            }
        )
    for link in party_links:
        groups[lane_index(link.role)]["items"].append(
            {
                "name": link.party.name,
                "role": link.get_role_display(),
                "identity": link.party.identity_no,
                "is_client": False,
                "url": "",
            }
        )
    return [group for group in groups if group["items"]]


def build_summary(case, tasks, hearings, steps, documents, now, today):
    """Sayaçlar ve yaklaşan işler. Girdiler ayrıca sorgulanmaması için hazır listelerdir."""
    open_tasks = [t for t in tasks if t.status in OPEN_STATUSES]
    overdue_tasks = [t for t in open_tasks if t.due_date < today]
    planned = [h for h in hearings if h.status == HearingStatus.PLANNED and h.starts_at >= now]
    planned.sort(key=lambda h: h.starts_at)
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
    for hearing in planned:
        upcoming.append(
            {
                "icon": "bi-bank2",
                "kind": hearing.get_kind_display(),
                "title": hearing.authority or hearing.get_kind_display(),
                "date": hearing.starts_at.date(),
                "time": hearing.starts_at,
                "tab": "#t-durusmalar",
                "sub": hearing.room,
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
        "next_hearing": planned[0] if planned else None,
        "step_count": len(steps),
        "last_step": max(steps, key=lambda s: (s.decision_date or dt.date.min, s.pk))
        if steps
        else None,
        "document_count": len(documents),
        "last_document_at": last_document,
        "upcoming": upcoming[:UPCOMING_LIMIT],
        "upcoming_more": max(len(upcoming) - UPCOMING_LIMIT, 0),
        "age_days": (age_end - case.opened_on).days if case.opened_on else None,
    }
