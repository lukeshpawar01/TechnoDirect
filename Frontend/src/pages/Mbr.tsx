import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { NavLink, Navigate, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { post } from '@/lib/api';
import { monthLabel } from '@/lib/format';
import { PageHeader } from '@/components/PageHeader';
import { ErrorState, InlineError, LoadingBlock, cx } from '@/components/ui';
import { IconMonitor, IconRepeat, IconX } from '@/components/Icons';
import { Performance } from '@/components/mbr/Performance';
import { Summary } from '@/components/mbr/Summary';
import { Growth } from '@/components/mbr/Growth';
import { Tech } from '@/components/mbr/Tech';
import { Developments } from '@/components/mbr/Developments';
import { useNotes, useScorecard } from '@/components/mbr/shared';
import type { MbrNotes } from '@/components/mbr/types';

/** The MBR agenda, in the order it is presented. */
const PAGES = [
  { slug: 'summary', n: 1, label: 'Executive summary', sub: 'Conclusions and decisions for leadership' },
  { slug: 'performance', n: 2, label: 'How are we doing', sub: 'Business & product metrics, targets vs actuals' },
  { slug: 'growth', n: 3, label: 'Growth actions', sub: 'Path to the goal, bottlenecks, support required' },
  { slug: 'tech', n: 4, label: 'Tech updates', sub: 'Delivery, blockers, adherence to timelines' },
  { slug: 'developments', n: 5, label: 'Other developments', sub: 'Wins, risks, people, partners, policy' },
] as const;
type Slug = (typeof PAGES)[number]['slug'];

const LAUNCH = '2024-12';
function todayIST() {
  const p = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Kolkata', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date());
  return p; // YYYY-MM-DD
}
function monthsSince(from: string, to: string) {
  const out: string[] = [];
  let [y, m] = from.split('-').map(Number);
  const [ty, tm] = to.split('-').map(Number);
  while (y < ty || (y === ty && m <= tm)) {
    out.push(`${y}-${String(m).padStart(2, '0')}`);
    m += 1;
    if (m > 12) { m = 1; y += 1; }
  }
  return out.reverse();
}

export default function MbrPage() {
  const { page } = useParams<{ page?: string }>();
  const [sp, setSp] = useSearchParams();
  const nav = useNavigate();
  const today = todayIST();
  const months = useMemo(() => monthsSince(LAUNCH, today.slice(0, 7)), [today]);
  const month = sp.get('month') && months.includes(sp.get('month')!) ? sp.get('month')! : months[0];
  const current = PAGES.find((p) => p.slug === page);

  const score = useScorecard(month);
  const notesQ = useNotes(month);

  // ---- present mode: the pages full screen, arrow keys move between them
  const stage = useRef<HTMLDivElement>(null);
  const [presenting, setPresenting] = useState(false);
  useEffect(() => {
    const on = () => setPresenting(document.fullscreenElement === stage.current && !!stage.current);
    document.addEventListener('fullscreenchange', on);
    return () => document.removeEventListener('fullscreenchange', on);
  }, []);
  const go = useCallback(
    (step: number) => {
      const i = PAGES.findIndex((p) => p.slug === page);
      const next = PAGES[Math.min(PAGES.length - 1, Math.max(0, i + step))];
      nav({ pathname: `/mbr/${next.slug}`, search: sp.toString() });
      stage.current?.scrollTo({ top: 0 });
    },
    [nav, page, sp],
  );
  useEffect(() => {
    if (!presenting) return;
    const key = (e: KeyboardEvent) => {
      if (e.key === 'ArrowRight' || e.key === 'PageDown') go(1);
      if (e.key === 'ArrowLeft' || e.key === 'PageUp') go(-1);
    };
    window.addEventListener('keydown', key);
    return () => window.removeEventListener('keydown', key);
  }, [presenting, go]);

  if (!current) return <Navigate to={{ pathname: '/mbr/summary', search: sp.toString() }} replace />;

  // presenting = read-only (drawers would open outside the full-screen stage)
  const notes: MbrNotes | undefined = notesQ.data && presenting ? { ...notesQ.data, can_edit: false } : notesQ.data;
  const setMonth = (m: string) => setSp((x) => { const n = new URLSearchParams(x); n.set('month', m); return n; }, { replace: true });

  return (
    <>
      <PageHeader
        title="Monthly Business Review"
        showBasis={false}
        meta={score.data?.meta}
        subtitle={<>TD's month on one page set, in the same format every month · {monthLabel(month)}</>}
        actions={
          <div className="flex items-center gap-2">
            <label className="sr-only" htmlFor="mbr-month">Month reviewed</label>
            <select id="mbr-month" className="input py-1 text-sm" value={month} onChange={(e) => setMonth(e.target.value)}>
              {months.map((m, i) => <option key={m} value={m}>{monthLabel(m)}{i === 0 ? ' (in progress)' : ''}</option>)}
            </select>
            <button className="btn" onClick={() => void stage.current?.requestFullscreen?.()} title="Full screen; ← → move between the pages; Esc to leave">
              <IconMonitor size={14} /> Present
            </button>
          </div>
        }
      />

      <div ref={stage} className={cx(presenting && 'overflow-y-auto bg-page px-8 py-6')}>
        {presenting && (
          <div className="mb-4 flex items-center justify-between gap-3">
            <div>
              <div className="text-xs text-muted">Monthly Business Review · TechnoDirect</div>
              <div className="text-2xl font-semibold text-ink">{monthLabel(month)}</div>
            </div>
            <div className="flex items-center gap-2 text-xs text-muted">
              <span className="tabular-nums">{current.n} / {PAGES.length}</span>
              <button className="btn btn-sm" onClick={() => go(-1)} disabled={current.n === 1}>← Back</button>
              <button className="btn btn-sm" onClick={() => go(1)} disabled={current.n === PAGES.length}>Next →</button>
              <button className="btn btn-sm" onClick={() => void document.exitFullscreen()} aria-label="Leave present mode"><IconX size={13} /></button>
            </div>
          </div>
        )}

        <nav aria-label="MBR pages" className="mb-4 grid grid-cols-2 gap-2 md:grid-cols-3 xl:grid-cols-5">
          {PAGES.map((p) => (
            <NavLink
              key={p.slug}
              to={{ pathname: `/mbr/${p.slug}`, search: sp.toString() }}
              className={({ isActive }) =>
                cx('group rounded-lg border px-3 py-2.5 transition-colors', isActive ? 'border-brand bg-brand/5 dark:bg-brand/20' : 'border-line bg-surface hover:bg-sunken')
              }
            >
              {({ isActive }) => (
                <div className="flex items-start gap-2.5">
                  <span className={cx('mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs font-semibold tabular-nums', isActive ? 'bg-brand text-brand-ink' : 'bg-sunken text-ink2')}>{p.n}</span>
                  <span className="min-w-0">
                    <span className="block text-sm font-semibold text-ink">{p.label}</span>
                    <span className="block truncate text-2xs text-muted">{p.sub}</span>
                  </span>
                </div>
              )}
            </NavLink>
          ))}
        </nav>

        {notes && !presenting && (current.slug === 'growth' || current.slug === 'tech') && <CarryForward notes={notes} month={month} />}

        <PageBody slug={current.slug} month={month} today={today} score={score} notes={notes} notesQ={notesQ} />
      </div>
    </>
  );
}

function PageBody({ slug, month, today, score, notes, notesQ }: {
  slug: Slug; month: string; today: string;
  score: ReturnType<typeof useScorecard>; notes: MbrNotes | undefined; notesQ: ReturnType<typeof useNotes>;
}) {
  const needsScore = slug === 'summary' || slug === 'performance' || slug === 'growth';
  if (needsScore) {
    if (score.isLoading) return <LoadingBlock height={420} label="Building the scorecard…" />;
    if (score.error && !score.data) return <ErrorState error={score.error} onRetry={() => void score.refetch()} />;
  }
  if (slug !== 'performance' && slug !== 'summary') {
    if (notesQ.isLoading) return <LoadingBlock height={300} />;
    if (notesQ.error || !notes) return <ErrorState error={notesQ.error} onRetry={() => void notesQ.refetch()} />;
  }
  const s = score.data?.data;
  if (slug === 'summary' && s) return <Summary s={s} notes={notes} />;
  if (slug === 'performance' && s) return <Performance s={s} notes={notes} />;
  if (slug === 'growth' && s && notes) return <Growth s={s} notes={notes} />;
  if (slug === 'tech' && notes) return <Tech notes={notes} month={month} today={today} />;
  if (slug === 'developments' && notes) return <Developments notes={notes} month={month} />;
  return null;
}

function CarryForward({ notes, month }: { notes: MbrNotes; month: string }) {
  const qc = useQueryClient();
  const carry = useMutation({
    mutationFn: () => post<{ copied: number }>(`/masters/mbr/carry-forward/?month=${month}`, {}),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['mbr'] }),
  });
  if (!notes.can_edit || notes.previous_open === 0) return null;
  return (
    <div className="mb-4 flex flex-wrap items-center justify-between gap-2 rounded-lg border border-line bg-sunken/60 px-4 py-2.5 text-sm">
      <span className="text-ink2">
        {monthLabel(notes.previous_month)} has <b className="font-semibold text-ink">{notes.previous_open} open</b> growth / tech line{notes.previous_open === 1 ? '' : 's'} not yet in {monthLabel(month)}.
      </span>
      <button className="btn btn-sm" disabled={carry.isPending} onClick={() => carry.mutate()}>
        <IconRepeat size={13} /> Carry them forward
      </button>
      {carry.error ? <InlineError error={carry.error} /> : null}
    </div>
  );
}
