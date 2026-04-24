
# Register your models here.
from django.contrib import admin
from .models import Class, Profile, Subject, AcademicYear, DocumentType, Document

# Liste de tes modèles pour les voir dans l'interface
admin.site.register(Class)
admin.site.register(Profile)
admin.site.register(Subject)
admin.site.register(AcademicYear)
admin.site.register(DocumentType)
admin.site.register(Document)