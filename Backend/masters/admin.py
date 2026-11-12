from django.contrib import admin

from .models import MetricDefinition, ReconciliationRef

admin.site.register(MetricDefinition)
admin.site.register(ReconciliationRef)
