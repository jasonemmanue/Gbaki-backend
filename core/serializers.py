from rest_framework import serializers
from .models import Class, Profile, Subject, AcademicYear, DocumentType, Document


class ClassSerializer(serializers.ModelSerializer):
    class Meta:
        model = Class
        fields = '__all__'


class ProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = Profile
        fields = '__all__'


class SubjectSerializer(serializers.ModelSerializer):
    class Meta:
        model = Subject
        fields = '__all__'


class AcademicYearSerializer(serializers.ModelSerializer):
    class Meta:
        model = AcademicYear
        fields = '__all__'


class DocumentTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = DocumentType
        fields = '__all__'


class DocumentSerializer(serializers.ModelSerializer):
    teachers = serializers.SerializerMethodField()
    class_info = serializers.SerializerMethodField()
    subject = serializers.SerializerMethodField()
    document_type = serializers.SerializerMethodField()
    academic_year = serializers.SerializerMethodField()
    uploaded_by = serializers.SerializerMethodField()
    clickable_link = serializers.SerializerMethodField()
    previewable = serializers.SerializerMethodField()
    badges = serializers.SerializerMethodField()

    class Meta:
        model = Document
        fields = [
            'id',
            'title',
            'description',
            'file_name',
            'clickable_link',
            'mime_type',
            'file_size',

            'class_info',
            'subject',
            'document_type',
            'academic_year',

            'uploaded_by',
            'teachers',

            'status',
            'is_published',
            'created_at',
            'updated_at',
            'previewable',
            'badges',
        ]

    def get_class_info(self, obj):
        if not obj.class_id:
            return None
        return {
            "code": obj.class_id.code,
            "label": obj.class_id.label,
        }

    def get_subject(self, obj):
        return obj.subject_id.name if obj.subject_id else None

    def get_document_type(self, obj):
        return obj.document_type_id.label if obj.document_type_id else None

    def get_academic_year(self, obj):
        return obj.academic_year_id.label if obj.academic_year_id else None

    def get_uploaded_by(self, obj):
        if not obj.uploaded_by:
            return None
        return obj.uploaded_by.full_name or obj.uploaded_by.email

    def get_teachers(self, obj):
        return [
            {
                "name": p.full_name or p.email,
                "email": p.email
            }
            for p in obj.teachers.all()
        ]

    def get_clickable_link(self, obj):
        return obj.file_path if obj.file_path else None

    def get_previewable(self, obj):
        if not obj.mime_type:
            return False

        previewable_types = {
            "application/pdf",
            "image/png",
            "image/jpeg",
            "image/webp",
            "text/plain",
        }
        return obj.mime_type in previewable_types

    def get_badges(self, obj):
        badges = []

        # Type MIME simplifié
        if obj.mime_type:
            mime_map = {
                "application/pdf": "PDF",
                "image/png": "PNG",
                "image/jpeg": "JPG",
                "image/jpg": "JPG",
                "image/webp": "WEBP",
                "text/plain": "TXT",
            }
            badges.append(mime_map.get(obj.mime_type, obj.mime_type.upper()))

        # Classe
        if obj.class_id and obj.class_id.code:
            badges.append(obj.class_id.code)

        # Type de document
        if obj.document_type_id and obj.document_type_id.label:
            badges.append(obj.document_type_id.label)

        # Matière
        if obj.subject_id and obj.subject_id.name:
            badges.append(obj.subject_id.name)

        # Statut publication
        if obj.is_published:
            badges.append("Publié")
        else:
            badges.append("Brouillon")

        # Statut métier
        if obj.status:
            badges.append(obj.status.capitalize())

        return badges
