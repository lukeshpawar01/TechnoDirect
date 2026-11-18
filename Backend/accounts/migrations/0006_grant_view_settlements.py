"""Give the new `view_settlements` permission to every role that can already see orders & payments."""
from django.db import migrations


def forwards(apps, schema_editor):
    Role = apps.get_model("accounts", "Role")
    for role in Role.objects.all():
        perms = list(role.permissions or [])
        if "view_orders" in perms and "view_settlements" not in perms:
            role.permissions = sorted(perms + ["view_settlements"])
            role.save(update_fields=["permissions"])


def backwards(apps, schema_editor):
    Role = apps.get_model("accounts", "Role")
    for role in Role.objects.all():
        if "view_settlements" in (role.permissions or []):
            role.permissions = [p for p in role.permissions if p != "view_settlements"]
            role.save(update_fields=["permissions"])


class Migration(migrations.Migration):
    dependencies = [("accounts", "0005_grant_view_blueorigin")]
    operations = [migrations.RunPython(forwards, backwards)]
