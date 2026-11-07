"""Django alanlarının yardım/hata ARIA başvuruları gerçek öğelere bağlanır."""

from html.parser import HTMLParser

from django import forms
from django.template.loader import render_to_string


class References(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids, self.refs = set(), set()

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if attrs.get("id"):
            self.ids.add(attrs["id"])
        self.refs.update(attrs.get("aria-describedby", "").split())


def test_field_help_and_error_references_exist():
    class Example(forms.Form):
        name = forms.CharField(help_text="Adınızı girin")

    for form in (Example(), Example(data={})):
        parser = References()
        parser.feed(render_to_string("partials/field.html", {"field": form["name"]}))
        assert parser.refs
        assert parser.refs <= parser.ids
