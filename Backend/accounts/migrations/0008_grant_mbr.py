"""Monthly Business Review: Business Head views and edits it; Regional Managers and Data Admins can view it."""
from django.db import migrations

GRANTS = {"Business Head": ["view_mbr", "manage_mbr"], "Regional Manager": ["view_mbr"], "Data Admin": ["view_mbr"]}
CODES = {"view_mbr", "manage_mbr"}


def forwards(apps, schema_editor):
    Role = apps.get_model("accounts", "Role")
    for name, codes in GRANTS.items():
        for role in Role.objects.filter(name=name):
            role.permissions = sorted(set(role.permissions or []) | set(codes))
            role.save(update_fields=["permissions"])


def backwards(apps, schema_editor):
    Role = apps.get_model("accounts", "Role")
    for role in Role.objects.all():
        if CODES & set(role.permissions or []):
            role.permissions = [p for p in role.permissions if p not in CODES]
            role.save(update_fields=["permissions"])


class Migration(migrations.Migration):
    dependencies = [("accounts", "0007_grant_pnl_business_head")]
    operations = [migrations.RunPython(forwards, backwards)]
