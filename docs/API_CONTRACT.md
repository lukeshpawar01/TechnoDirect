# TechnoDirect Dashboard — API Contract (v1)

> **Scope note (11 Nov 2026):** PayU is in scope for sales/order data only. Not built now: `/alerts/*`, `manage_alerts`,
> the `refunds` key in `/orders/summary/`, `refunds[]` in `/orders/{id}/`, `refund_value` on order rows, and anything settlement-related.
> `payment` in `/orders/summary/` = `{success, failed, pending, failed_value, paid_no_order, mode_mix:[{mode,count,value}]}`.
> Refresh: data refreshes at 10:00 and 18:00 IST only. Every envelope `meta` also carries `last_refresh_at` and `next_refresh_at`.
> `POST /data-health/sync/` accepts `source=all`. There is no `/overview/live/` endpoint.

Base URL: `/api`. JSON. Auth: `Authorization: Bearer <access JWT>`. All money values are numbers in INR (rupees, not paise).
Dates: `YYYY-MM-DD` (IST). Datetimes: ISO-8601 with offset.

## Envelope for analytics endpoints
```json
{
  "data": { ... },
  "meta": {
    "sales_basis": "Gross order value (incl. taxes, before returns)",
    "as_of": "2026-11-11T10:15:00+05:30",
    "period": {"from": "2026-11-01", "to": "2026-11-11", "label": "MTD", "compare_from": "2026-10-01", "compare_to": "2026-10-11"},
    "freshness": [{"source": "medusa", "last_success_at": "...", "status": "ok|stale|failed"}]
  }
}
```
Paginated lists: `{"count": n, "next": url|null, "previous": url|null, "results": [...]}` (page size param `page_size`, default 50).
Any list endpoint accepts `?export=csv|xlsx` (requires permission `export_data`) and returns a file download.

## Common filter query params (every analytics + list endpoint)
`preset` = today|yesterday|wtd|last_week|mtd|prev_month|q1|q2|q3|q4|qtd|fytd|last_7d|last_30d|last_90d|last_12m|all_time|custom
(default mtd; q1–q4 = FY quarters Apr–Jun / Jul–Sep / Oct–Dec / Jan–Mar of the current FY, or last FY if not started yet;
a running quarter compares the same days of the previous quarter; all_time = first order date → today, no comparison) ·
`date_from`, `date_to` (when custom) · `region`, `state`, `asm`, `distributor`, `retailer`, `category`, `article`
(comma-separated ids/codes) · `segment` = new|retained|reactivated|inactive|one_time|repeat · `order_status` · `payment_status`.

Module filters (sent only by the page that shows them; ignored where not applicable): `platform` (android,web) ·
`payment_mode` (UPI,CC,DC,NB) · `is_split=true|false` (split carts / single-distributor orders) · `order_status` (received,confirmed,shipped,delivered,cancelled; the summary's status chart always lists every status) · `cat_l1`, `cat_l2`, `cat_l3` (category I/II/III; order lines,
products and stock) · `size` (stock) · `has_account=true|false` (retailers / funnel; API only, not offered in the UI) · `kyc_status` (Retailers / Funnel) · `kyc_verified=true|false` (Retailers / Funnel; customer kyc column) ·
`event_type` = new_customer|earned|redeemed (loyalty) · `stock_sync` = fresh|stale|never (distributor scorecard).
`/meta/filters/` also returns `payment_modes`, `platforms`, `category_tree` [{l1,l2,l3}] and `sizes` for these.
The server additionally intersects with the user's data scope.

## Auth & users
- `POST /auth/token/` {email, password} → step 1. With OTP on (default): `{otp_required:true, challenge_id, email (masked), expires_in, resend_in, resends_left}` and a 6-digit code is emailed; wrong password → 401. With `LOGIN_OTP_ENABLED=False`: `{access, refresh}`.
- `POST /auth/otp/verify/` {challenge_id, code} → `{access, refresh}`; errors 400 `{detail, code: invalid|expired|restart, attempts_left?}` (`restart` = go back to step 1).
- `POST /auth/otp/resend/` {challenge_id} → same shape as step 1; 429 `{code:"too_soon", resend_in}` during the 30 s cooldown.
- `POST /auth/token/` {email,password} → {access, refresh}
- `POST /auth/token/refresh/` {refresh} → {access}
- `GET /auth/me/` → `{id,email,full_name,is_master_admin,role:{id,name},permissions:[code],scope:{all:bool,regions:[id],states:[id],asms:[id],distributors:[id]}}`
- `POST /auth/change-password/` {old_password,new_password}
- `GET/POST /admin/users/`, `GET/PATCH/DELETE /admin/users/{id}/` — user: `{id,email,full_name,is_active,role_id,scope:{...},last_login}`; POST accepts `password`.
- `POST /admin/users/{id}/reset-password/` {new_password}
- `GET/POST /admin/roles/`, `GET/PATCH/DELETE /admin/roles/{id}/` — role: `{id,name,description,permissions:[code],user_count}`
- `GET /admin/permissions/` → `[{code,label,group}]`
- `GET /admin/audit-log/` paginated `{id,at,user_email,action,object_type,object_id,before,after,reason}`

