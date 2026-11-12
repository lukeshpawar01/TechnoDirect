from django.apps import AppConfig
from django.db.models.signals import post_migrate


def _seed_metrics(sender, **kwargs):
    from .models import ensure_default_metrics

    ensure_default_metrics()


class MastersConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "masters"

    def ready(self):
        post_migrate.connect(_seed_metrics, sender=self)
