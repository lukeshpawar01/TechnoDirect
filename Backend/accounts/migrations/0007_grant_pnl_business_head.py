"""P&L module: give `view_pnl` and `manage_pnl` to the Business Head role (the master admin holds every permission)."""
from django.db import migrations

CODES = ["view_pnl", "manage_pnl"]


def forwards(apps, schema_editor):
    Role = apps.get_model("accounts", "Role")
    for role in Role.objects.filter(name="Business Head"):
        role.permissions = sorted(set(role.permissions or []) | set(CODES))
        role.save(update_fields=["permissions"])


def backwards(apps, schema_editor):
    Role = apps.get_model("accounts", "Role")
    for role in Role.objects.all():
        if set(CODES) & set(role.permissions or []):
            role.permissions = [p for p in role.permissions if p not in CODES]
            role.save(update_fields=["permissions"])


class Migration(migrations.Migration):
    dependencies = [("accounts", "0006_grant_view_settlements")]
    operations = [migrations.RunPython(forwards, backwards)]
