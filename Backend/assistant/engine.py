"""Techno AI: question -> (1) plan which permitted data tools to call -> (2) call them as the user ->
(3) answer strictly from that data, in a fixed JSON shape the UI renders."""
import datetime as dt
import json
import time

from django.conf import settings

from analytics.filters import today_ist
from warehouse.models import Asm, Distributor, Region, State

from . import llm
from .tools import PRESETS_HELP, TOOLS, allowed_tools, clean_params, denied_tools, run_tool

MAX_TOOLS = 4
HISTORY_TURNS = 6


def _scope_text(user):
    if user.has_full_scope:
        return "all regions, states, ASMs and distributors"
    parts = []
    for label, qs in (("regions", user.scope_regions.all()), ("states", user.scope_states.all()),
                      ("ASMs", user.scope_asms.all()), ("distributors", user.scope_distributors.all())):
        names = [o.name for o in qs]
        if names:
            parts.append(f"{label}: {', '.join(names[:20])}")
    return "; ".join(parts) or "no data scope assigned"


def _names(model, limit=60):
    return ", ".join(model.objects.order_by("name").values_list("name", flat=True)[:limit])


def _history(history):
    out = []
    for h in (history or [])[-HISTORY_TURNS:]:
        role = "assistant" if h.get("role") == "assistant" else "user"
        text = str(h.get("content") or "")[:1500]
        if text:
            out.append({"role": role, "content": text})
    return out


def plan(question, history, user, page_params, page):
    tools = allowed_tools(user)
    denied = denied_tools(user)
    today = today_ist()
    sys = f"""You plan data lookups for "Techno AI", the assistant of the TechnoDirect B2B sales dashboard
(Technosport sportswear sold to retailers through distributors, India; currency INR; financial year Apr-Mar).
Today is {today.isoformat()} ({today.strftime('%A')}). The user is on the page "{page or 'unknown'}".

Pick the smallest set of tools (max {MAX_TOOLS}) whose data answers the question. Tools the user may use:
{json.dumps({k: v['about'] for k, v in tools.items()}, indent=1)}

Modules this user is NOT authorised to see (never pick them): {', '.join(t['label'] for t in denied.values()) or 'none'}.

Parameters every data tool accepts (all optional):
- preset: {PRESETS_HELP}
- region / state / asm / distributor: names (comma separated). Known regions: {_names(Region)}.
  Known ASMs: {_names(Asm)}. Known distributors: {_names(Distributor)}.
- category: men, women, kids, unisex (product Category I)
Tool-specific: mom_trend.months (6|12|24); territory.group_by (region|state|asm); products/inventory cat_l2, cat_l3;
orders payment_mode (UPI,CC,DC,NB), platform (android,web).
If the question gives no period or place, reuse the user's current page filters: {json.dumps(page_params or {})}.
For "explain / what does X mean" questions include metric_definitions.

Reply ONLY with JSON: {{"tools": [{{"name": "<tool>", "params": {{...}}}}], "needs_unauthorised": ["<module label>"],
"off_topic": false}}. Set off_topic true (and tools []) only if the question is unrelated to this business / dashboard."""
    msgs = [{"role": "system", "content": sys}, *_history(history), {"role": "user", "content": question}]
    out = llm.parse_json(llm.chat(msgs, json_mode=True, temperature=0))
    calls = []
    for c in (out.get("tools") or [])[:MAX_TOOLS]:
        name = (c or {}).get("name")
        if name in tools and name not in [x[0] for x in calls]:
            calls.append((name, clean_params(name, {**(page_params or {}), **((c or {}).get("params") or {})})))
    wants_denied = [str(x) for x in (out.get("needs_unauthorised") or [])][:5]
    return calls, wants_denied, bool(out.get("off_topic"))


ANSWER_SCHEMA = """{
 "headline": "one sentence answering the question with the key number(s)",
 "what_to_do": [{"text": "a concrete next action with owner / place and the number behind it", "refs": ["R1"]}],
 "data_points": [{"text": "a supporting fact with its number", "refs": ["R2"]}],
 "explanation": "plain-language explanation of any metric involved (how it is calculated), or empty",
 "not_authorised": ["module label the question needed but the user cannot see"],
 "follow_ups": ["short follow-up question", "another", "another"]
}"""


