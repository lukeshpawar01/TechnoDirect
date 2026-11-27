"""Techno AI (the Ollama assistant) was removed from the dashboard (user, 2026-11-27): drop its permission from roles."""
from django.db import migrations


def forwards(apps, schema_editor):
    Role = apps.get_model("accounts", "Role")
    for role in Role.objects.all():
        if "use_assistant" in (role.permissions or []):
            role.permissions = [p for p in role.permissions if p != "use_assistant"]
            role.save(update_fields=["permissions"])


class Migration(migrations.Migration):
    dependencies = [("accounts", "0008_grant_mbr")]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
