from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from accounts.models import User


class Command(BaseCommand):
    help = "Create or update the master admin from MASTER_ADMIN_EMAIL / MASTER_ADMIN_PASSWORD (env)."

    def add_arguments(self, parser):
        parser.add_argument("--email", help="Override MASTER_ADMIN_EMAIL")
        parser.add_argument("--password", help="Override MASTER_ADMIN_PASSWORD")
        parser.add_argument("--reset-password", action="store_true",
                            help="Reset the password if the user already exists")

    def handle(self, *args, **opts):
        email = (opts.get("email") or settings.MASTER_ADMIN_EMAIL or "").strip().lower()
        password = opts.get("password") or settings.MASTER_ADMIN_PASSWORD
        if not email or not password:
            raise CommandError(
                "MASTER_ADMIN_EMAIL and MASTER_ADMIN_PASSWORD must be set in .env (not REPLACE_ME), "
                "or pass --email/--password."
            )
        user = User.objects.filter(email=email).first()
        if user is None:
            user = User.objects.create_superuser(email=email, password=password, full_name="Master Admin")
            self.stdout.write(self.style.SUCCESS(f"Created master admin {email}"))
        else:
            user.is_master_admin = True
            user.is_staff = True
            user.is_superuser = True
            user.scope_all = True
            user.is_active = True
            if opts.get("reset_password"):
                user.set_password(password)
            user.save()
            self.stdout.write(self.style.SUCCESS(f"Master admin {email} already existed – flags ensured"))
