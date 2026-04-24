# 📚 G-baki API — Backend Django

> Moteur de gestion et de recherche intelligente de supports pédagogiques

---

## 🎯 Vue d'ensemble

**G-baki** est une API REST construite avec Django & Django REST Framework. Elle constitue le backend d'un manuel numérique scolaire permettant :

- Aux **enseignants** de déposer et organiser des supports pédagogiques (cours, TD, examens, corrigés…)
- Aux **étudiants** de les retrouver rapidement via une **recherche avancée multi-critères**
- Aux **administrateurs** de gérer les classes, matières, années académiques et types de documents

---

## 🏗️ Architecture générale

```
gbaki_backend/
├── core/                          # Application principale
│   ├── models.py                  # Modèles de données
│   ├── serializers.py             # Sérialiseurs DRF enrichis
│   ├── views.py                   # ViewSets + logique de recherche
│   ├── admin.py                   # Interface d'administration Django
│   └── migrations/                # Historique des migrations
│       ├── 0001_initial.py
│       ├── 0002_remove_document_created_at_and_more.py
│       ├── 0003_document_created_at_document_is_published_and_more.py
│       └── 0004_remove_document_teacher_document_teachers.py
├── manage.py
├── pyproject.toml
└── requirements.txt
```

---

## 🗄️ Modèle de données

### Schéma relationnel

```
Class
  ├── code (unique)         ex: "AS2", "L1-ECO"
  ├── label                 ex: "Analyse Statistique 2"
  ├── cycle                 ex: "Licence"
  └── level_order           ex: 2

Profile (utilisateur)
  ├── email (unique)
  ├── full_name
  ├── role                  ex: "teacher", "student", "admin"
  └── class_id → Class

Subject (matière)
  ├── code                  ex: "STAT3"
  ├── name                  ex: "Statistiques 3"
  └── class_id → Class

AcademicYear (année académique)
  ├── label                 ex: "2024-2025"
  ├── start_year            ex: 2024
  ├── end_year              ex: 2025
  └── is_active             (une seule active à la fois)

DocumentType (type de document)
  ├── code                  ex: "COURS", "TD", "EXAM", "CORR"
  └── label                 ex: "Cours", "Travaux Dirigés", "Examen", "Corrigé"

Document (support pédagogique) ← cœur du système
  ├── title
  ├── description
  ├── file_name
  ├── file_path             URL directe vers le fichier (Cloudflare R2)
  ├── bucket_name
  ├── mime_type             ex: "application/pdf"
  ├── file_size
  ├── class_id → Class
  ├── subject_id → Subject
  ├── academic_year_id → AcademicYear
  ├── document_type_id → DocumentType
  ├── uploaded_by → Profile
  ├── teachers ↔ Profile    (relation ManyToMany)
  ├── status                ex: "draft", "published"
  └── is_published          (booléen)
```

### Notes sur le stockage des fichiers

Les fichiers physiques sont hébergés sur **Cloudflare R2** (stockage objet compatible S3). La base de données ne conserve que les **métadonnées** : chemin, bucket, type MIME, taille. Le champ `file_path` sert de lien cliquable direct vers le fichier.

---

## 🔌 Endpoints de l'API

Base URL : `/api/`

| Ressource       | Endpoint               | Méthodes           |
|----------------|------------------------|--------------------|
| Classes         | `/api/classes/`        | GET, POST, PUT, DELETE |
| Profils         | `/api/profiles/`       | GET, POST, PUT, DELETE |
| Matières        | `/api/subjects/`       | GET, POST, PUT, DELETE |
| Années acad.    | `/api/academic-years/` | GET, POST, PUT, DELETE |
| Types de doc    | `/api/document-types/` | GET, POST, PUT, DELETE |
| Documents       | `/api/documents/`      | GET, POST, PUT, DELETE |

---

## 🔍 Recherche et filtres sur `/api/documents/`

### Filtres directs (query params)

