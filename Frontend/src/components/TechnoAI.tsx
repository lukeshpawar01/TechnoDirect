import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
} from "react";
import { useQuery } from "@tanstack/react-query";
import { useLocation } from "react-router-dom";
import { useAuth } from "@/auth/AuthContext";
import type { AiItem, AiReply, AiStatus } from "@/api/types";
import { errorMessage, get, post } from "@/lib/api";
import { useFilters } from "@/lib/filters";
import { navItemFor } from "@/nav";
import { LOGO_ORANGE, LogoMark } from "./Logo";
import { IconArrowUp, IconX } from "./Icons";
import { cx } from "./ui";

/*
 * Techno AI — dashboard analyst chatbot (Ollama behind /api/assistant/*).
 * Answers come only from dashboard endpoints the signed-in user is allowed to see (enforced server-side).
 * Colours: brand navy + logo orange (+ crimson accent) — the dashboard's own palette.
 */

type Turn =
  | { id: string; role: "user"; text: string; at: string }
  | { id: string; role: "assistant"; reply: AiReply; at: string }
  | { id: string; role: "error"; text: string; at: string };

const NAVY = "#1E2A5E";
const GRADIENT = `linear-gradient(135deg, ${NAVY} 0%, #2f3f86 55%, #B03A48 140%)`;
const uid = () => Math.random().toString(36).slice(2, 10);

function storageKey(email: string) {
  return `td.ai.${email}`;
}
function loadTurns(email: string): Turn[] {
  try {
    const raw = localStorage.getItem(storageKey(email));
    return raw ? (JSON.parse(raw) as Turn[]).slice(-40) : [];
  } catch {
    return [];
  }
}
function saveTurns(email: string, turns: Turn[]) {
  try {
    localStorage.setItem(storageKey(email), JSON.stringify(turns.slice(-40)));
  } catch {
    /* storage full or blocked: chat still works for this session */
  }
}

/** Text of a past turn sent back as conversation history. */
function historyText(t: Turn): string {
  if (t.role === "assistant") {
    const a = t.reply.answer;
    return [a.headline, ...a.data_points.map((d) => `- ${d.text}`)].join("\n");
  }
  return t.text;
}

function Mark({ size = 34 }: { size?: number }) {
  return (
    <span
      className="inline-flex shrink-0 items-center justify-center rounded-xl shadow-sm"
      style={{ width: size, height: size, background: GRADIENT }}
    >
      <LogoMark className="text-white" title="Techno AI" />
    </span>
  );
}

function Refs({
  refs,
  sources,
}: {
  refs: string[];
  sources: AiReply["sources"];
}) {
  if (!refs.length) return null;
  return (
    <span className="ml-1.5 inline-flex flex-wrap gap-1 align-middle">
      {refs.map((r) => {
        const s = sources.find((x) => x.ref === r);
        return (
          <span
            key={r}
            title={s ? `${s.label}${s.period ? ` · ${s.period}` : ""}` : r}
            className="rounded px-1.5 py-px text-[10px] font-semibold tracking-wide"
            style={{ background: "rgba(243,125,32,0.18)", color: LOGO_ORANGE }}
          >
            {r}
          </span>
        );
      })}
    </span>
  );
}

