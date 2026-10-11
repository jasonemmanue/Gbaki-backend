"""
Indexe le texte des documents (recherche plein texte) et génère la vignette de la 1re page.

    python manage.py index_documents                 # documents jamais indexés
    python manage.py index_documents --class AS1 --limit 50
    python manage.py index_documents --force         # réindexe tout
    python manage.py index_documents --workers 6
    python manage.py index_documents --retry-empty   # relance les PDF / textes restés sans texte

Reprenable : sans --force, seuls les documents sans indexed_at sont traités.
"""
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from django.core.management.base import BaseCommand, CommandError
from django.db import close_old_connections
from django.db.models import Q

from core.indexing import index_document
from core.models import Document
from core.r2 import get_r2_client, r2_configured


def _work(doc_id):
    close_old_connections()
    try:
        doc = Document.objects.get(pk=doc_id)
        return doc, index_document(doc, client=get_r2_client())
    finally:
        close_old_connections()


class Command(BaseCommand):
    help = "Extrait le texte page par page et crée les vignettes des documents."

    def add_arguments(self, parser):
        parser.add_argument('--class', dest='class_code', help="Code de classe (ex : AS1)")
        parser.add_argument('--limit', type=int, default=0)
        parser.add_argument('--workers', type=int, default=4)
        parser.add_argument('--force', action='store_true', help="Réindexer aussi les documents déjà traités")
        parser.add_argument('--retry-empty', action='store_true',
                            help="Relancer les documents déjà traités mais sans aucune page de texte (erreurs, scans)")

    def handle(self, *args, **opts):
        if not r2_configured():
            raise CommandError("Cloudflare R2 non configuré (CF_R2_ENDPOINT_URL / CF_R2_ACCESS_KEY).")

        qs = Document.objects.order_by('class_id__code', 'file_path')
        if opts['retry_empty']:
            qs = qs.filter(indexed_at__isnull=False, is_folder=False, pages__isnull=True).filter(
                Q(file_name__iendswith='.pdf') | Q(mime_type__startswith='text/'))
        elif not opts['force']:
            qs = qs.filter(indexed_at__isnull=True)
        if opts['class_code']:
            qs = qs.filter(class_id__code=opts['class_code'])
        ids = list(qs.values_list('id', flat=True))
        if opts['limit']:
            ids = ids[:opts['limit']]

        total = len(ids)
        self.stdout.write(f"{total} document(s) à indexer avec {opts['workers']} worker(s).")
        start, errors = time.time(), 0
        with ThreadPoolExecutor(max_workers=opts['workers']) as pool:
            futures = [pool.submit(_work, i) for i in ids]
            for n, fut in enumerate(as_completed(futures), start=1):
                try:
                    doc, status = fut.result()
                    if status.startswith('erreur'):
                        errors += 1
                    self.stdout.write(f"[{n}/{total}] {doc.file_path} : {status}")
                except Exception as exc:
                    errors += 1
                    self.stdout.write(self.style.ERROR(f"[{n}/{total}] échec : {exc}"))
                if n % 100 == 0:
                    self.stdout.flush()

        elapsed = int(time.time() - start)
        self.stdout.write(self.style.SUCCESS(
            f"Terminé : {total} document(s) en {elapsed // 60} min {elapsed % 60} s, {errors} erreur(s)."
        ))
