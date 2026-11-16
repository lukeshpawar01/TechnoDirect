"""TD Target Forecaster — suggested targets for next month (see masters/target_forecast.py).

    python manage.py forecast_targets                       # next month, from data to date (also runs on the 27th)
    python manage.py forecast_targets --month 2026-11 --as-of 2026-10-27   # re-create a past forecast (backtest)
    python manage.py forecast_targets --backtest            # walk-forward accuracy for every month with targets
"""
import datetime as dt
import statistics

from django.core.management.base import BaseCommand, CommandError

from analytics.cache import bump_cache_version
from masters.target_forecast import History, backtest, choose_params, run


class Command(BaseCommand):
    help = "Forecast next month's targets per ASM / distributor (TD Target Forecaster)."

    def add_arguments(self, parser):
        parser.add_argument("--month", help="Forecast month YYYY-MM (default: the month after --as-of)")
        parser.add_argument("--as-of", dest="as_of", help="Use data up to this day YYYY-MM-DD (default: latest)")
        parser.add_argument("--backtest", action="store_true", help="Walk-forward accuracy report; saves nothing")

    def handle(self, *args, **o):
        h = History()
        if o["backtest"]:
            months = sorted({m for tm in h.targets.values() for m in tm})[1:]
            params, _ = choose_params(h, months[:-1]) if len(months) > 3 else ({"alpha": .5, "phi": .5, "anchor": "last"}, {})
            key = (params["alpha"], params["phi"], params["anchor"])
            rows = backtest(h, months, *key)[key]
            self.stdout.write(f"  params tuned on {months[0]:%b-%y}..{months[-2]:%b-%y}: {params}; last month is the holdout")
            for r in rows:
                self.stdout.write(f"  {r['month']}  model {r['wape'] * 100:5.1f}%   'same as last month' "
                                  f"{r['baseline_wape'] * 100:5.1f}%   set {r['target'] / 1e5:7.1f} L   "
                                  f"suggested {r['suggested'] / 1e5:7.1f} L")
            self.stdout.write(f"  mean WAPE: model {statistics.mean(r['wape'] for r in rows) * 100:.1f}%  "
                              f"baseline {statistics.mean(r['baseline_wape'] for r in rows) * 100:.1f}%")
            return
        try:
            as_of = dt.date.fromisoformat(o["as_of"]) if o["as_of"] else None
            month = dt.date.fromisoformat(o["month"] + "-01") if o["month"] else None
        except ValueError as e:
            raise CommandError(str(e)) from None
        res = run(month=month, as_of=as_of, h=h)
        bump_cache_version()
        self.stdout.write(f"  {res['month']:%b-%y} forecast as of {res['as_of']}: {res['asms']} ASMs, overall "
                          f"{res['overall'] / 1e5:.1f} L, params {res['params']}, train WAPE {res['train_wape']}")
        self.stdout.write(self.style.SUCCESS("[forecast] done."))
