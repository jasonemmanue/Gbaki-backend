from rest_framework import viewsets
from rest_framework.response import Response
from django.db.models import Q
from difflib import get_close_matches
import unicodedata

from .models import Class, Profile, Subject, AcademicYear, DocumentType, Document
from .serializers import (
    ClassSerializer, ProfileSerializer, SubjectSerializer,
    AcademicYearSerializer, DocumentTypeSerializer, DocumentSerializer
)


def normalize_text(text):
    if not text:
        return ""
    text = text.lower().strip()
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return text


def expand_query_terms(search):
    aliases = {
        "proba": ["probabilite", "probabilité"],
        "math": ["mathematiques", "mathématiques", "mathematique"],
        "stat": ["statistique", "statistiques"],
        "td": ["travaux diriges", "travaux dirigés", "td"],
        "tp": ["travaux pratiques", "tp"],
        "corrige": ["corrige", "corrigé", "correction"],
        "cours": ["cours"],
        "exam": ["examen", "exam", "epreuve", "épreuve"],
        "devoir": ["devoir", "interro", "interrogation"],
    }

    normalized = normalize_text(search)
    terms = normalized.split()
    expanded_terms = set()

    for term in terms:
        expanded_terms.add(term)
        if term in aliases:
            expanded_terms.update(normalize_text(x) for x in aliases[term])

    return list(expanded_terms)


def tokenize_query(search):
    if not search:
        return []
    return [normalize_text(t) for t in search.split() if t.strip()]


def collect_search_vocabulary(queryset):
    vocab = set()

    docs = queryset.select_related(
        "subject_id", "class_id", "document_type_id", "academic_year_id"
    ).prefetch_related("teachers")

    for doc in docs:
        teacher_names = " ".join([p.full_name or "" for p in doc.teachers.all()])
        teacher_emails = " ".join([p.email or "" for p in doc.teachers.all()])

        fields = [
            doc.title,
            doc.description,
            teacher_names,
            teacher_emails,
            doc.subject_id.name if doc.subject_id else "",
            doc.subject_id.code if doc.subject_id else "",
            doc.class_id.label if doc.class_id else "",
            doc.class_id.code if doc.class_id else "",
            doc.document_type_id.label if doc.document_type_id else "",
            doc.academic_year_id.label if doc.academic_year_id else "",
        ]

        for value in fields:
            if value:
                for token in normalize_text(value).split():
                    if len(token) >= 3:
                        vocab.add(token)

    return sorted(vocab)


def get_spelling_suggestions(search, vocabulary, max_suggestions=5):
    normalized_tokens = tokenize_query(search)
    suggestions = []

    for token in normalized_tokens:
        close = get_close_matches(token, vocabulary, n=max_suggestions, cutoff=0.72)
        for item in close:
            if item not in suggestions:
                suggestions.append(item)

    return suggestions[:max_suggestions]


class ClassViewSet(viewsets.ModelViewSet):
    queryset = Class.objects.all()
    serializer_class = ClassSerializer


class ProfileViewSet(viewsets.ModelViewSet):
    queryset = Profile.objects.all()
    serializer_class = ProfileSerializer


class SubjectViewSet(viewsets.ModelViewSet):
    queryset = Subject.objects.all()
    serializer_class = SubjectSerializer


class AcademicYearViewSet(viewsets.ModelViewSet):
    queryset = AcademicYear.objects.all()
    serializer_class = AcademicYearSerializer


class DocumentTypeViewSet(viewsets.ModelViewSet):
    queryset = DocumentType.objects.all()
    serializer_class = DocumentTypeSerializer


class DocumentViewSet(viewsets.ModelViewSet):
    queryset = Document.objects.all().prefetch_related("teachers")
    serializer_class = DocumentSerializer

    def get_queryset(self):
        queryset = super().get_queryset().order_by("-created_at")

        teacher_id = self.request.query_params.get("teacher")
        class_id = self.request.query_params.get("class_id")
        subject_id = self.request.query_params.get("subject_id")
        academic_year_id = self.request.query_params.get("academic_year_id")
        document_type_id = self.request.query_params.get("document_type_id")
        uploaded_by = self.request.query_params.get("uploaded_by")
        status = self.request.query_params.get("status")
        is_published = self.request.query_params.get("is_published")
        search = self.request.query_params.get("search")

        if teacher_id:
            queryset = queryset.filter(teachers=teacher_id)

        if class_id:
            queryset = queryset.filter(class_id=class_id)

        if subject_id:
            queryset = queryset.filter(subject_id=subject_id)

        if academic_year_id:
            queryset = queryset.filter(academic_year_id=academic_year_id)

        if document_type_id:
            queryset = queryset.filter(document_type_id=document_type_id)

        if uploaded_by:
            queryset = queryset.filter(uploaded_by=uploaded_by)

        if status:
            queryset = queryset.filter(status=status)

        if is_published is not None:
            val = is_published.lower()
            if val in ["true", "1", "yes"]:
                queryset = queryset.filter(is_published=True)
            elif val in ["false", "0", "no"]:
                queryset = queryset.filter(is_published=False)

        if search:
            expanded_terms = expand_query_terms(search)
            tokens = []
            for term in expanded_terms:
                tokens.extend(tokenize_query(term))

            tokens = list(dict.fromkeys(tokens))

            query = Q()
            for token in tokens:
                query |= Q(title__icontains=token)
                query |= Q(description__icontains=token)
                query |= Q(teachers__full_name__icontains=token)
                query |= Q(teachers__email__icontains=token)
                query |= Q(subject_id__name__icontains=token)
                query |= Q(subject_id__code__icontains=token)
                query |= Q(class_id__label__icontains=token)
                query |= Q(class_id__code__icontains=token)
                query |= Q(document_type_id__label__icontains=token)
                query |= Q(academic_year_id__label__icontains=token)

            queryset = queryset.filter(query)

        return queryset.distinct()

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        search = request.query_params.get("search")

        serializer = self.get_serializer(queryset, many=True)

        response_data = {
            "count": len(serializer.data),
            "results": serializer.data
        }

        if search and len(serializer.data) == 0:
            base_queryset = Document.objects.all()
            vocabulary = collect_search_vocabulary(base_queryset)
            suggestions = get_spelling_suggestions(search, vocabulary)

            if suggestions:
                response_data["suggestions"] = suggestions

        return Response(response_data)