"""Give the new `view_loyalty` permission to every role that can already see retention."""
from django.db import migrations


def forwards(apps, schema_editor):
    Role = apps.get_model("accounts", "Role")
    for role in Role.objects.all():
        perms = list(role.permissions or [])
        if "view_retention" in perms and "view_loyalty" not in perms:
            role.permissions = sorted(perms + ["view_loyalty"])
            role.save(update_fields=["permissions"])


def backwards(apps, schema_editor):
    Role = apps.get_model("accounts", "Role")
    for role in Role.objects.all():
        if "view_loyalty" in (role.permissions or []):
            role.permissions = [p for p in role.permissions if p != "view_loyalty"]
            role.save(update_fields=["permissions"])


class Migration(migrations.Migration):
    dependencies = [("accounts", "0001_initial")]
    operations = [migrations.RunPython(forwards, backwards)]
