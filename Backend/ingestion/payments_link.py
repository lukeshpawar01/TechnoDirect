"""Link PayU transactions to Medusa orders and derive Order.payment_status.

Matching (first hit wins):
  1. Payment.txnid      == Order.payment_ref   (merchant txnid stored on the Medusa order)
  2. Payment.order_ref  == Order.split_group / Order.source_id / Order.display_id

A cart that was split into several distributor orders shares one PayU txn, so the
txn status is applied to every order in the split group.

Order.payment_status rule: if the group has any PayU txn -> PayU wins (success beats
others, otherwise the latest txn); else fall back to the Medusa payment status.
"""
from django.db.models import Q

from warehouse.models import PAYU_TO_ORDER_PAYMENT, Order, Payment, compute_is_qualifying

from .upsert import chunked


def link_unmatched_payments(payment_ids=None):
    qs = Payment.objects.filter(split_group="")
    if payment_ids is not None:
        qs = qs.filter(id__in=payment_ids)
    pays = list(qs.only("id", "txnid", "order_ref"))
    if not pays:
        return set()
    txnids = {p.txnid for p in pays if p.txnid}
    refs = {p.order_ref for p in pays if p.order_ref}
    by_ref, by_txn = {}, {}
    for chunk in chunked(txnids):
        for oid, ref, grp in Order.objects.filter(payment_ref__in=chunk).values_list("id", "payment_ref",
                                                                                      "split_group"):
            by_txn.setdefault(ref, (oid, grp))
    for chunk in chunked(refs):
        for oid, sid, did, grp in Order.objects.filter(
                Q(split_group__in=chunk) | Q(source_id__in=chunk) | Q(display_id__in=chunk)
        ).values_list("id", "source_id", "display_id", "split_group"):
            for key in (grp, sid, did):
                if key in refs:
                    by_ref.setdefault(key, (oid, grp))
    touched, updates = set(), []
    for p in pays:
        hit = by_txn.get(p.txnid) or by_ref.get(p.order_ref)
        if hit:
            p.order_id, p.split_group = hit
            updates.append(p)
            touched.add(hit[1])
    Payment.objects.bulk_update(updates, ["order_id", "split_group"], batch_size=1000)
    return touched


def reconcile_payments(split_groups=None):
    """Link unmatched txns then recompute payment fields for affected (or all) split groups."""
    touched = link_unmatched_payments()
    if split_groups is None:
        groups = None
    else:
        groups = set(split_groups) | touched
        if not groups:
            return 0
    group_iter = [None] if groups is None else list(chunked(groups))
    changed = 0
    for chunk in group_iter:
        pq = Payment.objects.exclude(split_group="")
        oq = Order.objects.all()
        if chunk is not None:
            pq = pq.filter(split_group__in=chunk)
            oq = oq.filter(split_group__in=chunk)
        best = {}
        for grp, pid, status, mode, added in pq.values_list("split_group", "source_id", "status", "mode",
                                                            "added_on").order_by("added_on"):
            cur = best.get(grp)
            # success beats everything; otherwise latest txn wins
            if cur is None or status == "success" or cur[1] != "success":
                best[grp] = (pid, status, mode)
        objs = []
        for o in oq.only("id", "split_group", "status", "medusa_payment_status", "payment_status",
                         "payment_mode", "payu_txn_id", "payment_status_source", "is_qualifying"):
            b = best.get(o.split_group)
            if b:
                ps, mode, txn, src = PAYU_TO_ORDER_PAYMENT.get(b[1], "awaiting"), b[2], b[0], "payu"
                # keep Medusa refund states (refunds are out of scope for PayU sync)
                if ps == "captured" and o.medusa_payment_status in ("refunded", "partially_refunded"):
                    ps = o.medusa_payment_status
            else:
                ps, mode, txn, src = o.medusa_payment_status or o.payment_status, o.payment_mode, "", "medusa"
            q = compute_is_qualifying(o.status, ps)
            if (ps, mode, txn, src, q) != (o.payment_status, o.payment_mode, o.payu_txn_id,
                                           o.payment_status_source, o.is_qualifying):
                o.payment_status, o.payment_mode, o.payu_txn_id = ps, mode or "", txn
                o.payment_status_source, o.is_qualifying = src, q
                objs.append(o)
        Order.objects.bulk_update(objs, ["payment_status", "payment_mode", "payu_txn_id",
                                         "payment_status_source", "is_qualifying"], batch_size=1000)
        changed += len(objs)
    return changed
