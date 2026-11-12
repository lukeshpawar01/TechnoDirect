import { cx } from './ui';

/** Brand colours taken from the TechnoDirect logo artwork. */
export const LOGO_INDIGO = '#20174A';
export const LOGO_ORANGE = '#F37D20';

const INK = 'text-[#20174A] dark:text-[#E9E7F7]';

/* ------------------------------------------------------------------ mark */
/** Swoosh figure traced from the brand artwork (viewBox units = 5× source pixels). */
const MARK_BODY = 'M10 12 L488 148 L370 240 L432 330 L238 520 L310 350 L212 262 L258 200 L22 120 L195 128 Z';
/** The "head" is a slanted parallelogram, not an oval. */
const MARK_HEAD = 'M372 68 L440 15 L568 52 L502 104 Z';

/** TechnoDirect swoosh mark. Uses currentColor so it can flip to a light tone in dark mode. */
export function LogoMark({ className, title = 'TechnoDirect' }: { className?: string; title?: string }) {
  return (
    <svg viewBox="0 0 580 530" className={className} role="img" aria-label={title} fill="currentColor">
      <path d={MARK_BODY} />
      {/* thin same-colour stroke softens the parallelogram corners like the artwork */}
      <path d={MARK_HEAD} stroke="currentColor" strokeWidth={8} strokeLinejoin="round" />
    </svg>
  );
}

/* -------------------------------------------------------------- wordmark */
// Wide, low, rounded-square letterforms drawn as uniform strokes (centre-line geometry).
const S = 6.5; // stroke width
const HS = S / 2;
const H = 31; // cap height
const TOP = HS;
const BOT = H - HS;
const MID = H / 2;
const R = 7; // corner radius
const W = 40; // glyph width
const GAP = 10; // letter gap

type Glyph = { w: number; d: (x: number) => string };

const glyphs: Record<string, Glyph> = {
  T: { w: W, d: (x) => `M${x} ${TOP}H${x + W}M${x + W / 2} ${TOP}V${H}` },
  E: {
    w: W,
    d: (x) => {
      const L = x + HS;
      return `M${x + W} ${TOP}H${L + R}Q${L} ${TOP} ${L} ${TOP + R}V${BOT - R}Q${L} ${BOT} ${L + R} ${BOT}H${x + W}M${L} ${MID}H${x + W * 0.78}`;
    },
  },
  C: {
    w: W,
    d: (x) => {
      const L = x + HS;
      return `M${x + W} ${TOP}H${L + R}Q${L} ${TOP} ${L} ${TOP + R}V${BOT - R}Q${L} ${BOT} ${L + R} ${BOT}H${x + W}`;
    },
  },
  H: {
    w: W,
    d: (x) => {
      const L = x + HS;
      const Rt = x + W - HS;
      return `M${L} 0V${H}M${Rt} 0V${H}M${L} ${MID}H${Rt}`;
    },
  },
  // The artwork uses a lower-case style "n" arch in place of N.
  N: {
    w: W,
    d: (x) => {
      const L = x + HS;
      const Rt = x + W - HS;
      return `M${L} ${H}V${TOP + R}Q${L} ${TOP} ${L + R} ${TOP}H${Rt - R}Q${Rt} ${TOP} ${Rt} ${TOP + R}V${H}`;
    },
  },
  O: {
    w: W,
    d: (x) => {
      const L = x + HS;
      const Rt = x + W - HS;
      return `M${L + R} ${TOP}H${Rt - R}Q${Rt} ${TOP} ${Rt} ${TOP + R}V${BOT - R}Q${Rt} ${BOT} ${Rt - R} ${BOT}H${L + R}Q${L} ${BOT} ${L} ${BOT - R}V${TOP + R}Q${L} ${TOP} ${L + R} ${TOP}Z`;
    },
  },
  D: {
    w: W,
    d: (x) => {
      const L = x + HS;
      const Rt = x + W - HS;
      return `M${L} 0V${H}M${x} ${TOP}H${Rt - R}Q${Rt} ${TOP} ${Rt} ${TOP + R}V${BOT - R}Q${Rt} ${BOT} ${Rt - R} ${BOT}H${x}`;
    },
  },
  I: { w: S, d: (x) => `M${x + HS} 0V${H}` },
  R: {
    w: W,
    d: (x) => {
      const L = x + HS;
      const Rt = x + W - HS;
      return `M${L} 0V${H}M${x} ${TOP}H${Rt - R}Q${Rt} ${TOP} ${Rt} ${TOP + R}V${MID - R}Q${Rt} ${MID} ${Rt - R} ${MID}H${x}M${x + W * 0.55} ${MID}L${Rt} ${BOT}V${H}`;
    },
  },
};

function layout(word: string, start: number) {
  let x = start;
  const parts: string[] = [];
  for (const ch of word) {
    const g = glyphs[ch];
    parts.push(g.d(x));
    x += g.w + GAP;
  }
  return { d: parts.join(''), end: x };
}

const techno = layout('TECHNO', 0);
const direct = layout('DIRECT', techno.end);
const WORD_W = direct.end - GAP;

/** Wordmark: TECHNO (indigo) + DIRECT (orange). */
export function LogoWordmark({ className }: { className?: string }) {
  return (
    <svg viewBox={`0 0 ${WORD_W} ${H}`} className={className} role="img" aria-label="TechnoDirect" fill="none" strokeWidth={S}>
      <path d={techno.d} stroke="currentColor" className={INK} />
      <path d={direct.d} stroke={LOGO_ORANGE} />
    </svg>
  );
}

/* ------------------------------------------------------------ composite */
/** Full TechnoDirect logo: mark centred above the wordmark, proportions as in the artwork. */
export function Logo({ compact, className, size = 'md' }: { compact?: boolean; className?: string; size?: 'md' | 'lg' }) {
  if (compact) {
    return <LogoMark className={cx('h-8 w-8', INK, className)} />;
  }
  const lg = size === 'lg';
  return (
    <div className={cx('flex flex-col items-center', lg ? 'gap-4' : 'gap-2', className)}>
      <LogoMark className={cx(INK, lg ? 'h-[72px] w-auto' : 'h-10 w-auto')} />
      <LogoWordmark className={cx('h-auto', INK, lg ? 'w-[300px]' : 'w-[180px]')} />
    </div>
  );
}
