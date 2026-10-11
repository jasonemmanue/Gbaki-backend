"""
Remplace le catalogue documentaire par les CSV de data/catalogue/.

    python manage.py import_catalogue --confirm
    python manage.py import_catalogue --confirm --dir autre/dossier --skip-r2
    python manage.py import_catalogue --confirm --if-needed --backup-r2   # au démarrage (Railway)

Supprime documents, matières, années académiques et types de documents, puis
recrée années, types, matières et documents. Les classes, enseignants et
profils ne sont pas touchés. Tout se fait dans une seule transaction.

Les tailles de fichier sont lues dans un seul listing du bucket R2 ; les clés
absentes du bucket sont signalées (le document est quand même créé).
"""
import csv
import io
from collections import Counter
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from core.models import AcademicYear, Class, Document, DocumentType, Subject
from core.r2 import get_r2_client, list_objects, r2_configured

DEFAULT_DIR = Path(settings.BASE_DIR) / 'data' / 'catalogue'
FALLBACK_TYPE = 'DOCUMENT'
# Année par défaut du catalogue (documents sans année, ou année hors liste)
FALLBACK_YEAR = '2025-2026'
PATH_COL = 'Chemin Cloudflare R2 (cle objet)'


def read_csv(path: Path):
    with open(path, encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


class Command(BaseCommand):
    help = "Vide et réimporte années, types, matières et documents depuis les CSV du catalogue."

    def add_arguments(self, parser):
        parser.add_argument('--dir', default=str(DEFAULT_DIR), help="Dossier contenant les CSV app-*.csv")
        parser.add_argument('--confirm', action='store_true', help="Obligatoire : la commande supprime des données.")
        parser.add_argument('--skip-r2', action='store_true', help="Ne pas lire le bucket R2 (tailles vides).")
        parser.add_argument('--if-needed', action='store_true',
                            help="Ne rien faire si la base contient déjà exactement les documents du CSV.")
        parser.add_argument('--backup-r2', action='store_true',
                            help="Sauvegarder l'ancien catalogue (dumpdata JSON) dans R2 sous _backups/ avant suppression.")

    def handle(self, *args, **opts):
        if not opts['confirm']:
            raise CommandError("Ajoutez --confirm : cette commande supprime documents, matières, années et types.")

        base = Path(opts['dir'])
        years = read_csv(base / 'app-annees-academiques.csv')
        types = read_csv(base / 'app-types-documents.csv')
        subjects = read_csv(base / 'app-matieres.csv')
        docs = read_csv(base / 'app-documents.csv')

        classes = {c.code: c for c in Class.objects.all()}
        missing = {r['Classe'] for r in subjects + docs} - set(classes)
        if missing:
            raise CommandError(f"Classes absentes de la base : {', '.join(sorted(missing))}")

        if opts['if_needed']:
            wanted = {r[PATH_COL] for r in docs}
            current = set(Document.objects.values_list('file_path', flat=True))
            if current == wanted and Subject.objects.count() == len(subjects):
                self.stdout.write("Catalogue déjà importé : rien à faire.")
                return

        if opts['backup_r2']:
            self._backup_to_r2()

        sizes = {} if opts['skip_r2'] or not r2_configured() else self._r2_sizes()

        with transaction.atomic():
            deleted = {
                'documents': Document.objects.all().delete()[0],
                'matières': Subject.objects.all().delete()[0],
                'années': AcademicYear.objects.all().delete()[0],
                'types': DocumentType.objects.all().delete()[0],
            }
            self.stdout.write(f"Supprimé (lignes, liens compris) : {deleted}")

            year_by_label = {}
            for r in years:
                y = AcademicYear.objects.create(
                    label=r['Libelle'], start_year=int(r['Annee debut']), end_year=int(r['Annee fin']),
                    is_active=r['Annee en cours'].strip().lower() == 'oui',
                )
                year_by_label[y.label] = y

            type_by_code = {}
            for r in types:
                t = DocumentType.objects.create(code=r['Code'], label=r['Libelle'], description=r['Description'])
                type_by_code[t.code] = t

            subject_by_code = {}
            for r in subjects:
                s = Subject.objects.create(
                    code=r['Code'], name=r['Nom'], description=r['Description'], class_id=classes[r['Classe']],
                )
                subject_by_code[s.code] = s

            to_create, absent, year_fixed = [], [], []
            for r in docs:
                key = r[PATH_COL]
                is_folder = r['_projet'].strip().lower() == 'oui' or key.endswith('/')
                if sizes:
                    size = (sum(v for k, v in sizes.items() if k.startswith(key)) if is_folder
                            else sizes.get(key))
                    if not size and size != 0:
                        absent.append(key)
                else:
                    size = None
                year = year_by_label.get(r['Annee academique'])
                if year is None:
                    year = year_by_label[FALLBACK_YEAR]
                    year_fixed.append(f"{key} ({r['Annee academique']})")
                to_create.append(Document(
                    title=r['Titre'][:255],
                    description=r['Description'] or None,
                    file_name=r['Nom du fichier'].rstrip('/') if is_folder else r['Nom du fichier'],
                    file_path=key,
                    bucket_name=settings.CF_R2_BUCKET_NAME,
                    mime_type=r['Type MIME'] or None,
                    file_size=size,
                    class_id=classes[r['Classe']],
                    subject_id=subject_by_code[r['_code_matiere']],
                    academic_year_id=year,
                    document_type_id=type_by_code[r['_code_type'] or FALLBACK_TYPE],
                    status='published',
                    is_published=True,
                    is_folder=is_folder,
                ))
            Document.objects.bulk_create(to_create, batch_size=500)

        per_class = Counter(r['Classe'] for r in docs)
        self.stdout.write(self.style.SUCCESS(
            f"Importé : {len(years)} années, {len(types)} types, {len(subjects)} matières, "
            f"{len(to_create)} documents {dict(per_class)}"
        ))
        if year_fixed:
            self.stdout.write(self.style.WARNING(
                f"{len(year_fixed)} document(s) avec une année hors liste, rattachés à {FALLBACK_YEAR} :"))
            for line in year_fixed:
                self.stdout.write(f"  - {line}")
        if sizes:
            if absent:
                self.stdout.write(self.style.WARNING(f"{len(absent)} clé(s) absente(s) du bucket R2 :"))
                for key in absent[:50]:
                    self.stdout.write(f"  - {key}")
            else:
                self.stdout.write(self.style.SUCCESS("Toutes les clés existent dans le bucket R2."))

    def _backup_to_r2(self):
        if not r2_configured():
            raise CommandError("--backup-r2 demandé mais R2 n'est pas configuré : import annulé.")
        out = io.StringIO()
        call_command('dumpdata', 'core.document', 'core.subject', 'core.academicyear', 'core.documenttype',
                     indent=1, stdout=out)
        key = f"_backups/catalogue-{timezone.now():%Y%m%d-%H%M%S}.json"
        get_r2_client().put_object(
            Bucket=settings.CF_R2_BUCKET_NAME, Key=key, Body=out.getvalue().encode('utf-8'),
            ContentType='application/json',
        )
        self.stdout.write(f"Sauvegarde de l'ancien catalogue : R2 {key}")

    def _r2_sizes(self):
        self.stdout.write("Lecture du bucket R2…")
        sizes = dict(list_objects())
        self.stdout.write(f"{len(sizes)} objets dans le bucket.")
        return sizes
