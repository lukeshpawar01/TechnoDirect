import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';

export type ThemePref = 'light' | 'dark' | 'system';
export type ResolvedTheme = 'light' | 'dark';

interface ThemeCtx {
  pref: ThemePref;
  theme: ResolvedTheme;
  setPref: (p: ThemePref) => void;
}

const Ctx = createContext<ThemeCtx>({ pref: 'system', theme: 'light', setPref: () => {} });

function readPref(): ThemePref {
  try {
    const v = localStorage.getItem('td.theme');
    return v === 'light' || v === 'dark' ? v : 'system';
  } catch {
    return 'system';
  }
}

const mq = () => (typeof window !== 'undefined' ? window.matchMedia('(prefers-color-scheme: dark)') : null);

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [pref, setPrefState] = useState<ThemePref>(readPref);
  const [systemDark, setSystemDark] = useState<boolean>(() => !!mq()?.matches);

  useEffect(() => {
    const m = mq();
    if (!m) return;
    const on = (e: MediaQueryListEvent) => setSystemDark(e.matches);
    m.addEventListener('change', on);
    return () => m.removeEventListener('change', on);
  }, []);

  const theme: ResolvedTheme = pref === 'system' ? (systemDark ? 'dark' : 'light') : pref;

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
  }, [theme]);

  const value = useMemo<ThemeCtx>(
    () => ({
      pref,
      theme,
      setPref: (p) => {
        setPrefState(p);
        try {
          localStorage.setItem('td.theme', p);
        } catch {
          /* ignore */
        }
      },
    }),
    [pref, theme],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export const useTheme = () => useContext(Ctx);
