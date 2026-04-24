


# Create your models here.
import uuid
from django.db import models


class Class(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=50, unique=True)
    label = models.CharField(max_length=255)
    cycle = models.CharField(max_length=100, null=True, blank=True)
    level_order = models.IntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.label


class Profile(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True)
    full_name = models.CharField(max_length=255, null=True, blank=True)
    role = models.CharField(max_length=50, null=True, blank=True)
    class_id = models.ForeignKey(
        Class, on_delete=models.SET_NULL, null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.email


class Subject(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=50, null=True, blank=True)
    name = models.CharField(max_length=255)
    description = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    class_id = models.ForeignKey(
        Class, on_delete=models.SET_NULL, null=True, blank=True)

    def __str__(self):
        return self.name


class AcademicYear(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    label = models.CharField(max_length=100)
    start_year = models.IntegerField()
    end_year = models.IntegerField()
    is_active = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.label


class DocumentType(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=50, null=True, blank=True)
    label = models.CharField(max_length=255)
    description = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.label


class Document(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=255)
    description = models.TextField(null=True, blank=True)
    file_name = models.CharField(max_length=255)
    file_path = models.CharField(max_length=500)
    bucket_name = models.CharField(max_length=255, null=True, blank=True)
    mime_type = models.CharField(max_length=100, null=True, blank=True)
    file_size = models.IntegerField(null=True, blank=True)
    class_id = models.ForeignKey(Class, on_delete=models.CASCADE)
    subject_id = models.ForeignKey(Subject, on_delete=models.CASCADE)
    academic_year_id = models.ForeignKey(
        AcademicYear, on_delete=models.CASCADE)
    document_type_id = models.ForeignKey(
        DocumentType, on_delete=models.CASCADE)

    uploaded_by = models.ForeignKey(
        Profile,
        on_delete=models.SET_NULL,
        null=True,
        related_name="uploaded_documents"
    )

    teachers = models.ManyToManyField(
        Profile,
        blank=True,
        related_name="teaching_documents"
    )

    status = models.CharField(max_length=50, default='draft')
    is_published = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.title
