import { useState } from "react";
import { useAnalytics } from "@/api/hooks";
import { date, inr, num, pct } from "@/lib/format";
import { DataTable } from "./DataTable";
import { MiniStat } from "./KpiTile";
import { IconPulse } from "./Icons";
import {
  Badge,
  Drawer,
  EmptyState,
  Segmented,
  Skeleton,
  type Tone,
} from "./ui";

type GroupBy = "region" | "state" | "asm" | "distributor";
type Status =
  "achieved" | "on_track" | "at_risk" | "behind" | "missed" | "no_target";
interface Rates {
  target: number;
  achieved: number;
  achievement_pct: number | null;
  balance: number;
  days_elapsed: number;
  days_total: number;
  days_left: number;
  current_run_rate: number;
  last7_run_rate: number;
  required_run_rate: number;
  gap_per_day: number;
  projected: number;
  projected_pct: number | null;
  status: Status;
}
interface Row extends Rates {
  id: number;
  name: string;
}
interface RunRateData {
  group_by: GroupBy;
  as_of: string;
  last7_from: string;
  overall: Rates | null;
  rows: Row[];
  counts?: Partial<Record<Status, number>>;
  note: string | null;
}

const STATUS: Record<Status, { label: string; tone: Tone; hint: string }> = {
  achieved: { label: "Achieved", tone: "good", hint: "Target already reached" },
  on_track: {
    label: "On track",
    tone: "good",
    hint: "At the current pace the target is reached",
  },
  at_risk: {
    label: "At risk",
    tone: "warn",
    hint: "At the current pace it ends at 90–100% of target",
  },
  behind: {
    label: "Behind",
    tone: "bad",
    hint: "At the current pace it ends below 90% of target",
  },
  missed: {
    label: "Missed",
    tone: "bad",
    hint: "The period is over and the target was not reached",
  },
  no_target: { label: "No target", tone: "neutral", hint: "No target set" },
};
const GROUPS: { value: GroupBy; label: string }[] = [
  { value: "region", label: "Region" },
  { value: "state", label: "State" },
  { value: "asm", label: "ASM" },
  { value: "distributor", label: "Distributor" },
];
const perDay = (v: number | null | undefined) =>
  v === null || v === undefined ? "–" : `${inr(v)}/day`;

/** "Run rate" button for the Executive Overview header: opens the run-rate panel. */
export function RunRateButton() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button
        className="btn btn-sm"
        onClick={() => setOpen(true)}
        title="Current vs required daily sales, projection, and who is behind"
      >
        <IconPulse size={13} /> Run rate
      </button>
      <RunRateDrawer open={open} onClose={() => setOpen(false)} />
    </>
  );
}

