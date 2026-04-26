from rest_framework import serializers
from .models import Class, Profile, Subject, AcademicYear, DocumentType, Document, Teacher


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


class TeacherSerializer(serializers.ModelSerializer):
    class Meta:
        model = Teacher
        fields = '__all__'


class DocumentSerializer(serializers.ModelSerializer):
    teachers      = serializers.SerializerMethodField()
    class_info    = serializers.SerializerMethodField()
    subject       = serializers.SerializerMethodField()
    subject_id_val= serializers.SerializerMethodField()
    document_type = serializers.SerializerMethodField()
    academic_year = serializers.SerializerMethodField()
    uploaded_by   = serializers.SerializerMethodField()
    clickable_link= serializers.SerializerMethodField()
    previewable   = serializers.SerializerMethodField()
    badges        = serializers.SerializerMethodField()

    class Meta:
        model = Document
        fields = [
            'id', 'title', 'description', 'file_name',
            'clickable_link', 'mime_type', 'file_size',
            'class_info', 'subject', 'subject_id_val',
            'document_type', 'academic_year',
            'uploaded_by', 'teachers',
            'status', 'is_published',
            'created_at', 'updated_at',
            'previewable', 'badges',
            # FK ids pour l'admin
            'class_id', 'subject_id', 'academic_year_id', 'document_type_id',
        ]

    def get_class_info(self, obj):
        if not obj.class_id: return None
        return {'code': obj.class_id.code, 'label': obj.class_id.label, 'id': str(obj.class_id.id)}

    def get_subject(self, obj):
        return obj.subject_id.name if obj.subject_id else None

    def get_subject_id_val(self, obj):
        return str(obj.subject_id.id) if obj.subject_id else None

    def get_document_type(self, obj):
        return obj.document_type_id.label if obj.document_type_id else None

    def get_academic_year(self, obj):
        return obj.academic_year_id.label if obj.academic_year_id else None

    def get_uploaded_by(self, obj):
        if not obj.uploaded_by: return None
        return obj.uploaded_by.full_name or obj.uploaded_by.email

    def get_teachers(self, obj):
        return [
            {'id': str(t.id), 'name': t.full_name, 'email': t.email or '', 'department': t.department or ''}
            for t in obj.teachers.all()
        ]

    def get_clickable_link(self, obj):
        # Retourne le chemin brut — le frontend appelle /api/documents/{id}/download/
        return obj.file_path if obj.file_path else None

    def get_previewable(self, obj):
        if not obj.mime_type: return False
        return obj.mime_type in {
            'application/pdf', 'image/png', 'image/jpeg',
            'image/webp', 'image/gif', 'text/plain',
        }

    def get_badges(self, obj):
        badges = []
        if obj.mime_type:
            mime_map = {
                'application/pdf': 'PDF', 'image/png': 'PNG',
                'image/jpeg': 'JPG', 'image/webp': 'WEBP', 'text/plain': 'TXT',
            }
            badges.append(mime_map.get(obj.mime_type, obj.mime_type.upper()))
        if obj.class_id and obj.class_id.code: badges.append(obj.class_id.code)
        if obj.document_type_id: badges.append(obj.document_type_id.label)
        if obj.subject_id: badges.append(obj.subject_id.name)
        badges.append('Publié' if obj.is_published else 'Brouillon')
        return badges
