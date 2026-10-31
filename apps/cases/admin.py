from django.contrib import admin

from . import models

for m in (models.Case, models.CaseParty, models.Document):
    admin.site.register(m)