Permission codes: `view_overview, view_funnel, view_distributors, view_territory, view_orders, view_products, view_inventory, view_retention, view_loyalty, view_data_health, export_data, view_pii, manage_targets, manage_mappings, manage_users, manage_alerts, manage_metrics, trigger_sync`.
Master admin (`is_master_admin`) implicitly has all permissions and full scope.

## Filter options
- `GET /meta/filters/` → `{regions:[{id,name}],states:[{id,name,region_id}],asms:[{id,name,region_id}],distributors:[{id,name,state_id}],categories:[{code,name}],order_statuses:[..],payment_statuses:[..]}` (already scope-limited)

## Analytics pages
- `GET /overview/` → data:
```json
{
 "kpis": {"sales":KPI,"orders":KPI,"aov":KPI,"units_per_order":KPI,"realisation_per_unit":KPI,
          "active_retailers":KPI,"new_retailers":KPI,"repeat_retailers":KPI,"active_distributors":KPI},
 "target": {"target":n,"achieved":n,"achievement_pct":n,"balance":n,"days_elapsed":n,"days_total":n,
            "current_run_rate":n,"required_run_rate":n,"projected":n} | null,
 "daily_trend": [{"date":"2026-11-01","sales":n,"orders":n,"cum_sales":n,"cum_target":n|null}],
 "monthly": [{"month":"2025-12","sales":n,"orders":n,"aov":n,"active_retailers":n,"prev_year_sales":n|null}],
 "order_funnel": [{"status":"received|confirmed|shipped|delivered|cancelled","count":n,"value":n}],
 "concentration": {"top3_distributor_share":n,"top_state":{"name":s,"share":n},"top10_retailer_share":n},
 "top_distributors": [{"id","name","sales","share","growth_pct"}],
 "top_states": [{"id","name","sales","share"}],
 "exceptions": [{"code","severity":"high|medium|low","count":n,"message":s,"link":"/orders?..."}]
}
```
  KPI = `{"value":n,"compare":n|null,"delta_pct":n|null,"spark":[n,...12 months]}`
- `GET /funnel/` → `{"stages":[{"key":"signed_up|kyc_submitted|kyc_approved|first_order|repeat_order|active_this_period","label","count"}],
  "kyc_status":[{"status":"pending|approved|rejected","count"}], "never_ordered":{"total","warm","cold","flagged"},
  "inactivity":{"d30","d60","d90"}, "signup_cohorts":[{"month","signed_up","kyc_approved","first_order","kyc_rate","order_rate"}] (by sign-up month; no KYC approval date in the source), "kyc_conversion":{"kyc_approved","converted","rate","median_days","within_30d","within_30d_pct","basis":"signup"} (time to first order measured from the created date),
  "acquisition_monthly":[{"month","new_retailers","cumulative"}], "by_state":[{"state","kyc_approved","ever_ordered","active","adoption_pct"}]}`
- `GET /retailers/` (list; segment filter incl. `never_ordered`, `inactive_30|60|90`) → rows `{id,name,phone(masked unless view_pii),state,distributor,asm,kyc_status,first_order_date,last_order_date,days_since_last_order,orders,sales,segment,warm_match}`
- `GET /retailers/{id}/` → profile + `monthly:[{month,sales,orders}]` + `recent_orders:[...]`
- `GET /distributors/` → `{"rows":[{id,name,state,sales,share,orders,aov,retailers,active_retailers,new_retailers,repeat_pct,orders_per_retailer,dispatch_pct,median_dispatch_days,l3m_sales,growth_pct,prev_sales,target,achievement_pct,last_stock_sync,spark:[12]}]}` · Leaders & laggards (top/bottom 5) is computed client-side from these rows: sales (>0), growth (prev_sales ≥ ₹50K), target achievement (has target), activation (active/mapped retailers, ≥20 mapped), fulfilment (dispatch %, ≥5 orders).
- `GET /distributors/{id}/` → `{profile, kpis, monthly:[...], top_articles:[...], retailers:[...top 50]}`
- `GET /territory/?group_by=region|state|asm` → `{"rows":[{id,name,sales,target,achievement_pct,orders,active_retailers,new_retailers,kyc_base,adoption_pct,distributors,growth_pct}], "monthly_by_group":[{month, group, sales}]}`
- `GET /orders/summary/` → `{"status_counts":[{status,count,value}],"ageing":[{bucket:"0-1d|1-2d|2-4d|4-7d|7d+",status,count}],
  "tat":{"order_to_dispatch_median_h","order_to_delivery_median_h","trend":[{month,dispatch_h,delivery_h}]},
  "cancellation_rate","payment":{"success","failed","failed_value","paid_no_order"},
  "refunds":{"pending_count","pending_value","processed_value","ageing":[{bucket,count}]},
  "split_orders":{"split_carts","total_carts"}, "sla_breaches":n, "crm":{"open","by_type":[{type,count}]}}`
