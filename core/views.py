"""
core/views.py
"""
import uuid
from difflib import get_close_matches

from django.conf import settings
from django.core.cache import cache
from django.contrib.auth.models import User
from django.db.models import Q
from django.http import HttpResponseRedirect
from django.utils import timezone
from rest_framework import viewsets, status
from rest_framework.decorators import api_view, permission_classes, action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from .indexing import can_thumbnail, index_document
from .models import Class, Profile, Subject, AcademicYear, DocumentType, Document, Teacher, DocumentPage
from .r2 import generate_presigned_url, get_r2_client, list_objects, r2_configured
from .search import page_lines, parse_query, search_fulltext
from .serializers import (
    ClassSerializer, ProfileSerializer, SubjectSerializer,
    AcademicYearSerializer, DocumentTypeSerializer, DocumentSerializer, TeacherSerializer
)
from .text import normalize_text


# ── Helpers recherche ────────────────────────────────────────────────────────

def expand_query_terms(search):
    aliases = {
        "proba": ["probabilite"], "math": ["mathematiques", "mathematique"],
        "stat": ["statistique", "statistiques"], "td": ["travaux diriges"],
        "tp": ["travaux pratiques"], "corrige": ["corrige", "correction"],
        "exam": ["examen", "epreuve"], "devoir": ["devoir", "interrogation"],
    }
    normalized = normalize_text(search)
    terms = normalized.split()
    expanded = set()
    for t in terms:
        expanded.add(t)
        if t in aliases:
            expanded.update(normalize_text(x) for x in aliases[t])
    return list(expanded)


def tokenize_query(search):
    if not search: return []
    return [normalize_text(t) for t in search.split() if t.strip()]


VOCAB_CACHE_KEY = 'gbaki:vocab'


def collect_vocab():
    """Vocabulaire des métadonnées (titres, matières, types, classes, enseignants), en cache 10 min."""
    vocab = cache.get(VOCAB_CACHE_KEY)
    if vocab is not None:
        return vocab
    texts = []
    texts += Document.objects.filter(is_published=True).values_list('title', flat=True)
    texts += Subject.objects.values_list('name', flat=True)
    texts += DocumentType.objects.values_list('label', flat=True)
    texts += Class.objects.values_list('label', flat=True)
    texts += Teacher.objects.values_list('full_name', flat=True)
    vocab = sorted({tok for v in texts for tok in normalize_text(v).split() if len(tok) >= 3})
    cache.set(VOCAB_CACHE_KEY, vocab, 600)
    return vocab


def get_suggestions(search, vocab, n=5):
    tokens = tokenize_query(search)
    suggestions = []
    for tok in tokens:
        for item in get_close_matches(tok, vocab, n=n, cutoff=0.72):
            if item not in suggestions: suggestions.append(item)
    return suggestions[:n]


