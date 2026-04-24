"""
gbaki_backend/urls.py
"""
from django.contrib import admin
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from core.views import (
    ClassViewSet, ProfileViewSet, SubjectViewSet,
    AcademicYearViewSet, DocumentTypeViewSet, DocumentViewSet,
)
from core.auth_views import register, login_view, logout_view, me

router = DefaultRouter()
router.register(r'classes',        ClassViewSet)
router.register(r'profiles',       ProfileViewSet)
router.register(r'subjects',       SubjectViewSet)
router.register(r'academic-years', AcademicYearViewSet)
router.register(r'document-types', DocumentTypeViewSet)
router.register(r'documents',      DocumentViewSet)

urlpatterns = [
    path('admin/',          admin.site.urls),
    path('api/auth/register/', register,    name='auth-register'),
    path('api/auth/login/',    login_view,  name='auth-login'),
    path('api/auth/logout/',   logout_view, name='auth-logout'),
    path('api/auth/me/',       me,          name='auth-me'),
    path('api/',               include(router.urls)),
]
