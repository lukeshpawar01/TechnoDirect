/** Lifecycle groups of retailers (the `segment` filter): tabs on the Retailers and Retailer Funnel pages. */
export const SEGMENT_TABS = [
  { value: '', label: 'All' },
  { value: 'new', label: 'New' },
  { value: 'repeat', label: 'Repeat' },
  { value: 'one_time', label: 'One-time' },
  { value: 'retained', label: 'Retained' },
  { value: 'reactivated', label: 'Reactivated' },
  { value: 'never_ordered', label: 'Never ordered' },
  { value: 'inactive_30', label: 'Inactive 30+' },
  { value: 'inactive_60', label: 'Inactive 60+' },
  { value: 'inactive_90', label: 'Inactive 90+' },
];

/** What each lifecycle tab contains (the rule), then what to do with it. */
export const ACTION_HINT: Record<string, string> = {
  new: 'First-ever order placed in a month of the selected period.',
  repeat: 'Two or more orders, all time.',
  one_time: 'Exactly one order, all time — second-order offers.',
  retained: 'Ordered in a month of the period and in the month before it.',
  reactivated: 'Ordered in a month of the period after skipping the month before (not their first month) — keep them on rhythm.',
  never_ordered: 'Registered retailers who have never ordered — call warm (ledger-matched) ones first.',
  inactive_30: 'Last order 30–59 days ago — reactivation calls.',
  inactive_60: 'Last order 60–89 days ago — at risk of churn.',
  inactive_90: 'Last order 90+ days ago — treat as lost; win-back offers.',
};
