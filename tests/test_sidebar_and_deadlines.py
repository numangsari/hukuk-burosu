import datetime as dt

import pytest
from django.template.loader import render_to_string
from django.utils import timezone

from apps.office.models import OfficeSettings
from apps.tasks.models import Task

pytestmark = pytest.mark.django_db


def test_saved_office_logo_is_a_decorative_sidebar_background(lawyer_client):
    office = OfficeSettings.load()
    office.logo = "office/ornek-logo.png"
    office.save()
    html = lawyer_client.get("/").content.decode()
    head = html.split('<div class="sidebar-head">', 1)[1].split("<nav", 1)[0]
    assert 'class="sidebar-watermark"' in head
    assert 'src="/media/office/ornek-logo.png"' in head
    assert 'alt="" aria-hidden="true"' in head
    assert office.name in head


@pytest.mark.parametrize(
    "days, css, icon",
    [
        (0, "due-today", "bi-exclamation-circle-fill"),
        (2, "due-soon", "bi-calendar-event"),
        (3, "due-soon", "bi-calendar-event"),
        (-1, "due-overdue", "bi-exclamation-circle-fill"),
    ],
)
def test_task_deadline_badges_keep_day_and_clear_urgency(days, css, icon):
    task = Task(title="Örnek görev", due_date=timezone.localdate() + dt.timedelta(days=days))
    html = render_to_string("tasks/_chips.html", {"t": task, "part": "due"})
    assert css in html and icon in html and task.due_label in html
