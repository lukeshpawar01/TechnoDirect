from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.db import models
from django.utils import timezone

# Permission catalogue (code, label, group). Kept in code so the API can list it.
PERMISSIONS = [
    ("view_overview", "View executive overview", "Dashboards"),
    ("view_funnel", "View retailer funnel & retailer list", "Dashboards"),
    ("view_distributors", "View distributor performance", "Dashboards"),
    ("view_territory", "View territory performance", "Dashboards"),
    ("view_orders", "View orders & payments", "Dashboards"),
    ("view_products", "View product performance", "Dashboards"),
    ("view_inventory", "View inventory", "Dashboards"),
    ("view_retention", "View retention & growth", "Dashboards"),
    ("view_loyalty", "View loyalty points", "Dashboards"),
    ("view_data_health", "View data health", "Dashboards"),
    ("export_data", "Export data (CSV / Excel)", "Data"),
    ("view_pii", "View retailer phone numbers / PII", "Data"),
    ("manage_targets", "Manage targets", "Admin"),
    ("manage_mappings", "Manage mappings (regions, states, ASMs, pincodes)", "Admin"),
    ("manage_users", "Manage users, roles & audit log", "Admin"),
    ("manage_metrics", "Manage metric dictionary & reconciliation", "Admin"),
    ("trigger_sync", "Trigger data sync", "Admin"),
]
PERMISSION_CODES = [p[0] for p in PERMISSIONS]


class Role(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.CharField(max_length=255, blank=True)
    permissions = models.JSONField(default=list, blank=True, help_text="List of permission codes")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class UserManager(BaseUserManager):
    use_in_migrations = True

    def create_user(self, email, password=None, **extra):
        if not email:
            raise ValueError("Email is required")
        email = self.normalize_email(email).lower()
        user = self.model(email=email, **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra):
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        extra.setdefault("is_master_admin", True)
        extra.setdefault("scope_all", True)
        return self.create_user(email, password, **extra)


class User(AbstractBaseUser, PermissionsMixin):
    email = models.EmailField(unique=True)
    full_name = models.CharField(max_length=150, blank=True)
    phone = models.CharField(max_length=20, blank=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    is_master_admin = models.BooleanField(default=False)
    role = models.ForeignKey(Role, null=True, blank=True, on_delete=models.SET_NULL, related_name="users")
    # Data scope. scope_all=True => everything. Otherwise the union of the listed entities.
    scope_all = models.BooleanField(default=False)
    scope_regions = models.ManyToManyField("warehouse.Region", blank=True, related_name="+")
    scope_states = models.ManyToManyField("warehouse.State", blank=True, related_name="+")
    scope_asms = models.ManyToManyField("warehouse.Asm", blank=True, related_name="+")
    scope_distributors = models.ManyToManyField("warehouse.Distributor", blank=True, related_name="+")
    date_joined = models.DateTimeField(default=timezone.now)

    objects = UserManager()
    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    class Meta:
        ordering = ["email"]

    def __str__(self):
        return self.email

    @property
    def permission_codes(self):
        if self.is_master_admin:
            return list(PERMISSION_CODES)
        if not self.role_id:
            return []
        return [c for c in (self.role.permissions or []) if c in PERMISSION_CODES]

    def has_code(self, code):
        return self.is_master_admin or code in self.permission_codes

    @property
    def has_full_scope(self):
        return self.is_master_admin or self.scope_all


class AuditLog(models.Model):
    at = models.DateTimeField(default=timezone.now, db_index=True)
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="audit_entries")
    user_email = models.CharField(max_length=254, blank=True)
    action = models.CharField(max_length=32, db_index=True)
    object_type = models.CharField(max_length=64, db_index=True)
    object_id = models.CharField(max_length=64, blank=True)
    before = models.JSONField(null=True, blank=True)
    after = models.JSONField(null=True, blank=True)
    reason = models.CharField(max_length=255, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        ordering = ["-at"]
