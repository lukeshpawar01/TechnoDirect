import type { ChartTokens } from '@/charts/palette';

/** BlueOrigin tiers, best first (sheet "New Tier"; blank = Untiered). */
export const TIERS = ['Platinum', 'Gold', 'Silver', 'Green', 'Yellow', 'Untiered'] as const;
const STRENGTH: Record<string, number> = { Platinum: 5, Gold: 4, Silver: 3, Green: 2, Yellow: 1 };

/**
 * Tiers are ordered by purchase, so they share one sequential ramp (magnitude), not categorical hues:
 * Platinum is the strongest step, Yellow the lightest, Untiered de-emphasised. The tier name is always shown as text.
 */
export function tierColor(tier: string, t: ChartTokens): string {
  const s = STRENGTH[tier];
  if (!s) return t.deemph;
  return t.theme === 'dark' ? t.ordinal[5 - s] : t.ordinal[s];
}
