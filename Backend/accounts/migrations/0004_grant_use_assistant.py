"""Give `use_assistant` (Techno AI chatbot) to every role that can already view at least one dashboard."""
from django.db import migrations


def forwards(apps, schema_editor):
    Role = apps.get_model("accounts", "Role")
    for role in Role.objects.all():
        perms = list(role.permissions or [])
        if any(p.startswith("view_") and p != "view_pii" for p in perms) and "use_assistant" not in perms:
            role.permissions = sorted(perms + ["use_assistant"])
            role.save(update_fields=["permissions"])


def backwards(apps, schema_editor):
    Role = apps.get_model("accounts", "Role")
    for role in Role.objects.all():
        if "use_assistant" in (role.permissions or []):
            role.permissions = [p for p in role.permissions if p != "use_assistant"]
            role.save(update_fields=["permissions"])


class Migration(migrations.Migration):
    dependencies = [("accounts", "0003_login_otp")]
    operations = [migrations.RunPython(forwards, backwards)]
