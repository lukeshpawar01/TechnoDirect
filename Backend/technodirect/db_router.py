"""Database router.

The `supabase` alias is the TD database on Supabase, reached with a READ-ONLY login. No Django model lives there:
the ingestion connector uses raw SQL via `django.db.connections["supabase"]`
(see ingestion/connectors/supabase_queries.py). This router guarantees we never migrate or write to it.
"""

SUPABASE_ALIAS = "supabase"


class ReadOnlySourceRouter:
    def db_for_read(self, model, **hints):
        return "default"

    def db_for_write(self, model, **hints):
        return "default"

    def allow_relation(self, obj1, obj2, **hints):
        return True

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        if db == SUPABASE_ALIAS:
            return False
        return None
