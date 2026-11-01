"""Bağlı dosyaların liste ve rapor ekranlarındaki gösterimi."""

from django.db.models import Count

from .models import Case


def linked_counts(flow_ids=None) -> dict:
    """flow_id -> gruptaki dosya sayısı."""
    qs = Case.objects.filter(flow_id__isnull=False)
    if flow_ids is not None:
        qs = qs.filter(flow_id__in=set(flow_ids))
    return {row["flow_id"]: row["n"] for row in qs.values("flow_id").annotate(n=Count("pk"))}


def cluster(cases):
    """Bağlı dosyaları art arda dizer (grup ilk üyesinin yerine gelir, üyeler akış sırasında).

    Her dosyaya `linked_others` (bağlı diğer dosya sayısı), `chain_prev` ve `chain_next`
    (komşu satırla bağ işareti çizilsin mi) özniteliklerini ekler. Yalnızca verilen liste
    içindeki dosyalar kümelenir."""
    cases = list(cases)
    counts = linked_counts({c.flow_id for c in cases if c.flow_id})
    groups = {}
    for case in cases:
        if case.flow_id:
            groups.setdefault(case.flow_id, []).append(case)
    ordered, placed = [], set()
    for case in cases:
        if not case.flow_id:
            ordered.append(case)
        elif case.flow_id not in placed:
            placed.add(case.flow_id)
            ordered.extend(
                sorted(
                    groups[case.flow_id],
                    key=lambda c: (c.flow_position, c.opened_on is None, c.opened_on, c.pk),
                )
            )
    for index, case in enumerate(ordered):
        case.linked_others = max(counts.get(case.flow_id, 1) - 1, 0) if case.flow_id else 0
        before = ordered[index - 1] if index else None
        after = ordered[index + 1] if index + 1 < len(ordered) else None
        case.chain_prev = bool(case.flow_id and before and before.flow_id == case.flow_id)
        case.chain_next = bool(case.flow_id and after and after.flow_id == case.flow_id)
    return ordered