def answer(question, history, user, results, wants_denied, off_topic):
    role = user.role.name if user.role else ("Master admin" if user.is_master_admin else "User")
    denied = [t["label"] for t in denied_tools(user).values()]
    sources = "\n\n".join(
        f"[{r['ref']}] {r['label']} — period: {r['period'] or 'n/a'} — filters: {json.dumps(r['params'])}\n"
        + (json.dumps(r["data"], ensure_ascii=False, default=str) if r["data"] is not None else f"UNAVAILABLE ({r['error']})")
        for r in results) or "(no data was retrieved)"
    sys = f"""You are "Techno AI", the analyst assistant inside the TechnoDirect business dashboard.
The user is {user.full_name or user.email}, role "{role}", data scope: {_scope_text(user)}.
Modules this user is NOT authorised to see: {', '.join(denied) or 'none'}.

RULES
1. Use ONLY the numbers in the DATA below. Never invent, estimate or recall numbers. If the data does not contain
   the answer, say so plainly in the headline.
2. Every item in what_to_do and data_points must cite the source refs (R1, R2...) it is based on.
3. If the question needs a module the user is not authorised to see, do not answer that part: list it in
   not_authorised and say the user's role does not have access.{(' The planner flagged: ' + ', '.join(wants_denied)) if wants_denied else ''}
4. Money in Indian style: ₹ with L (lakh) / Cr (crore), e.g. ₹74.6 L, ₹1.82 Cr. Percentages with one decimal.
5. "Sales" = gross order value of paid, non-cancelled orders. Explain metrics simply when asked.
6. Be concise and recommendation-first: up to 4 what_to_do items, up to 5 data_points. Empty lists are fine.
7. {'The question is not about this business or dashboard: politely say you only answer questions about the TechnoDirect dashboard, with empty lists.' if off_topic else 'Stay on the TechnoDirect business data.'}

DATA
{sources}

Reply ONLY with JSON in exactly this shape:
{ANSWER_SCHEMA}"""
    msgs = [{"role": "system", "content": sys}, *_history(history), {"role": "user", "content": question}]
    out = llm.parse_json(llm.chat(msgs, json_mode=True, temperature=0.2))
    refs = {r["ref"] for r in results}

    def items(key, limit):
        rows = []
        for it in (out.get(key) or [])[:limit]:
            if isinstance(it, str):
                it = {"text": it, "refs": []}
            if isinstance(it, dict) and str(it.get("text") or "").strip():
                rows.append({"text": str(it["text"]).strip(),
                             "refs": [x for x in (it.get("refs") or []) if x in refs]})
        return rows

    return {
        "headline": str(out.get("headline") or "I couldn't produce an answer from the available data.").strip(),
        "what_to_do": items("what_to_do", 4),
        "data_points": items("data_points", 5),
        "explanation": str(out.get("explanation") or "").strip(),
        "not_authorised": [str(x) for x in (out.get("not_authorised") or []) if x][:5],
        "follow_ups": [str(x).strip() for x in (out.get("follow_ups") or []) if str(x).strip()][:3],
    }


def ask(question, history, user, page_params=None, page=None):
    t0 = time.monotonic()
    calls, wants_denied, off_topic = plan(question, history, user, page_params, page)
    results = []
    for i, (name, params) in enumerate(calls, start=1):
        data, meta, err = run_tool(name, params, user)
        period = (meta or {}).get("period") or {}
        results.append({"ref": f"R{i}", "tool": name, "label": TOOLS[name]["label"], "params": params,
                        "period": period.get("label") and f"{period.get('label')} ({period.get('from')} – {period.get('to')})",
                        "data": data, "error": err})
    ans = answer(question, history, user, results, wants_denied, off_topic)
    return {
        "answer": ans,
        "sources": [{"ref": r["ref"], "tool": r["tool"], "label": r["label"], "period": r["period"],
                     "params": r["params"], "ok": r["error"] is None} for r in results],
        "model": settings.OLLAMA_MODEL,
        "took_ms": int((time.monotonic() - t0) * 1000),
        "asked_at": dt.datetime.now().isoformat(timespec="seconds"),
    }
