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


class Teacher(models.Model):
    """
    Table dédiée aux enseignants — indépendante de Profile.
    Permet l'autocomplete et la réutilisation entre documents.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    full_name = models.CharField(max_length=255)
    email = models.EmailField(null=True, blank=True)
    department = models.CharField(max_length=255, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['full_name']

    def __str__(self):
        return self.full_name


class Document(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=255)
    description = models.TextField(null=True, blank=True)
    file_name = models.CharField(max_length=255)
    # Cloudflare R2 : chemin objet dans le bucket (ex: "documents/cours_proba.pdf")
    file_path = models.CharField(max_length=500)
    # Nom du bucket R2
    bucket_name = models.CharField(max_length=255, null=True, blank=True)
    mime_type = models.CharField(max_length=100, null=True, blank=True)
    file_size = models.IntegerField(null=True, blank=True)

    class_id = models.ForeignKey(Class, on_delete=models.CASCADE)
    subject_id = models.ForeignKey(Subject, on_delete=models.CASCADE)
    academic_year_id = models.ForeignKey(AcademicYear, on_delete=models.CASCADE)
    document_type_id = models.ForeignKey(DocumentType, on_delete=models.CASCADE)

    uploaded_by = models.ForeignKey(
        Profile, on_delete=models.SET_NULL, null=True,
        related_name="uploaded_documents"
    )

    # Relation M2M avec la nouvelle table Teacher
    teachers = models.ManyToManyField(
        Teacher, blank=True, related_name="documents"
    )

    status = models.CharField(max_length=50, default='draft')
    is_published = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Dossier-projet : file_path est un préfixe R2 (se termine par "/"), pas un fichier
    is_folder = models.BooleanField(default=False)
    # Rempli par la commande index_documents
    page_count = models.IntegerField(null=True, blank=True)
    thumbnail_key = models.CharField(max_length=500, null=True, blank=True)
    indexed_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return self.title


class DocumentPage(models.Model):
    """Texte extrait d'une page de document, pour la recherche plein texte."""
    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name='pages')
    page_number = models.IntegerField()
    content = models.TextField()

    class Meta:
        ordering = ['document', 'page_number']
        constraints = [
            models.UniqueConstraint(fields=['document', 'page_number'], name='uniq_document_page'),
        ]

    def __str__(self):
        return f"{self.document_id} p.{self.page_number}"


class SearchTerm(models.Model):
    """Vocabulaire des documents indexés (mots sans accents), pour corriger les fautes de frappe."""
    word = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return self.word


class OTPCode(models.Model):
    """
    Stockage persistant des codes OTP pour la réinitialisation de mot de passe.
    Remplace le dictionnaire en mémoire (_otp_store) incompatible avec le serverless.
    """
    email       = models.EmailField(db_index=True)
    code        = models.CharField(max_length=4)
    reset_token = models.CharField(max_length=20, blank=True, default='')
    expires_at  = models.DateTimeField()
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def is_expired(self):
        from django.utils import timezone
        return timezone.now() > self.expires_at

    def __str__(self):
        return f"OTP({self.email}, expires={self.expires_at})"