function RunRateDrawer({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const [groupBy, setGroupBy] = useState<GroupBy>("region");
  const q = useAnalytics<RunRateData>(
    "/overview/run-rate/",
    { group_by: groupBy },
    { enabled: open },
  );
  const d = q.data?.data;
  const o = d?.overall;
  const st = o ? STATUS[o.status] : null;

  return (
    <Drawer open={open} onClose={onClose} width={1100} title="Run rate">
      {q.isLoading ? (
        <Skeleton className="h-64" />
      ) : !o && !d?.rows.length ? (
        <EmptyState
          title="Run rate not available"
          hint={d?.note ?? "No target for this period and scope."}
          height={200}
        />
      ) : (
        <>
          {!o && d?.note && (
            <p className="mb-3 rounded-md bg-sunken px-3 py-2 text-xs text-ink2">
              {d.note} The breakdown below uses each one's own target.
            </p>
          )}
          {o && (
            <>
              <div className="mb-3 flex flex-wrap items-center gap-2 text-sm">
                <span className="text-ink2">
                  {q.data?.meta?.period?.label ?? "Period"} · day{" "}
                  {num(o.days_elapsed)} of {num(o.days_total)} ·{" "}
                  {num(o.days_left)} days left · sales up to {date(d?.as_of)}
                </span>
                {st && (
                  <span className="ml-auto" title={st.hint}>
                    <Badge tone={st.tone} icon>
                      {st.label}
                    </Badge>
                  </span>
                )}
              </div>

              <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
                <MiniStat
                  label="Target"
                  value={inr(o.target)}
                  sub={`Achieved ${inr(o.achieved)} (${pct(o.achievement_pct)})`}
                />
                <MiniStat
                  label="Current run rate"
                  value={perDay(o.current_run_rate)}
                  sub="Sales so far ÷ days elapsed"
                />
                <MiniStat
                  label="Last 7 days"
                  value={perDay(o.last7_run_rate)}
                  sub={`${date(d?.last7_from)} – ${date(d?.as_of)}`}
                  tone={
                    o.last7_run_rate < o.current_run_rate ? "warn" : undefined
                  }
                />
                <MiniStat
                  label="Required run rate"
                  value={o.days_left > 0 ? perDay(o.required_run_rate) : "–"}
                  sub={
                    o.days_left > 0
                      ? `${inr(o.balance)} left ÷ ${num(o.days_left)} days`
                      : "Period over"
                  }
                  tone={
                    o.days_left > 0 && o.required_run_rate > o.current_run_rate
                      ? "bad"
                      : undefined
                  }
                />
                <MiniStat
                  label="Projected"
                  value={inr(o.projected)}
                  sub={`${pct(o.projected_pct)} of target at the current pace`}
                  tone={
                    st?.tone === "bad"
                      ? "bad"
                      : st?.tone === "warn"
                        ? "warn"
                        : "good"
                  }
                />
                <MiniStat
                  label="Gap per day"
                  value={o.gap_per_day ? perDay(o.gap_per_day) : "–"}
                  sub={
                    o.gap_per_day
                      ? "Extra needed each day vs current pace"
                      : "No extra needed"
                  }
                  tone={o.gap_per_day ? "bad" : "good"}
                />
                <MiniStat
                  label="Target left"
                  value={inr(o.balance)}
                  sub={`${pct(o.achievement_pct)} done`}
                />
                <MiniStat
                  label="Behind / at risk"
                  value={`${num((d?.counts?.behind ?? 0) + (d?.counts?.missed ?? 0))} / ${num(d?.counts?.at_risk ?? 0)}`}
                  sub={`of ${num(d?.rows.filter((r) => r.status !== "no_target").length)} ${GROUPS.find((g) => g.value === groupBy)?.label.toLowerCase()}s with a target`}
                />
              </div>
            </>
          )}

          <div className="mt-5 mb-2 flex flex-wrap items-center gap-2">
            <h3 className="mr-auto text-sm font-semibold text-ink">
              By {GROUPS.find((g) => g.value === groupBy)?.label}
            </h3>
            <Segmented value={groupBy} onChange={setGroupBy} options={GROUPS} />
          </div>
          <DataTable
            rows={d?.rows}
            loading={q.isFetching && !d}
            fetching={q.isFetching}
            error={q.error}
            onRetry={() => q.refetch()}
            rowKey={(r) => r.id}
            exportName={`run_rate_by_${groupBy}`}
            exportPath="/overview/run-rate/"
            exportParams={{ group_by: groupBy }}
            pageSize={25}
            dense
            columns={[
              {
                key: "name",
                header:
                  GROUPS.find((g) => g.value === groupBy)?.label ?? "Name",
                render: (r) => (
                  <span className="font-medium text-ink">{r.name}</span>
                ),
              },
              {
                key: "status",
                header: "Status",
                render: (r) => (
                  <span title={STATUS[r.status].hint}>
                    <Badge tone={STATUS[r.status].tone}>
                      {STATUS[r.status].label}
                    </Badge>
                  </span>
                ),
                value: (r) => STATUS[r.status].label,
              },
              {
                key: "target",
                header: "Target",
                align: "right",
                render: (r) => (r.target ? inr(r.target) : "–"),
              },
              {
                key: "achieved",
                header: "Achieved",
                align: "right",
                render: (r) => inr(r.achieved),
              },
              {
                key: "achievement_pct",
                header: "Ach. %",
                align: "right",
                render: (r) => pct(r.achievement_pct),
              },
              {
                key: "current_run_rate",
                header: "Current / day",
                align: "right",
                render: (r) => inr(r.current_run_rate),
              },
              {
                key: "last7_run_rate",
                header: "Last 7 days / day",
                align: "right",
                render: (r) => inr(r.last7_run_rate),
              },
              {
                key: "required_run_rate",
                header: "Required / day",
                align: "right",
                render: (r) =>
                  r.target && r.days_left > 0 ? inr(r.required_run_rate) : "–",
              },
              {
                key: "gap_per_day",
                header: "Gap / day",
                align: "right",
                render: (r) =>
                  r.gap_per_day ? (
                    <span className="font-medium text-bad">
                      {inr(r.gap_per_day)}
                    </span>
                  ) : (
                    <span className="text-muted">–</span>
                  ),
              },
              {
                key: "projected",
                header: "Projected",
                align: "right",
                render: (r) => inr(r.projected),
              },
              {
                key: "projected_pct",
                header: "Projected %",
                align: "right",
                render: (r) => pct(r.projected_pct),
              },
            ]}
          />
          <p className="mt-3 text-2xs text-muted">
            Current run rate = sales so far ÷ days elapsed. Required run rate =
            target left ÷ days left. Projected = current run rate × all days of
            the month(s) with a target. On track: projected ≥ target; at risk:
            90–100%; behind: below 90%. Counts only the months of the period
            that have a target; follows the top filters (dates, region, ASM,
            distributor…).
          </p>
        </>
      )}
    </Drawer>
  );
}
