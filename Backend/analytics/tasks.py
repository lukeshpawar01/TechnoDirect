from celery import shared_task

from .derivations import run_all_derivations


@shared_task(name="analytics.tasks.run_derivations")
def run_derivations():
    return run_all_derivations()
