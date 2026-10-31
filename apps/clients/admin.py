from django.contrib import admin

from . import models

for m in (models.Client, models.PowerOfAttorney, models.Party):
    admin.site.register(m)
