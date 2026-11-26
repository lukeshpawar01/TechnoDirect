import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { navItemFor } from '@/nav';

/**
 * "← Back" in the top bar: returns to the dashboard PAGE you came from (not the homepage, and not merely the last
 * filter / tab change on the same page), with its filters, tab and scroll position as you left them.
 *
 * It keeps its own trail of pages for this browser tab (sessionStorage), each with its position in the browser
 * history (react-router's history.state.idx) and its scroll offset, so Back steps the real history back to that
 * exact entry. Hidden when there is no earlier dashboard page in this tab.
 */
type Entry = { path: string; search: string; idx: number; scroll: number };
const KEY = 'td.trail';
const MAX = 50;

const read = (): Entry[] => {
  try {
    return JSON.parse(sessionStorage.getItem(KEY) || '[]') as Entry[];
  } catch {
    return [];
  }
};
const write = (t: Entry[]) => {
  try {
    sessionStorage.setItem(KEY, JSON.stringify(t.slice(-MAX)));
  } catch {
    /* private mode: the trail just lives in memory for this page */
  }
};
const histIdx = () => (window.history.state as { idx?: number } | null)?.idx ?? 0;
/** the dashboard scrolls inside <main>, not the window */
const scroller = () => document.querySelector('main');

function titleFor(path: string) {
  if (path.startsWith('/mbr')) return 'MBR';
  const item = navItemFor(path);
  if (item) return item.label;
  if (path.startsWith('/distributors/')) return 'Distributor';
  return 'previous page';
}

export function BackButton() {
  const loc = useLocation();
  const nav = useNavigate();
  const [trail, setTrail] = useState<Entry[]>(read);
  const restoring = useRef<number | null>(null);

  // remember the scroll of the page being left (main scrolls; update the top entry as the user scrolls)
  useEffect(() => {
    const el = scroller();
    if (!el) return;
    let h: number | undefined;
    const onScroll = () => {
      window.clearTimeout(h);
      h = window.setTimeout(() => {
        const t = read();
        if (t.length && t[t.length - 1].path === loc.pathname) {
          t[t.length - 1].scroll = el.scrollTop;
          write(t);
        }
      }, 150);
    };
    el.addEventListener('scroll', onScroll, { passive: true });
    return () => { el.removeEventListener('scroll', onScroll); window.clearTimeout(h); };
  }, [loc.pathname]);

  // keep the trail in step with every location change
  useLayoutEffect(() => {
    const idx = histIdx();
    let t = read().filter((e) => e.idx <= idx); // entries "ahead" of us were left behind by going back
    const top = t[t.length - 1];
    if (top && top.path === loc.pathname) {
      t[t.length - 1] = { ...top, search: loc.search, idx }; // same page: a filter / tab change, not a new page
    } else if (top && top.idx === idx) {
      t[t.length - 1] = { path: loc.pathname, search: loc.search, idx, scroll: 0 }; // a redirect (replace), e.g. / -> /overview
    } else if (top && t.length >= 2 && t[t.length - 2].path === loc.pathname && t[t.length - 2].idx === idx) {
      t = t.slice(0, -1); // the browser's own back button took us to the previous page
    } else {
      t.push({ path: loc.pathname, search: loc.search, idx, scroll: 0 });
    }
    write(t);
    setTrail(t);
    // came back to a page: put its scroll back once its data has drawn
    const target = restoring.current;
    if (target !== null) {
      restoring.current = null;
      let tries = 0;
      const put = () => {
        const el = scroller();
        if (!el) return;
        el.scrollTop = target;
        if (Math.abs(el.scrollTop - target) > 2 && ++tries < 20) window.setTimeout(put, 150);
      };
      window.setTimeout(put, 50);
    }
  }, [loc.pathname, loc.search, loc.key]);

  const prev = trail.length >= 2 ? trail[trail.length - 2] : null;
  if (!prev) return null;

  const go = () => {
    restoring.current = prev.scroll || 0;
    const steps = prev.idx - histIdx();
    if (steps < 0) nav(steps); // the real history entry: filters, tab and state exactly as left
    else nav(prev.path + prev.search);
  };
  const label = titleFor(prev.path);
  return (
    <button
      onClick={go}
      className="flex shrink-0 items-center gap-1 rounded-md border border-line bg-surface px-2 py-1 text-xs font-medium text-ink2 hover:bg-sunken hover:text-ink"
      title={`Back to ${label} (Alt+←)`}
      aria-label={`Back to ${label}`}
    >
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
        <path d="M15 18l-6-6 6-6" />
      </svg>
      <span className="hidden max-w-[9rem] truncate sm:inline">{label}</span>
    </button>
  );
}
