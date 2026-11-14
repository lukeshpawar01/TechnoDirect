"""Techno AI endpoints.

GET  /api/assistant/status/  -> {enabled, configured, model, provider, modules, suggestions}
POST /api/assistant/chat/    {question, history:[{role, content}], context:{page, params}}
                             -> {answer:{headline, what_to_do, data_points, explanation, not_authorised, follow_ups},
                                 sources:[{ref, tool, label, period, params, ok}], model, took_ms}
"""
from django.conf import settings
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.audit import log_action
from accounts.permissions import HasPerm

from . import llm
from .engine import ask
from .tools import allowed_tools

SUGGESTIONS = {
    "overview": ["How are we tracking against this month's target?", "Explain the run rate and projection",
                 "Which states drive most of our sales?"],
    "mom_trend": ["Is sales value growing faster than quantity month on month?"],
    "distributors": ["Which distributors are furthest behind target?", "Which distributors have stale stock sync?"],
    "territory": ["Compare ASMs by target achievement this month"],
    "orders": ["How many orders are pending dispatch beyond SLA?", "What is our payment mode mix?"],
    "products": ["Which categories and articles sell the most?", "Which new launches are performing?"],
    "inventory": ["Where are we out of stock on fast-moving articles?"],
    "retention": ["How many retailers did we lose last month?", "What is our repeat retailer rate?"],
    "funnel": ["How many KYC-approved retailers have never ordered?"],
    "loyalty": ["How many loyalty points were redeemed?"],
    "metric_definitions": ["What does AOV mean and how is it calculated?"],
}


def _provider():
    base = (settings.OLLAMA_BASE_URL or "").lower()
    return "Ollama Cloud" if "ollama.com" in base else "Ollama (self-hosted)"


class AssistantStatusView(APIView):
    def get_permissions(self):
        return [IsAuthenticated(), HasPerm("use_assistant")()]

    def get(self, request):
        tools = allowed_tools(request.user)
        sugg = [q for k in tools for q in SUGGESTIONS.get(k, [])]
        return Response({
            "enabled": settings.ASSISTANT_ENABLED,
            "configured": llm.is_configured(),
            "model": settings.OLLAMA_MODEL or None,
            "provider": _provider(),
            "modules": [t["label"] for k, t in tools.items() if k != "metric_definitions"],
            "suggestions": sugg[:8],
        })


class AssistantChatView(APIView):
    throttle_scope = "assistant"

    def get_permissions(self):
        return [IsAuthenticated(), HasPerm("use_assistant")()]

    def post(self, request):
        if not settings.ASSISTANT_ENABLED:
            return Response({"detail": "Techno AI is switched off (ASSISTANT_ENABLED)."}, status=503)
        q = str(request.data.get("question") or "").strip()
        if not q:
            return Response({"detail": "Ask a question."}, status=400)
        if len(q) > 1000:
            return Response({"detail": "Please keep the question under 1,000 characters."}, status=400)
        history = request.data.get("history") or []
        ctx = request.data.get("context") or {}
        page_params = {k: v for k, v in (ctx.get("params") or {}).items() if isinstance(v, (str, int))}
        try:
            result = ask(q, history if isinstance(history, list) else [], request.user, page_params, ctx.get("page"))
        except llm.LlmError as e:
            return Response({"detail": str(e)}, status=503)
        log_action(request, "assistant_query", None, object_type="assistant", object_id=settings.OLLAMA_MODEL or "",
                   after={"question": q[:500], "page": ctx.get("page"), "sources": [s["tool"] for s in result["sources"]],
                          "took_ms": result["took_ms"]})
        return Response(result)
