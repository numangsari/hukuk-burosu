"""HTML niteliği içindeki Alpine ifadelerinde JavaScript dizesi güvenliği."""

import re
from html.parser import HTMLParser
from pathlib import Path
from types import SimpleNamespace

import pytest
from django.conf import settings
from django.template import Context, Template
from django.utils.html import escapejs


class AlpineAttributes(HTMLParser):
    def __init__(self):
        super().__init__()
        self.values = []

    def handle_starttag(self, tag, attrs):
        self.values.extend(value for key, value in attrs if key == "x-data")


@pytest.mark.parametrize(
    "template,field",
    [
        ("accounts/login.html", "username"),
        ("clients/form.html", "kind"),
        ("cases/form.html", "case_type"),
        ("accounting/form.html", "kind"),
        ("accounts/settings.html", "role"),
    ],
)
def test_bound_values_remain_javascript_strings(template, field):
    payload = "'+(window.auditXss=1)+'"
    form = SimpleNamespace(**{field: SimpleNamespace(value=payload)})
    source = (Path(settings.BASE_DIR) / "templates" / template).read_text(encoding="utf-8")
    expressions = re.findall(r'x-data="[^"]*"', source)
    html = Template("".join(f"<div {attr}></div>" for attr in expressions)).render(
        Context({"form": form})
    )
    parser = AlpineAttributes()
    parser.feed(html)
    assert any(str(escapejs(payload)) in value for value in parser.values)
    assert all(payload not in value for value in parser.values)
