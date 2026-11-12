"""Database router.

The `medusa` alias points at a READ-ONLY replica of the Medusa backend database.
No Django model lives there: ingestion connectors use raw SQL via
`django.db.connections["medusa"]` (see ingestion/connectors/medusa_queries.py).
This router guarantees we never migrate or write to it.
"""

MEDUSA_ALIAS = "medusa"


class MedusaRouter:
    def db_for_read(self, model, **hints):
        return "default"

    def db_for_write(self, model, **hints):
        return "default"

    def allow_relation(self, obj1, obj2, **hints):
        return True

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        if db == MEDUSA_ALIAS:
            return False
        return None
