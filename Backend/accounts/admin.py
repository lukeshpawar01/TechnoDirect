from django.contrib import admin

from .models import AuditLog, Role, User


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ["email", "full_name", "role", "is_master_admin", "is_active", "last_login"]
    search_fields = ["email", "full_name"]
    filter_horizontal = ["scope_regions", "scope_states", "scope_asms", "scope_distributors"]
    exclude = ["password", "groups", "user_permissions"]


admin.site.register(Role)


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ["at", "user_email", "action", "object_type", "object_id"]
    list_filter = ["action", "object_type"]
