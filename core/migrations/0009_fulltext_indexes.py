"""
Index de recherche plein texte (PostgreSQL uniquement, sans effet sous SQLite).

- unaccent + pg_trgm
- gbaki_unaccent() : wrapper IMMUTABLE d'unaccent, utilisable dans un index
- GIN sur to_tsvector('french', gbaki_unaccent(content)) des pages
- GIN trigramme sur le vocabulaire (correction des fautes de frappe)
"""
from django.db import migrations

FORWARD = [
    "CREATE EXTENSION IF NOT EXISTS unaccent",
    "CREATE EXTENSION IF NOT EXISTS pg_trgm",
    """
    CREATE OR REPLACE FUNCTION gbaki_unaccent(text) RETURNS text AS
    $$ SELECT public.unaccent('public.unaccent'::regdictionary, $1) $$
    LANGUAGE sql IMMUTABLE PARALLEL SAFE STRICT
    """,
    """
    CREATE INDEX IF NOT EXISTS core_documentpage_fts
    ON core_documentpage USING GIN (to_tsvector('french', gbaki_unaccent(content)))
    """,
    """
    CREATE INDEX IF NOT EXISTS core_searchterm_trgm
    ON core_searchterm USING GIN (word gin_trgm_ops)
    """,
]

BACKWARD = [
    "DROP INDEX IF EXISTS core_searchterm_trgm",
    "DROP INDEX IF EXISTS core_documentpage_fts",
    "DROP FUNCTION IF EXISTS gbaki_unaccent(text)",
]


def _run(statements):
    def apply(apps, schema_editor):
        if schema_editor.connection.vendor != 'postgresql':
            return
        for sql in statements:
            schema_editor.execute(sql)
    return apply


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0008_document_index_fields'),
    ]

    operations = [
        migrations.RunPython(_run(FORWARD), _run(BACKWARD)),
    ]