function AnswerCard({
  reply,
  onFollowUp,
}: {
  reply: AiReply;
  onFollowUp: (q: string) => void;
}) {
  const a = reply.answer;
  const list = (items: AiItem[], numbered: boolean, dark: boolean) => (
    <ol className="space-y-2.5">
      {items.map((it, i) => (
        <li key={i} className="flex gap-2.5 text-[13px] leading-relaxed">
          {numbered ? (
            <span
              className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[11px] font-bold"
              style={{ background: "rgba(243,125,32,0.2)", color: LOGO_ORANGE }}
            >
              {i + 1}
            </span>
          ) : (
            <span
              className={cx(
                "mt-2 h-1.5 w-1.5 shrink-0 rounded-full",
                dark ? "bg-white/50" : "bg-brand/60",
              )}
            />
          )}
          <span className={dark ? "text-white/90" : "text-ink"}>
            {it.text}
            <Refs refs={it.refs} sources={reply.sources} />
          </span>
        </li>
      ))}
    </ol>
  );
  return (
    <div className="space-y-3">
      <div
        className="overflow-hidden rounded-2xl p-4 text-white shadow-md"
        style={{ background: GRADIENT }}
      >
        <div
          className="mb-2 flex items-center gap-2 text-[11px] font-bold uppercase tracking-[0.14em]"
          style={{ color: LOGO_ORANGE }}
        >
          <LogoMark className="h-4 w-4" title="" /> Techno AI
        </div>
        <p className="text-[15px] font-semibold leading-snug">{a.headline}</p>
        {a.what_to_do.length > 0 && (
          <>
            <div className="my-3 border-t border-white/15" />
            <div className="mb-2 text-[11px] font-bold uppercase tracking-[0.14em] text-white/60">
              What to do
            </div>
            {list(a.what_to_do, true, true)}
          </>
        )}
      </div>
      {a.not_authorised.length > 0 && (
        <div className="rounded-lg border border-warn/30 bg-warn-bg px-3 py-2 text-xs text-ink2">
          Your role doesn't have access to <b>{a.not_authorised.join(", ")}</b>,
          so that part isn't answered. Ask your admin if you need it.
        </div>
      )}
      {a.data_points.length > 0 && (
        <div className="rounded-xl border border-line bg-surface p-3.5">
          <div className="mb-2 text-[11px] font-bold uppercase tracking-[0.14em] text-muted">
            What the data shows
          </div>
          {list(a.data_points, false, false)}
        </div>
      )}
      {a.explanation && (
        <div className="rounded-xl border border-brand/20 bg-brand/5 p-3.5 text-[13px] leading-relaxed text-ink">
          <div className="mb-1 text-[11px] font-bold uppercase tracking-[0.14em] text-brand dark:text-ink2">
            How this metric works
          </div>
          {a.explanation}
        </div>
      )}
      {reply.sources.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5 text-[11px] text-muted">
          <span>Sources:</span>
          {reply.sources.map((s) => (
            <span
              key={s.ref}
              className={cx(
                "rounded-full border px-2 py-0.5",
                s.ok
                  ? "border-line bg-sunken text-ink2"
                  : "border-bad/30 text-bad",
              )}
              title={s.period ?? undefined}
            >
              <b className="font-semibold">{s.ref}</b> {s.label}
              {s.period ? ` · ${s.period.split(" (")[0]}` : ""}
              {!s.ok && " · unavailable"}
            </span>
          ))}
          <span className="ml-auto">{(reply.took_ms / 1000).toFixed(1)}s</span>
        </div>
      )}
      {a.follow_ups.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {a.follow_ups.map((q) => (
            <button
              key={q}
              onClick={() => onFollowUp(q)}
              className="rounded-full border border-brand/25 bg-surface px-3 py-1 text-xs text-brand transition-colors hover:bg-brand hover:text-white dark:text-ink2"
            >
              {q}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

const THINKING = [
  "Reading your dashboards…",
  "Checking the numbers you can access…",
  "Writing the answer…",
];

function Thinking() {
  const [i, setI] = useState(0);
  useEffect(() => {
    const t = window.setInterval(
      () => setI((x) => Math.min(x + 1, THINKING.length - 1)),
      2500,
    );
    return () => window.clearInterval(t);
  }, []);
  return (
    <div className="flex items-center gap-3 rounded-2xl border border-line bg-surface px-4 py-3 text-sm text-ink2">
      <span className="flex gap-1" aria-hidden="true">
        {[0, 1, 2].map((d) => (
          <span
            key={d}
            className="h-2 w-2 animate-bounce rounded-full"
            style={{
              background: d === 1 ? LOGO_ORANGE : NAVY,
              animationDelay: `${d * 140}ms`,
            }}
          />
        ))}
      </span>
      <span aria-live="polite">{THINKING[i]}</span>
    </div>
  );
}

export function TechnoAI() {
  const { user, can } = useAuth();
  const loc = useLocation();
  const { apiParams } = useFilters();
  const [open, setOpen] = useState(false);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [turns, setTurns] = useState<Turn[]>(() =>
    user ? loadTurns(user.email) : [],
  );
  const scroller = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const allowed = can("use_assistant");

  const status = useQuery({
    queryKey: ["assistant", "status"],
    queryFn: () => get<AiStatus>("/assistant/status/"),
    enabled: allowed && open,
    staleTime: 5 * 60_000,
  });
  const st = status.data;
  const ready = !!st?.enabled && !!st?.configured;
  const page = navItemFor(loc.pathname)?.label ?? "Dashboard";

  useEffect(() => {
    if (user) saveTurns(user.email, turns);
  }, [turns, user]);
  // a new answer scrolls to its headline (read top-down); anything else follows the bottom of the chat
  const lastRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const last = turns[turns.length - 1];
    if (!busy && last?.role === "assistant" && lastRef.current)
      lastRef.current.scrollIntoView({ block: "start", behavior: "smooth" });
    else
      scroller.current?.scrollTo({
        top: scroller.current.scrollHeight,
        behavior: "smooth",
      });
  }, [turns, busy, open]);
  useEffect(() => {
    if (open) window.setTimeout(() => inputRef.current?.focus(), 150);
    const onKey = (e: globalThis.KeyboardEvent) =>
      e.key === "Escape" && setOpen(false);
    if (open) window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  const suggestions = useMemo(() => st?.suggestions ?? [], [st]);
  if (!user || !allowed) return null;

  async function ask(q: string) {
    const question = q.trim();
    if (!question || busy || !ready) return;
    const history = turns
      .filter((t) => t.role !== "error")
      .slice(-6)
      .map((t) => ({ role: t.role, content: historyText(t) }));
    setTurns((ts) => [
      ...ts,
      { id: uid(), role: "user", text: question, at: new Date().toISOString() },
    ]);
    setInput("");
    setBusy(true);
    try {
      const reply = await post<AiReply>(
        "/assistant/chat/",
        { question, history, context: { page, params: apiParams } },
        { timeout: 200_000 },
      );
      setTurns((ts) => [
        ...ts,
        { id: uid(), role: "assistant", reply, at: new Date().toISOString() },
      ]);
    } catch (e) {
      setTurns((ts) => [
        ...ts,
        {
          id: uid(),
          role: "error",
          text: errorMessage(e),
          at: new Date().toISOString(),
        },
      ]);
    } finally {
      setBusy(false);
    }
  }

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void ask(input);
    }
  };

  return (
    <>
      {/* launcher */}
      {!open && (
        <button
          onClick={() => setOpen(true)}
          className="fixed bottom-5 right-5 z-40 flex items-center gap-2.5 rounded-full py-2.5 pl-3 pr-5 text-sm font-semibold text-white shadow-lg ring-1 ring-white/10 transition-transform hover:-translate-y-0.5 hover:shadow-xl focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-brand/40"
          style={{ background: GRADIENT }}
          aria-label="Open Techno AI assistant"
        >
          <span
            className="flex h-7 w-7 items-center justify-center rounded-full"
            style={{ background: "rgba(243,125,32,0.22)" }}
          >
            <LogoMark className="h-4 w-4" title="" />
          </span>
          Techno AI
        </button>
      )}

      {/* panel */}
      {open && (
        <div
          className="fixed inset-0 z-40 bg-black/20 md:bg-transparent"
          onClick={() => setOpen(false)}
          aria-hidden="true"
        />
      )}
      <aside
        className={cx(
          // floating card: margin on every side, rounded corners, soft layered shadow
          "fixed inset-3 z-50 flex flex-col overflow-hidden rounded-2xl border border-line bg-page shadow-[0_24px_60px_-12px_rgba(15,20,36,0.35),0_8px_20px_-8px_rgba(15,20,36,0.2)] transition-all duration-300 ease-out md:inset-auto md:bottom-4 md:right-4 md:top-4 md:w-[460px] dark:shadow-[0_24px_60px_-12px_rgba(0,0,0,0.7),0_8px_20px_-8px_rgba(0,0,0,0.5)]",
          open ? "translate-x-0 opacity-100" : "pointer-events-none translate-x-[calc(100%+2rem)] opacity-0",
        )}
        role="dialog"
        aria-modal="true"
        aria-label="Techno AI assistant"
        aria-hidden={!open}
      >
        <header className="border-b border-line bg-surface px-4 pb-3 pt-4">
          <div className="flex items-start gap-3">
            <Mark size={40} />
            <div className="min-w-0 flex-1">
              <h2 className="text-lg font-bold tracking-tight text-ink">
                Techno AI
              </h2>
              <p className="text-xs leading-snug text-muted">
                Answers from this dashboard's data you're allowed to see —
                recommendation first, every number referenced.
              </p>
            </div>
            <button
              className="btn btn-sm"
              onClick={() => setTurns([])}
              disabled={busy || turns.length === 0}
              title="Start a new conversation"
            >
              New chat
            </button>
            <button
              className="rounded p-1.5 text-ink2 hover:bg-sunken"
              onClick={() => setOpen(false)}
              aria-label="Close Techno AI"
            >
              <IconX size={16} />
            </button>
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-2 text-[11px]">
            <span className="inline-flex items-center gap-1.5 rounded-full border border-line bg-sunken px-2.5 py-1 text-ink2">
              <span
                className={cx(
                  "h-2 w-2 rounded-full",
                  ready ? "bg-good" : status.isLoading ? "bg-muted" : "bg-bad",
                )}
              />
              <b className="font-semibold text-ink">
                {st?.model ??
                  (status.isLoading ? "Connecting…" : "Not configured")}
              </b>
              {st && <span className="text-muted">· {st.provider}</span>}
            </span>
            <span className="text-muted">Page: {page}</span>
          </div>
        </header>

        <div
          ref={scroller}
          className="flex-1 space-y-4 overflow-y-auto px-4 py-4"
        >
          {status.isError && (
            <div className="rounded-lg border border-bad/30 bg-bad-bg px-3 py-2 text-xs text-bad">
              {errorMessage(status.error)}
            </div>
          )}
          {st && !ready && (
            <div className="rounded-xl border border-warn/30 bg-warn-bg p-4 text-sm text-ink2">
              <b className="text-ink">Techno AI isn't set up yet.</b>
              <p className="mt-1 text-xs">
                {st.enabled
                  ? "Add OLLAMA_BASE_URL, OLLAMA_API_KEY and OLLAMA_MODEL to the backend .env and restart it."
                  : "It is switched off (ASSISTANT_ENABLED=False)."}
              </p>
            </div>
          )}

          {turns.length === 0 && ready && (
            <div className="space-y-4">
              <div
                className="rounded-2xl p-5 text-white shadow-md"
                style={{ background: GRADIENT }}
              >
                <div
                  className="text-[11px] font-bold uppercase tracking-[0.14em]"
                  style={{ color: LOGO_ORANGE }}
                >
                  Hi {user.full_name?.split(" ")[0] || "there"}
                </div>
                <p className="mt-1 text-[15px] font-semibold leading-snug">
                  Ask about sales, targets, retailers, orders, products or stock
                  — or what any metric means.
                </p>
                {st && st.modules.length > 0 && (
                  <p className="mt-2 text-xs text-white/70">
                    You can ask about: {st.modules.join(" · ")}
                  </p>
                )}
              </div>
              <div className="grid gap-2">
                {suggestions.map((q) => (
                  <button
                    key={q}
                    onClick={() => void ask(q)}
                    className="rounded-xl border border-line bg-surface px-3.5 py-2.5 text-left text-sm text-ink transition-colors hover:border-brand/40 hover:bg-sunken"
                  >
                    {q}
                  </button>
                ))}
              </div>
            </div>
          )}

          {turns.map((t, i) => (
            <div
              key={t.id}
              ref={i === turns.length - 1 ? lastRef : undefined}
              className="scroll-mt-2"
            >
              {t.role === "user" ? (
                <div key={t.id} className="flex justify-end">
                  <div className="max-w-[85%] rounded-2xl rounded-br-md bg-brand px-3.5 py-2 text-sm text-white shadow-sm">
                    {t.text}
                  </div>
                </div>
              ) : t.role === "assistant" ? (
                <AnswerCard
                  key={t.id}
                  reply={t.reply}
                  onFollowUp={(q) => void ask(q)}
                />
              ) : (
                <div
                  key={t.id}
                  className="rounded-lg border border-bad/30 bg-bad-bg px-3 py-2 text-sm text-bad"
                >
                  {t.text}
                </div>
              )}
            </div>
          ))}
          {busy && <Thinking />}
        </div>

        <footer className="border-t border-line bg-surface p-3">
          <div className="flex items-end gap-2">
            <textarea
              ref={inputRef}
              rows={2}
              value={input}
              maxLength={1000}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={onKeyDown}
              disabled={!ready}
              placeholder={
                ready
                  ? "Ask anything about sales, targets, retailers or stock…"
                  : "Techno AI is not configured"
              }
              className="input min-h-[52px] flex-1 resize-none text-sm"
              aria-label="Your question"
            />
            <button
              onClick={() => void ask(input)}
              disabled={busy || !ready || !input.trim()}
              className="flex h-[52px] w-[52px] shrink-0 items-center justify-center rounded-xl text-white shadow-sm transition-opacity disabled:opacity-40"
              style={{ background: GRADIENT }}
              aria-label="Send"
            >
              <IconArrowUp size={18} />
            </button>
          </div>
          <p className="mt-1.5 text-[11px] text-muted">
            Enter to ask · Shift+Enter for a new line · chat is saved in this
            browser only
          </p>
        </footer>
      </aside>
    </>
  );
}