- `GET /orders/` list → `{id,display_id,placed_at,retailer,distributor,state,status,payment_status,value,units,awb,dispatch_hours,is_split,refund_value}`; `GET /orders/{id}/` → with `lines[]`, `payments[]`, `refunds[]`, `timeline[]`.
- `GET /products/` → `{"categories":[{code,name,sales,units,share,realisation}],"category_mix_monthly":[{month,category,sales}],
  "top_articles":[{style,name,category,sales,units,orders,retailers,share}],"bottom_articles":[...],"new_launches":[{style,launched_on,sales,units,retailers}],
  "size_mix":[{size,units,share}],"concentration":{"top4_share","top12_share","distinct_articles"}}`
- `GET /inventory/` → `{"sync":[{distributor_id,distributor,last_sync_at,status,skus,in_stock_skus}],"summary":{"live_styles","oos_skus","low_stock_skus"},
  "oos_top_sellers":[{style,size,distributor,last_30d_units}],"rows":paginated? no → use /inventory/items/}`; `GET /inventory/items/` list.
- `GET /retention/` → `{"movement":[{month,active,retained,reactivated,new,lost,net,mom_retention}],"quarterly_retention":[{quarter,rate}],
  "cohorts":[{cohort:"2025-01",size,values:[pct...]}],"contribution":[{month,new_sales,repeat_sales,reactivated_sales}],
  "order_bands":[{band:"1|2|3-5|6-10|11-20|21+",retailers,sales}],"pareto":[{top_n,share}],"avg_days_between_orders":n,"orders_per_active_retailer":[{month,value}]}`
- `GET /growth/` (perm `view_retention`; TD_DataDeck slides 28–44, 56, 59–61; launch → period end, scope and filters apply) → `{"headline":{since,cum_sales,cum_orders,retailers,distributors,last_month,last_month_sales,repeat_share_last_month,record_month},
  "monthly":[{month,is_partial,sales,orders,units,active_retailers,distributors,new_retailers,aov,units_per_order,realisation_per_unit,sales_per_retailer,orders_per_retailer,mom_pct,prev_year_sales,yoy_pct,cum_sales,cum_orders,cum_retailers,active_pct_of_base,new_sales,repeat_sales,repeat_share,articles_per_order,articles_sold}],
  "quarters"|"fy":[{label,start,sales,orders,aov,active_retailers,growth_pct,is_partial}],"milestones":[{month,kind:cumulative|month|record,label}],
  "decomposition":{period,compare,prev_sales,cur_sales,change,change_pct,available,factors:[{key,label,prev,cur,change_pct,share_pct,contribution}],aov_factors:[…]}` (selected period vs the same dates last year; sales = active retailers × orders per retailer × AOV, AOV = units per order × realisation; shares by log contribution, sum to 100),
  `"bridge":{window,prev_window,prev_total,cur_total,like_for_like:{retailers,prev,cur,change,change_pct},new:{retailers,sales},lapsed:{retailers,sales}}` (6 months to the period end vs the same window LY; prev − lapsed + LFL change + new = cur),
  `"retailer_value":{window,transacting,avg_spend,median_spend,top_quartile:{retailers,avg_spend,share},histogram:[{bucket,retailers}],months_active:[{months,retailers}],avg_months_active,single_month,lifetime:{acquired,repeat_retailers,repeat_pct,repeat_sales_share,avg_orders,one_order,one_order_sales},first_vs_repeat_aov:{first_aov,first_orders,repeat_aov,repeat_orders},top_retailers:[{id,name,orders,sales,months_active,last_order}]}}`
