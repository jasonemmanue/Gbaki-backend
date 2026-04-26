"""
gbaki_backend/urls.py
"""
from django.contrib import admin
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from core.views import (
    ClassViewSet, ProfileViewSet, SubjectViewSet,
    AcademicYearViewSet, DocumentTypeViewSet, DocumentViewSet, TeacherViewSet,
    autocomplete_teachers, autocomplete_documents,
    upload_document,
)
from core.auth_views import register, login_view, logout_view, me

router = DefaultRouter()
router.register(r'classes',        ClassViewSet)
router.register(r'profiles',       ProfileViewSet)
router.register(r'subjects',       SubjectViewSet)
router.register(r'academic-years', AcademicYearViewSet)
router.register(r'document-types', DocumentTypeViewSet)
router.register(r'documents',      DocumentViewSet)
router.register(r'teachers',       TeacherViewSet)

urlpatterns = [
    path('admin/',                          admin.site.urls),

    # Auth
    path('api/auth/register/',              register,             name='auth-register'),
    path('api/auth/login/',                 login_view,           name='auth-login'),
    path('api/auth/logout/',                logout_view,          name='auth-logout'),
    path('api/auth/me/',                    me,                   name='auth-me'),

    # Upload PDF → Cloudflare R2  (AVANT include(router.urls) pour éviter les conflits)
    path('api/documents/upload/',           upload_document,      name='document-upload'),

    # Autocomplete
    path('api/autocomplete/teachers/',      autocomplete_teachers,  name='autocomplete-teachers'),
    path('api/autocomplete/documents/',     autocomplete_documents, name='autocomplete-docs'),

    # REST API (ViewSets)
    path('api/',                            include(router.urls)),
]