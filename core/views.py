"""
core/views.py
"""
import os
import uuid
import unicodedata
import boto3
from botocore.config import Config
from difflib import get_close_matches
from django.conf import settings
from django.db.models import Q
from rest_framework import viewsets, status
from rest_framework.decorators import api_view, permission_classes, action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from .models import Class, Profile, Subject, AcademicYear, DocumentType, Document, Teacher
from .serializers import (
    ClassSerializer, ProfileSerializer, SubjectSerializer,
    AcademicYearSerializer, DocumentTypeSerializer, DocumentSerializer, TeacherSerializer
)


# ── Helpers recherche ────────────────────────────────────────────────────────

def normalize_text(text):
    if not text: return ""
    text = text.lower().strip()
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return text


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


def collect_vocab(queryset):
    vocab = set()
    for doc in queryset.select_related("subject_id", "class_id", "document_type_id").prefetch_related("teachers"):
        fields = [
            doc.title, doc.description or "",
            " ".join(t.full_name for t in doc.teachers.all()),
            doc.subject_id.name if doc.subject_id else "",
            doc.class_id.label if doc.class_id else "",
            doc.class_id.code if doc.class_id else "",
            doc.document_type_id.label if doc.document_type_id else "",
        ]
        for v in fields:
            for tok in normalize_text(v).split():
                if len(tok) >= 3: vocab.add(tok)
    return sorted(vocab)


def get_suggestions(search, vocab, n=5):
    tokens = tokenize_query(search)
    suggestions = []
    for tok in tokens:
        for item in get_close_matches(tok, vocab, n=n, cutoff=0.72):
            if item not in suggestions: suggestions.append(item)
    return suggestions[:n]


# ── Cloudflare R2 helpers ────────────────────────────────────────────────────

def get_r2_client():
    return boto3.client(
        "s3",
        endpoint_url=settings.CF_R2_ENDPOINT_URL,
        aws_access_key_id=settings.CF_R2_ACCESS_KEY,
        aws_secret_access_key=settings.CF_R2_SECRET_KEY,
        config=Config(signature_version="s3v4"),
        region_name="auto",
    )


def generate_presigned_url(file_path: str, file_name: str, force_download: bool = False) -> str:
    """
    Retourne une URL signée R2 valable CF_R2_PRESIGN_EXPIRY secondes.
    Si les credentials R2 ne sont pas configurés, retourne file_path directement.
    """
    if not settings.CF_R2_ENDPOINT_URL or not settings.CF_R2_ACCESS_KEY:
        return file_path

    params = {
        "Bucket": settings.CF_R2_BUCKET_NAME,
        "Key": file_path,
    }
    if force_download:
        params["ResponseContentDisposition"] = f'attachment; filename="{file_name}"'

    client = get_r2_client()
    return client.generate_presigned_url(
        "get_object",
        Params=params,
        ExpiresIn=settings.CF_R2_PRESIGN_EXPIRY,
    )


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
    if not settings.CF_R2_ENDPOINT_URL or not settings.CF_R2_ACCESS_KEY:
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


class ProfileViewSet(viewsets.ModelViewSet):
    queryset = Profile.objects.all().order_by('-created_at')
    serializer_class = ProfileSerializer


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


class DocumentViewSet(viewsets.ModelViewSet):
    queryset = Document.objects.all().prefetch_related('teachers')
    serializer_class = DocumentSerializer

    def get_queryset(self):
        qs = super().get_queryset().order_by('-created_at')
        p = self.request.query_params

        if p.get('class_id'):          qs = qs.filter(class_id=p['class_id'])
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
        qs = self.get_queryset()
        serializer = self.get_serializer(qs, many=True)
        data = {'count': len(serializer.data), 'results': serializer.data}
        search = request.query_params.get('search')
        if search and len(serializer.data) == 0:
            vocab = collect_vocab(Document.objects.all())
            suggestions = get_suggestions(search, vocab)
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
    vocab = collect_vocab(Document.objects.filter(is_published=True))
    suggestions = get_suggestions(q, vocab)
    return Response({'suggestions': suggestions})