- `GET /distributors/insights/` (perm `view_distributors`; slides 49, 52, 62, 63) → `{"trend":{months,series:[{name,data}]}` (period's top 5 + Other, 12 months), `"top_articles":[{id,name,sales,articles:[{style,sales}×3]}]`, `"multi_distributor":{retailers,multi,multi_pct,avg_orders_multi,avg_orders_single,monthly:[{month,active,multi,multi_pct}]}`, `"transacting_monthly":[{month,distributors,retailers}]}`
- Also added: `/distributors/` rows `p3m_sales, l3m_growth_pct` (≥ ₹50K base), `sales_per_retailer`; `/territory/` rows `sales_per_retailer`; `/funnel/` `kyc_penetration:{kyc_approved,ever_ordered,ever_pct,active,active_pct,period_label}`; `/products/` `category_mix:[{l1,l2,sales,units,orders,share,realisation,units_per_order}]`, `category_mix_monthly_l1l2`, `new_articles_6m:{since,articles,sales,share}`, article rows `realisation, units_per_order`; `/orders/summary/` `tat.trend[].dispatch_pct`.
- `GET /trends/mom/?months=6|12|24` (perm `view_overview`) → `{months:[{month,is_partial,days,basis:full_month|same_days,sales,orders,pieces,boxes,avg_price_per_piece,prev_sales,prev_pieces,prev_boxes,sales_mom_pct,pieces_mom_pct,boxes_mom_pct,avg_price_mom_pct}],range,as_of,first_data_month}`. Months end at the period end; the running month's MoM compares days 1..N with days 1..N of the previous month. Honors all global filters (category/article → line-level value and quantity).
- `GET /loyalty/` (perm `view_loyalty`) → `{"period":{points_issued,points_redeemed,net_points,redemption_rate,events,members,earning_retailers,redeeming_retailers,new_members},"previous":{same}|null,"lifetime":{same},
  "data_range":{first,last},"monthly":[{month,issued,redeemed,earners,new_members}],"by_event":[{event,events,points}],"by_state":[{state,members,issued,redeemed}],
  "top_members":[{retailer_id,retailer,owner,state,distributor,earned,redeemed,balance,orders,events,last_event}]}`. Points are positive numbers; `redemption_rate` is 0–100. Export: `?export=csv` (top_members).
- `GET /data-health/` → `{"sources":[{source,status,last_success_at,last_error,rows_last_run,next_run_at}],"issues":[{code,label,count,severity}],"reconciliation":[{metric,period,dashboard_value,mis_value,diff_pct}]}`
- `POST /data-health/sync/` {source} → triggers sync (perm `trigger_sync`).

## ASM tracker (Region & ASM Performance page, `/territory`: Export / Upload / Edit)
- `GET /masters/asm-tracker/?month=YYYY-MM` (perm `view_territory`, scoped) → `{month, as_of, rows:[{distributor_id, distributor, region, asm_id, asm, sales, orders, share, target, remaining, achieved_pct, asm_target, asm_sales, asm_achieved_pct}], asm_summary:[...], totals, regions, asms}`; add `&download=xlsx` for the Excel tracker (needs `export_data`).
- `POST /masters/asm-tracker/` `{month, rows:[{distributor_id, region, asm, target}]}` and `POST /masters/asm-tracker/upload/` (multipart `file` .xlsx/.csv in the tracker layout + `month`) — perms `manage_targets` + `manage_mappings`. Same rules as `manage.py import_asm_tracker`; the save is the full picture for the month (blank target removes that distributor's own target; ASM / region / overall targets are the sums). Audited.

## Techno AI assistant (perm `use_assistant`)
- `GET /assistant/status/` → `{enabled, configured, model, provider, modules:[label], suggestions:[str]}`
- `POST /assistant/chat/` `{question, history:[{role:user|assistant, content}], context:{page, params:{...current filters}}}` →
  `{answer:{headline, what_to_do:[{text, refs}], data_points:[{text, refs}], explanation, not_authorised:[label], follow_ups:[str]},
  sources:[{ref, tool, label, period, params, ok}], model, took_ms, asked_at}`. 503 `{detail}` when the model is unreachable / not configured;
  rate-limited (`ASSISTANT_RATE_LIMIT`, default 15/min). Data is fetched through the dashboard endpoints as the user (same permissions + scope).

## Masters (Admin)
- `GET/POST /masters/targets/`, `PATCH/DELETE /masters/targets/{id}/` — `{id,month:"2026-11",scope_type:"overall|region|state|asm|distributor",scope_id,scope_name,metric:"sales|orders|new_retailers|active_retailers",value,effective_from,notes}`
- `GET /masters/targets/template/` → xlsx; `POST /masters/targets/upload/` multipart `file` → `{created,updated,errors:[{row,message}]}`
- Same pattern for `/masters/asms/`, `/masters/pincodes/` (pincode→state→asm), `/masters/regions/`, `/masters/states/`, `/masters/reconciliation/` (MIS reference values).
- `GET/PATCH /masters/metrics/` metric dictionary `{code,name,definition,formula,source,owner,refresh}`.

## Alerts
- `GET/POST /alerts/rules/`, `PATCH/DELETE /alerts/rules/{id}/` — `{id,code,name,is_active,threshold,params,channels:["email","whatsapp","in_app"],recipients:[emails/phones]}`
- `GET /alerts/events/` paginated `{id,rule,severity,message,triggered_at,acknowledged}`; `POST /alerts/events/{id}/ack/`
- `GET /alerts/mis/preview/` → HTML of today's daily MIS; `POST /alerts/mis/send-now/`