# ── Upload PDF vers R2 ───────────────────────────────────────────────────────

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def upload_document(request):
    """
    POST /api/documents/upload/
    Reçoit le fichier PDF + métadonnées, l'envoie vers Cloudflare R2,
    puis crée l'entrée Document en base de données.

    Body (multipart/form-data) :
      - file              : fichier PDF (obligatoire)
      - title             : str (obligatoire)
      - class_id          : UUID (obligatoire)
      - subject_id        : UUID (obligatoire)
      - academic_year_id  : UUID (obligatoire)
      - document_type_id  : UUID (obligatoire)
      - teacher_ids       : liste d'UUIDs, ex: teacher_ids=uuid1&teacher_ids=uuid2 (optionnel)
      - description       : str (optionnel)
      - status            : 'draft' | 'published' (optionnel, défaut: 'draft')
      - is_published      : bool (optionnel, défaut: false)

    Réponse 201 : objet Document complet sérialisé.
    """
    # ── 1. Récupérer le fichier ──────────────────────────────────────────────
    file = request.FILES.get('file')
    if not file:
        return Response({'error': 'Fichier manquant (champ "file" requis).'}, status=400)

    # ── 2. Valider les champs obligatoires ───────────────────────────────────
    required_fields = ['title', 'class_id', 'subject_id', 'academic_year_id', 'document_type_id']
    for field in required_fields:
        if not request.data.get(field):
            return Response({'error': f'Le champ "{field}" est requis.'}, status=400)

    class_id    = request.data['class_id']
    teacher_ids = request.data.getlist('teacher_ids', [])

    # ── 3. Construire le chemin R2 ───────────────────────────────────────────
    # Structure : documents/{class_id}/{uid8}_{nom_fichier_original}
    # Exemple   : documents/uuid-L1/a3f9b2c1_cours_proba.pdf
    original_name = file.name
    short_uid     = str(uuid.uuid4()).replace('-', '')[:8]
    file_path     = f"documents/{class_id}/{short_uid}_{original_name}"

    # ── 4. Upload vers Cloudflare R2 ─────────────────────────────────────────
    if not r2_configured():
        return Response(
            {'error': 'Cloudflare R2 non configuré. Vérifie CF_R2_ENDPOINT_URL et CF_R2_ACCESS_KEY dans .env.'},
            status=500
        )

    try:
        r2 = get_r2_client()
        r2.upload_fileobj(
            file,
            settings.CF_R2_BUCKET_NAME,
            file_path,
            ExtraArgs={'ContentType': file.content_type or 'application/pdf'}
        )
    except Exception as e:
        return Response({'error': f'Erreur upload R2 : {str(e)}'}, status=500)

    # ── 5. Créer le Document en base ─────────────────────────────────────────
    # Résoudre le Profile de l'utilisateur connecté
    uploaded_by = None
    try:
        uploaded_by = Profile.objects.get(email=request.user.email)
    except Profile.DoesNotExist:
        pass  # uploaded_by reste None, ce qui est autorisé (SET_NULL)

    try:
        doc = Document.objects.create(
            title               = request.data['title'],
            description         = request.data.get('description', ''),
            file_name           = original_name,
            file_path           = file_path,
            bucket_name         = settings.CF_R2_BUCKET_NAME,
            mime_type           = file.content_type,
            file_size           = file.size,
            class_id_id         = class_id,
            subject_id_id       = request.data['subject_id'],
            academic_year_id_id = request.data['academic_year_id'],
            document_type_id_id = request.data['document_type_id'],
            uploaded_by         = uploaded_by,
            status              = request.data.get('status', 'draft'),
            is_published        = str(request.data.get('is_published', 'false')).lower() in ['true', '1', 'yes'],
        )
        if teacher_ids:
            doc.teachers.set(teacher_ids)
    except Exception as e:
        # Si la création en base échoue, supprimer le fichier déjà uploadé sur R2
        try:
            r2 = get_r2_client()
            r2.delete_object(Bucket=settings.CF_R2_BUCKET_NAME, Key=file_path)
        except Exception:
            pass
        return Response({'error': f'Erreur base de données : {str(e)}'}, status=500)

    return Response(DocumentSerializer(doc).data, status=201)


# ── ViewSets ─────────────────────────────────────────────────────────────────

class ClassViewSet(viewsets.ModelViewSet):
    queryset = Class.objects.all().order_by('level_order', 'label')
    serializer_class = ClassSerializer


def is_admin_user(user):
    return bool(user and user.is_authenticated and (user.is_staff or user.is_superuser))