| Paramètre          | Description                              | Exemple                        |
|--------------------|------------------------------------------|--------------------------------|
| `class_id`         | Filtrer par classe (UUID)                | `?class_id=abc-123`            |
| `subject_id`       | Filtrer par matière (UUID)               | `?subject_id=xyz-456`          |
| `academic_year_id` | Filtrer par année académique (UUID)      | `?academic_year_id=aaa-789`    |
| `document_type_id` | Filtrer par type de document (UUID)      | `?document_type_id=bbb-321`    |
| `teacher`          | Filtrer par enseignant (UUID)            | `?teacher=ccc-654`             |
| `uploaded_by`      | Filtrer par uploadeur (UUID)             | `?uploaded_by=ddd-987`         |
| `status`           | Filtrer par statut                       | `?status=draft`                |
| `is_published`     | Filtrer par publication                  | `?is_published=true`           |
| `search`           | Recherche textuelle intelligente         | `?search=proba conditionnelle` |

### Fonctionnement de la recherche textuelle (`?search=`)

La recherche est multi-couches :

#### 1. Normalisation unicode
Suppression des accents pour une correspondance insensible : `probabilité` ≡ `probabilite`

#### 2. Expansion de synonymes
| Terme saisi | Termes recherchés                                       |
|-------------|--------------------------------------------------------|
| `proba`     | probabilite, probabilité                               |
| `math`      | mathematiques, mathématiques, mathematique             |
| `stat`      | statistique, statistiques                              |
| `td`        | travaux diriges, travaux dirigés                       |
| `tp`        | travaux pratiques                                      |
| `corrige`   | corrige, corrigé, correction                           |
| `exam`      | examen, épreuve                                        |
| `devoir`    | devoir, interro, interrogation                         |

#### 3. Champs de recherche couverts
- Titre et description du document
- Nom et email des enseignants liés
- Nom et code de la matière
- Label et code de la classe
- Label du type de document
- Label de l'année académique

#### 4. Suggestions orthographiques
Si la recherche retourne **0 résultats**, l'API analyse le vocabulaire existant et propose des corrections via `difflib.get_close_matches`.

**Exemple de réponse avec suggestion :**
```json
{
  "count": 0,
  "results": [],
  "suggestions": ["probabilite", "statistique"]
}
```

### Format de réponse standard `/api/documents/`

```json
{
  "count": 4,
  "results": [
    {
      "id": "1482694624fe4eb182d09af27c544636",
      "title": "Devoir Estimation AS2 2024-2025",
      "description": "Examen 1 d'estimation 2025",
      "file_name": "Devoir_Estimation_AS2_2024-2025",
      "clickable_link": "https://...",
      "mime_type": "application/pdf",
      "file_size": null,
      "class_info": { "code": "AS2", "label": "Analyse Statistique 2" },
      "subject": "Estimation",
      "document_type": "Devoir/TD",
      "academic_year": "2024-2025",
      "uploaded_by": "Jean Dupont",
      "teachers": [
        { "name": "Jean Dupont", "email": "jean@school.ci" }
      ],
      "status": "draft",
      "is_published": false,
      "created_at": "2026-04-13T15:24:37Z",
      "updated_at": "2026-04-13T15:24:37Z",
      "previewable": true,
      "badges": ["PDF", "AS2", "Devoir/TD", "Estimation", "Brouillon", "Draft"]
    }
  ]
}
```

### Champs calculés du sérialiseur

| Champ           | Description                                                        |
|-----------------|--------------------------------------------------------------------|
| `clickable_link` | Lien direct vers le fichier (= `file_path`)                       |
| `previewable`    | `true` si PDF, PNG, JPEG, WEBP ou TXT                             |
| `badges`         | Liste de tags résumant le document (type MIME, classe, statut…)   |
| `class_info`     | Objet `{ code, label }` de la classe                              |
| `teachers`       | Liste `[{ name, email }]` des enseignants                         |

---

## ⚙️ Installation & lancement

### Prérequis
- Python 3.14+
- SQLite (dev) ou PostgreSQL (prod)

### Installation

