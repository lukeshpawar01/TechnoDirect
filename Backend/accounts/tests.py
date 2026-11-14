import re
from django.core.cache import cache
from accounts.testing import jwt_login
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
        tok = jwt_login(self.c, "rm@test.local", "Strong-pass-1")["access"]
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
        tok = jwt_login(self.c, "admin@test.local", "x-Strong-pass1")["access"]
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


class LoginOtpTests(TestCase):
    def setUp(self):
        from django.core import mail

        self.mail = mail
        self.user = User.objects.create_user(email="otp@test.local", password="Strong-pass-1", full_name="Otp User")
        self.c = APIClient()

    def _start(self):
        r = self.c.post("/api/auth/token/", {"email": "OTP@test.local ", "password": "Strong-pass-1"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        body = r.json()
        self.assertTrue(body["otp_required"])
        self.assertNotIn("access", body)
        self.assertEqual(body["email"], "ot*@test.local")
        code = re.search(r"\b(\d{6})\b", self.mail.outbox[-1].body).group(1)
        return body["challenge_id"], code

    def test_password_then_code_issues_tokens_once(self):
        cid, code = self._start()
        self.assertEqual(self.mail.outbox[-1].to, ["otp@test.local"])
        r = self.c.post("/api/auth/otp/verify/", {"challenge_id": cid, "code": code}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertIn("access", r.json())
        again = self.c.post("/api/auth/otp/verify/", {"challenge_id": cid, "code": code}, format="json")
        self.assertEqual((again.status_code, again.json()["code"]), (400, "restart"))

    def test_wrong_password_sends_no_email(self):
        r = self.c.post("/api/auth/token/", {"email": "otp@test.local", "password": "nope"}, format="json")
        self.assertEqual(r.status_code, 401)
        self.assertEqual(len(self.mail.outbox), 0)

    def test_wrong_codes_lock_the_challenge(self):
        cid, code = self._start()
        wrong = "000000" if code != "000000" else "111111"
        for left in (4, 3, 2, 1):
            r = self.c.post("/api/auth/otp/verify/", {"challenge_id": cid, "code": wrong}, format="json")
            self.assertEqual(r.json()["attempts_left"], left)
        r = self.c.post("/api/auth/otp/verify/", {"challenge_id": cid, "code": wrong}, format="json")
        self.assertEqual(r.json()["code"], "restart")
        r = self.c.post("/api/auth/otp/verify/", {"challenge_id": cid, "code": code}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_expired_code(self):
        from accounts.models import LoginOtp
        from django.utils import timezone

        cid, code = self._start()
        LoginOtp.objects.filter(challenge_id=cid).update(expires_at=timezone.now())
        r = self.c.post("/api/auth/otp/verify/", {"challenge_id": cid, "code": code}, format="json")
        self.assertEqual(r.json()["code"], "expired")

    def test_resend_cooldown_and_new_code(self):
        import datetime as dt

        from accounts.models import LoginOtp
        from django.utils import timezone

        cid, old = self._start()
        r = self.c.post("/api/auth/otp/resend/", {"challenge_id": cid}, format="json")
        self.assertEqual(r.status_code, 429)
        LoginOtp.objects.filter(challenge_id=cid).update(last_sent_at=timezone.now() - dt.timedelta(minutes=1))
        r = self.c.post("/api/auth/otp/resend/", {"challenge_id": cid}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        new = re.search(r"\b(\d{6})\b", self.mail.outbox[-1].body).group(1)
        if new != old:
            bad = self.c.post("/api/auth/otp/verify/", {"challenge_id": cid, "code": old}, format="json")
            self.assertEqual(bad.status_code, 400)
        ok = self.c.post("/api/auth/otp/verify/", {"challenge_id": cid, "code": new}, format="json")
        self.assertEqual(ok.status_code, 200)

    def test_code_is_not_stored_in_plain_text(self):
        from accounts.models import LoginOtp

        cid, code = self._start()
        self.assertNotIn(code, LoginOtp.objects.get(challenge_id=cid).code_hash)

    def test_otp_can_be_switched_off(self):
        from django.test import override_settings

        with override_settings(LOGIN_OTP_ENABLED=False):
            r = self.c.post("/api/auth/token/", {"email": "otp@test.local", "password": "Strong-pass-1"}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertIn("access", r.json())
        self.assertNotIn("otp_required", r.json())
        self.assertEqual(len(self.mail.outbox), 0)