class ProfileViewSet(viewsets.ModelViewSet):
    """Les admins voient tous les profils ; un étudiant ne voit et ne modifie que le sien."""
    queryset = Profile.objects.all().order_by('-created_at')
    serializer_class = ProfileSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = super().get_queryset()
        if is_admin_user(self.request.user):
            return qs
        email = (self.request.user.email or self.request.user.username).strip()
        return qs.filter(email__iexact=email)

    def create(self, request, *args, **kwargs):
        if not is_admin_user(request.user):
            return Response({'error': 'Réservé aux administrateurs.'}, status=status.HTTP_403_FORBIDDEN)
        return super().create(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        """Supprime le profil ET les comptes de connexion de cet email, pour libérer l'adresse."""
        if not is_admin_user(request.user):
            return Response({'error': 'Réservé aux administrateurs.'}, status=status.HTTP_403_FORBIDDEN)
        profile = self.get_object()
        if profile.email.lower() == (request.user.email or '').lower():
            return Response({'error': 'Impossible de supprimer ton propre compte.'}, status=status.HTTP_400_BAD_REQUEST)
        User.objects.filter(Q(email__iexact=profile.email) | Q(username__iexact=profile.email)).delete()
        profile.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class SubjectViewSet(viewsets.ModelViewSet):
    queryset = Subject.objects.all().order_by('name')
    serializer_class = SubjectSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        class_id = self.request.query_params.get('class_id')
        if class_id: qs = qs.filter(class_id=class_id)
        return qs


class AcademicYearViewSet(viewsets.ModelViewSet):
    queryset = AcademicYear.objects.all().order_by('-start_year')
    serializer_class = AcademicYearSerializer


class DocumentTypeViewSet(viewsets.ModelViewSet):
    queryset = DocumentType.objects.all().order_by('label')
    serializer_class = DocumentTypeSerializer


class TeacherViewSet(viewsets.ModelViewSet):
    queryset = Teacher.objects.all().order_by('full_name')
    serializer_class = TeacherSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        q = self.request.query_params.get('q', '').strip()
        if q:
            qs = qs.filter(
                Q(full_name__icontains=q) | Q(email__icontains=q) | Q(department__icontains=q)
            )
        return qs


DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200


def _positive_int(value, default, maximum=None):
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default
    if n < 1:
        return default
    return min(n, maximum) if maximum else n


class DocumentViewSet(viewsets.ModelViewSet):
    queryset = Document.objects.all().select_related(
        'class_id', 'subject_id', 'academic_year_id', 'document_type_id', 'uploaded_by',
    ).prefetch_related('teachers')
    serializer_class = DocumentSerializer

    def get_queryset(self):
        p = self.request.query_params
        ordering = {
            'title': ('title',), '-title': ('-title',),
            'year': ('-academic_year_id__start_year', 'title'),
        }.get(p.get('ordering'), ('-created_at', 'title'))
        qs = super().get_queryset().order_by(*ordering)

        if p.get('class_id'):          qs = qs.filter(class_id=p['class_id'])
        if p.get('class_code'):        qs = qs.filter(class_id__code=p['class_code'])
        if p.get('title'):             qs = qs.filter(title__icontains=p['title'])
        if p.get('subject_id'):        qs = qs.filter(subject_id=p['subject_id'])
        if p.get('academic_year_id'):  qs = qs.filter(academic_year_id=p['academic_year_id'])
        if p.get('document_type_id'):  qs = qs.filter(document_type_id=p['document_type_id'])
        if p.get('uploaded_by'):       qs = qs.filter(uploaded_by=p['uploaded_by'])
        if p.get('status'):            qs = qs.filter(status=p['status'])
        if p.get('teacher_id'):        qs = qs.filter(teachers__id=p['teacher_id'])

        is_pub = p.get('is_published')
        if is_pub is not None:
            qs = qs.filter(is_published=is_pub.lower() in ['true', '1', 'yes'])

        search = p.get('search')
        if search:
            tokens = []
            for term in expand_query_terms(search):
                tokens.extend(tokenize_query(term))
            tokens = list(dict.fromkeys(tokens))
            q = Q()
            for tok in tokens:
                q |= Q(title__icontains=tok)
                q |= Q(description__icontains=tok)
                q |= Q(teachers__full_name__icontains=tok)
                q |= Q(subject_id__name__icontains=tok)
                q |= Q(subject_id__code__icontains=tok)
                q |= Q(class_id__label__icontains=tok)
                q |= Q(class_id__code__icontains=tok)
                q |= Q(document_type_id__label__icontains=tok)
                q |= Q(academic_year_id__label__icontains=tok)
            qs = qs.filter(q)

        return qs.distinct()

    def list(self, request, *args, **kwargs):
        """
        Liste paginée : ?page=1&page_size=50 (max 200).
        Réponse : {count, page, page_size, num_pages, results[, suggestions]}
        """
        qs = self.get_queryset()
        page_size = _positive_int(request.query_params.get('page_size'), DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE)
        count = qs.count()
        num_pages = max(1, -(-count // page_size))
        page = min(_positive_int(request.query_params.get('page'), 1), num_pages)
        items = qs[(page - 1) * page_size: page * page_size]
        serializer = self.get_serializer(items, many=True)
        data = {
            'count': count, 'page': page, 'page_size': page_size, 'num_pages': num_pages,
            'results': serializer.data,
        }
        search = request.query_params.get('search')
        if search and count == 0:
            suggestions = get_suggestions(search, collect_vocab())
            if suggestions: data['suggestions'] = suggestions
        return Response(data)

    def create(self, request, *args, **kwargs):
        """
        POST /api/documents/ — crée un Document sans fichier (métadonnées seules).
        Pour uploader un PDF vers R2, utilise POST /api/documents/upload/
        """
        teacher_ids = request.data.get('teacher_ids', [])
        try:
            doc = Document.objects.create(
                title               = request.data['title'],
                description         = request.data.get('description', ''),
                file_name           = request.data['file_name'],
                file_path           = request.data['file_path'],
                bucket_name         = request.data.get('bucket_name', settings.CF_R2_BUCKET_NAME),
                mime_type           = request.data.get('mime_type'),
                file_size           = request.data.get('file_size'),
                class_id_id         = request.data['class_id'],
                subject_id_id       = request.data['subject_id'],
                academic_year_id_id = request.data['academic_year_id'],
                document_type_id_id = request.data['document_type_id'],
                status              = request.data.get('status', 'draft'),
                is_published        = request.data.get('is_published', False),
            )
            if teacher_ids:
                doc.teachers.set(teacher_ids)
            return Response(DocumentSerializer(doc).data, status=status.HTTP_201_CREATED)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    def update(self, request, *args, **kwargs):
        teacher_ids = request.data.get('teacher_ids', None)
        instance = self.get_object()
        fields = ['title', 'description', 'file_name', 'file_path', 'mime_type',
                  'file_size', 'status', 'is_published']
        for f in fields:
            if f in request.data:
                setattr(instance, f, request.data[f])
        for fk in [('class_id', 'class_id_id'), ('subject_id', 'subject_id_id'),
                   ('academic_year_id', 'academic_year_id_id'), ('document_type_id', 'document_type_id_id')]:
            if fk[0] in request.data:
                setattr(instance, fk[1], request.data[fk[0]])
        instance.save()
        if teacher_ids is not None:
            instance.teachers.set(teacher_ids)
        return Response(DocumentSerializer(instance).data)

    @action(detail=True, methods=['get'], permission_classes=[IsAuthenticated],
            url_path='download')
    def download(self, request, pk=None):
        """
        GET /api/documents/{id}/download/?mode=preview|download
        Retourne une URL signée Cloudflare R2.
          mode=preview  → affichage inline dans le navigateur (défaut)
          mode=download → force le téléchargement (Content-Disposition: attachment)
        """
        doc = self.get_object()
        mode = request.query_params.get('mode', 'preview')
        force_dl = (mode == 'download')
        try:
            url = generate_presigned_url(doc.file_path, doc.file_name, force_download=force_dl)
            return Response({'url': url, 'file_name': doc.file_name, 'mime_type': doc.mime_type})
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['get'], permission_classes=[AllowAny], url_path='thumbnail')
    def thumbnail(self, request, pk=None):
        """
        GET /api/documents/{id}/thumbnail/
        Redirige vers l'image de la 1re page (URL signée R2). Public pour être utilisable
        dans une balise <img>, limité aux documents publiés. Générée à la volée si absente.
        """
        doc = self.get_object()
        if not doc.is_published and not is_admin_user(request.user):
            return Response({'error': 'Document non publié.'}, status=status.HTTP_404_NOT_FOUND)
        if not doc.thumbnail_key and can_thumbnail(doc) and r2_configured():
            index_document(doc, with_text=False)
        if not doc.thumbnail_key:
            return Response({'error': "Pas d'aperçu pour ce type de fichier."}, status=status.HTTP_404_NOT_FOUND)
        response = HttpResponseRedirect(generate_presigned_url(doc.thumbnail_key))
        response['Cache-Control'] = 'private, max-age=1800'
        return response

    @action(detail=True, methods=['get'], permission_classes=[IsAuthenticated], url_path='files')
    def files(self, request, pk=None):
        """
        GET /api/documents/{id}/files/
        Contenu d'un dossier-projet : [{name, path, size, url}] (URLs signées de téléchargement).
        """
        doc = self.get_object()
        if not doc.is_folder:
            return Response({'error': "Ce document n'est pas un dossier."}, status=status.HTTP_400_BAD_REQUEST)
        if not r2_configured():
            return Response({'count': 0, 'files': []})
        prefix = doc.file_path if doc.file_path.endswith('/') else doc.file_path + '/'
        files = []
        for key, size in list_objects(prefix):
            name = key[len(prefix):]
            if not name:
                continue
            files.append({
                'name': name, 'path': key, 'size': size,
                'url': generate_presigned_url(key, name.rsplit('/', 1)[-1], force_download=True),
            })
        return Response({'count': len(files), 'files': files})

    @action(detail=True, methods=['get'], permission_classes=[IsAuthenticated], url_path='page')
    def page_text(self, request, pk=None):
        """
        GET /api/documents/{id}/page/?n=3&q=intervalle
        Texte indexé d'une page, ligne par ligne, avec les plages à surligner pour q.
        """
        doc = self.get_object()
        n = _positive_int(request.query_params.get('n'), 1)
        page = DocumentPage.objects.filter(document=doc, page_number=n).first()
        q = request.query_params.get('q', '').strip()
        return Response({
            'document_id': str(doc.id), 'page': n, 'page_count': doc.page_count,
            'lines': page_lines(page.content, parse_query(q) if q else None) if page else [],
        })


# ── Recherche plein texte ─────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def fulltext_search(request):
    """
    GET /api/search/fulltext/?q=intervalle de confiance&class_id=<uuid>
    Passages trouvés dans le texte des documents : page, ligne, exacte / proche.
    """
    q = request.query_params.get('q', '').strip()
    if len(q) < 2:
        return Response({'error': 'Requête trop courte (2 caractères minimum).'}, status=status.HTTP_400_BAD_REQUEST)
    return Response(search_fulltext(q[:200], class_id=request.query_params.get('class_id') or None))


# ── Notifications ─────────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([AllowAny])
def notifications_today(request):
    """GET /api/notifications/today/ — nombre de documents publiés aujourd'hui."""
    today = timezone.localdate()
    count = Document.objects.filter(is_published=True, created_at__date=today).count()
    return Response({'count': count, 'date': today.isoformat()})


# ── Autocomplete teachers ─────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def autocomplete_teachers(request):
    """GET /api/autocomplete/teachers/?q=dupont"""
    q = request.query_params.get('q', '').strip()
    if len(q) < 2:
        return Response([])
    teachers = Teacher.objects.filter(
        Q(full_name__icontains=q) | Q(email__icontains=q)
    )[:10]
    return Response(TeacherSerializer(teachers, many=True).data)


# ── Autocomplete documents (search suggestions) ───────────────────────────────

@api_view(['GET'])
@permission_classes([AllowAny])
def autocomplete_documents(request):
    """GET /api/autocomplete/documents/?q=probab"""
    q = request.query_params.get('q', '').strip()
    if len(q) < 2:
        return Response({'suggestions': []})
    suggestions = get_suggestions(q, collect_vocab())
    return Response({'suggestions': suggestions})