```bash
# Cloner le projet
git clone <repo-url>
cd gbaki_backend

# Installer les dépendances (avec uv recommandé)
uv sync
# ou avec pip
pip install -r requirements.txt

# Appliquer les migrations
python manage.py migrate

# Créer un superutilisateur
python manage.py createsuperuser

# Lancer le serveur
python manage.py runserver
```

### Variables d'environnement recommandées

```env
SECRET_KEY=your-django-secret-key
DEBUG=True
DATABASE_URL=sqlite:///db.sqlite3
# Pour la prod :
# DATABASE_URL=postgresql://user:pass@localhost/gbaki
CLOUDFLARE_R2_BUCKET=gbaki--ia
CLOUDFLARE_R2_ENDPOINT=https://...
```

---

## 🛠️ Stack technique

| Composant             | Technologie                          |
|-----------------------|--------------------------------------|
| Framework             | Django 6.0.3                         |
| API REST              | Django REST Framework 3.15+          |
| Base de données (dev) | SQLite 3                             |
| Base de données (prod)| PostgreSQL (via psycopg2-binary)     |
| Stockage de fichiers  | Cloudflare R2 (compatible S3)        |
| CORS                  | django-cors-headers                  |
| Filtrage              | django-filter                        |
| Gestion dépendances   | uv / pip                             |

---

## 📊 État du projet

### ✅ Implémenté
- Modèles complets avec UUIDs
- CRUD complet sur toutes les ressources
- Recherche textuelle multi-champs avec normalisation unicode
- Expansion de synonymes en français
- Suggestions orthographiques
- Filtres combinables
- Sérialiseur enrichi (badges, previewable, clickable_link)
- Interface d'administration Django
- Support ManyToMany enseignants par document

### 🔜 À implémenter
- Authentification (JWT / Supabase Auth)
- Permissions par rôle (admin / enseignant / étudiant)
- Pagination côté API
- Upload de fichiers vers Cloudflare R2 via l'API
- Endpoint dashboard (stats par classe, par matière, activité récente)
- Tests unitaires et d'intégration
- Documentation Swagger / OpenAPI

---

## 🗂️ Historique des migrations

| Migration | Description                                                           |
|-----------|-----------------------------------------------------------------------|
| `0001`    | Structure initiale : Class, Profile, Subject, AcademicYear, DocumentType, Document |
| `0002`    | Refactoring temporaire : suppression de `created_at`, `status`, `is_published` |
| `0003`    | Réintroduction des champs + ajout d'un `teacher` FK                   |
| `0004`    | Remplacement du FK `teacher` par une relation **ManyToMany** `teachers` |

---

## 👥 Rôles utilisateurs (Profile.role)

| Rôle      | Description                                                     |
|-----------|-----------------------------------------------------------------|
| `admin`   | Gestion complète (classes, matières, documents, utilisateurs)   |
| `teacher` | Upload et gestion de ses propres documents                      |
| `student` | Consultation et recherche de documents publiés                  |

---

*G-baki — Manuel numérique de gestion des supports pédagogiques*


cd gbaki_backend
cd C:\Users\hp\StudioProjects\Gbaki_back-end
.\.venv\Scripts\Activate.ps1
pip install django djangorestframework django-cors-headers //Mieux
pip install djangorestframework djangorestframework-authtoken django-cors-headers
ou  python manage.py makemigrations
    python manage.py migrate

python manage.py migrate
python manage.py runserver 8000


# ── COMMANDES APRÈS MODIFICATION ─────────────────────────────────
# .venv\Scripts\python.exe manage.py migrate
# .venv\Scripts\python.exe manage.py createsuperuser
# .venv\Scripts\python.exe manage.py runserver 8000


#SUPERUSERDJANGO DE MA PART

#NOM:emmanuel , Email:emmanuelsakam@gmail.com ,password:123456789
#NOM:emmanu , Email:emmanusakam@ensea.edu.ci ,password:123456789



comptes claudes travailleurs:
emmanusakam@gmail.com et emmanudev2@gmail.com


cd gbaki_backend
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser   # crée ton admin
python manage.py runserver 8000