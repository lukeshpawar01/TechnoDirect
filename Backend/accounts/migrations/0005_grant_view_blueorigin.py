"""Give the new `view_blueorigin` permission to every role that can already see retention."""
from django.db import migrations


def forwards(apps, schema_editor):
    Role = apps.get_model("accounts", "Role")
    for role in Role.objects.all():
        perms = list(role.permissions or [])
        if "view_retention" in perms and "view_blueorigin" not in perms:
            role.permissions = sorted(perms + ["view_blueorigin"])
            role.save(update_fields=["permissions"])


def backwards(apps, schema_editor):
    Role = apps.get_model("accounts", "Role")
    for role in Role.objects.all():
        if "view_blueorigin" in (role.permissions or []):
            role.permissions = [p for p in role.permissions if p != "view_blueorigin"]
            role.save(update_fields=["permissions"])


class Migration(migrations.Migration):
    dependencies = [("accounts", "0004_grant_use_assistant")]
    operations = [migrations.RunPython(forwards, backwards)]
