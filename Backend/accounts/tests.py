from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient

from analytics.tests import make_world

from .models import AuditLog, Role, User


class ScopeEnforcementTests(TestCase):
    def setUp(self):
        cache.clear()
        self.w = make_world()
        role = Role.objects.create(name="RM", permissions=["view_overview", "view_funnel", "view_distributors"])
        self.user = User.objects.create_user(email="rm@test.local", password="Strong-pass-1", role=role)
        self.user.scope_states.set([self.w["ka"]])
        self.c = APIClient()
        tok = self.c.post("/api/auth/token/", {"email": "rm@test.local", "password": "Strong-pass-1"},
                          format="json").json()["access"]
        self.c.credentials(HTTP_AUTHORIZATION=f"Bearer {tok}")

    def test_me_reports_scope_and_permissions(self):
        me = self.c.get("/api/auth/me/").json()
        self.assertEqual(me["scope"]["all"], False)
        self.assertEqual(me["scope"]["states"], [self.w["ka"].id])
        self.assertIn("view_overview", me["permissions"])
        self.assertEqual(me["role"]["name"], "RM")

    def test_filters_are_scope_limited(self):
        f = self.c.get("/api/meta/filters/").json()
        self.assertEqual([d["name"] for d in f["distributors"]], ["Heera Exports"])

    def test_analytics_only_show_scoped_rows(self):
        rows = self.c.get("/api/distributors/?preset=last_12m").json()["data"]["rows"]
        self.assertEqual({r["name"] for r in rows}, {"Heera Exports"})
        kpi = self.c.get("/api/overview/?preset=last_12m").json()["data"]["kpis"]["sales"]["value"]
        self.assertEqual(kpi, 80000.0)  # Odisha order (20k) excluded

    def test_filter_cannot_escape_scope(self):
        rows = self.c.get(f"/api/distributors/?preset=last_12m&state={self.w['od'].id}").json()["data"]["rows"]
        self.assertEqual(rows, [])

    def test_out_of_scope_detail_is_404_and_missing_perm_is_403(self):
        self.assertEqual(self.c.get(f"/api/retailers/{self.w['ret2'].id}/").status_code, 404)
        self.assertEqual(self.c.get(f"/api/retailers/{self.w['ret1'].id}/").status_code, 200)
        self.assertEqual(self.c.get("/api/orders/summary/").status_code, 403)
        self.assertEqual(self.c.get("/api/admin/users/").status_code, 403)

    def test_phone_masked_without_view_pii(self):
        row = self.c.get("/api/retailers/?preset=last_12m").json()["results"][0]
        self.assertIn("X", row["phone"])

    def test_export_requires_permission(self):
        self.assertEqual(self.c.get("/api/retailers/?export=csv").status_code, 403)


class AdminFlowTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(email="admin@test.local", password="x-Strong-pass1")
        self.c = APIClient()
        tok = self.c.post("/api/auth/token/", {"email": "admin@test.local", "password": "x-Strong-pass1"},
                          format="json").json()["access"]
        self.c.credentials(HTTP_AUTHORIZATION=f"Bearer {tok}")

    def test_create_role_and_user_is_audited(self):
        r = self.c.post("/api/admin/roles/", {"name": "Viewer", "permissions": ["view_overview"]}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        u = self.c.post("/api/admin/users/", {"email": "v@test.local", "full_name": "V", "password": "Strong-pass-9",
                                              "role_id": r.json()["id"], "scope": {"all": True}}, format="json")
        self.assertEqual(u.status_code, 201, u.content)
        self.assertEqual(u.json()["scope"]["all"], True)
        self.assertGreaterEqual(AuditLog.objects.count(), 2)
        bad = self.c.post("/api/admin/roles/", {"name": "Bad", "permissions": ["nope"]}, format="json")
        self.assertEqual(bad.status_code, 400)

    def test_master_admin_cannot_be_deleted(self):
        self.assertEqual(self.c.delete(f"/api/admin/users/{self.admin.id}/").status_code, 403)
