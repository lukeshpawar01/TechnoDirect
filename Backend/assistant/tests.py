"""Techno AI: permission / scope enforcement and response shape, with the Ollama call mocked."""
import json
from unittest import mock

from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from accounts.models import Role, User
from analytics.tests import make_world
from assistant import llm
from assistant.tools import run_tool


def fake_llm(plan_tools):
    """First call = planner (returns plan_tools), second = answer (echoes refs it was given)."""
    calls = []

    def _chat(messages, json_mode=False, temperature=0.2):
        calls.append(messages)
        if len(calls) % 2 == 1:
            return json.dumps({"tools": plan_tools, "needs_unauthorised": [], "off_topic": False})
        system = messages[0]["content"]
        return json.dumps({
            "headline": "Sales are on track.",
            "what_to_do": [{"text": "Push Heera", "refs": ["R1", "R9"]}],
            "data_points": [{"text": "Data seen", "refs": ["R1"]}, "plain string point"],
            "explanation": "", "not_authorised": ["Inventory"] if "Inventory" in system else [],
            "follow_ups": ["Next?"],
        })
    return _chat, calls


@override_settings(OLLAMA_BASE_URL="http://ollama.test", OLLAMA_MODEL="test-model", ASSISTANT_ENABLED=True)
class AssistantTests(TestCase):
    def setUp(self):
        cache.clear()
        self.w = make_world()
        role = Role.objects.create(name="Overview only", permissions=["view_overview", "use_assistant"])
        self.user = User.objects.create_user(email="asm@test.local", password="Strong-pass-1", role=role)
        self.user.scope_states.set([self.w["ka"]])
        self.c = APIClient()
        self.c.force_authenticate(self.user)

    def test_status_lists_only_permitted_modules(self):
        r = self.c.get("/api/assistant/status/").json()
        self.assertTrue(r["configured"])
        self.assertIn("Executive Overview", r["modules"])
        self.assertNotIn("Inventory", r["modules"])

    def test_unpermitted_tools_are_never_called(self):
        chat, calls = fake_llm([{"name": "overview", "params": {"preset": "mtd"}},
                                {"name": "inventory", "params": {}}])
        with mock.patch.object(llm, "chat", side_effect=chat):
            r = self.c.post("/api/assistant/chat/", {"question": "How are sales and stock?"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        body = r.json()
        self.assertEqual([s["tool"] for s in body["sources"]], ["overview"])  # inventory dropped
        answer_prompt = calls[1][0]["content"]
        self.assertIn("NOT authorised to see: Funnel", answer_prompt.replace("Retailer Funnel", "Funnel"))
        self.assertNotIn('"label": "Inventory"', answer_prompt)
        # refs that do not exist (R9) are removed; plain-string items are accepted
        self.assertEqual(body["answer"]["what_to_do"][0]["refs"], ["R1"])
        self.assertEqual(body["answer"]["data_points"][1]["text"], "plain string point")

    def test_tool_runs_with_users_scope(self):
        data, meta, err = run_tool("overview", {"preset": "last_12m"}, self.user)
        self.assertIsNone(err)
        admin = User.objects.create_superuser(email="admin@test.local", password="x-Strong-pass1")
        all_data, _, _ = run_tool("overview", {"preset": "last_12m"}, admin)
        self.assertLessEqual(data["kpis"]["sales"]["value"] or 0, all_data["kpis"]["sales"]["value"] or 0)
        self.assertEqual(run_tool("inventory", {}, self.user)[2], "not_authorised")

    def test_requires_use_assistant_permission(self):
        self.user.role.permissions = ["view_overview"]
        self.user.role.save()
        self.assertEqual(self.c.get("/api/assistant/status/").status_code, 403)
        self.assertEqual(self.c.post("/api/assistant/chat/", {"question": "hi"}, format="json").status_code, 403)

    def test_llm_failure_is_a_clean_503(self):
        with mock.patch.object(llm, "chat", side_effect=llm.LlmError("down")):
            r = self.c.post("/api/assistant/chat/", {"question": "sales?"}, format="json")
        self.assertEqual((r.status_code, r.json()["detail"]), (503, "down"))

    @override_settings(OLLAMA_MODEL="")
    def test_not_configured(self):
        self.assertFalse(self.c.get("/api/assistant/status/").json()["configured"])

    def test_parse_json_tolerates_fences(self):
        self.assertEqual(llm.parse_json('```json\n{"a": 1}\n```'), {"a": 1})
        self.assertEqual(llm.parse_json('Sure! {"a": 2} hope that helps'), {"a": 2})
        self.assertEqual(llm.parse_json("nope"), {})
