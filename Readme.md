# G-baki API — Backend Django

> Bibliothèque numérique de la filière AS de l'ENSEA : catalogue de supports pédagogiques,
> recherche dans le texte des documents (page et ligne), aperçu de la première page.
> Porté par l'ENSEA Data Science Club.

API REST Django + Django REST Framework, base PostgreSQL, fichiers sur Cloudflare R2.
Deux fronts Next.js la consomment : **Gbaki-AI** (étudiants, repo `Gbaki-AI-interface`)
et **GBAKI Admin** (repo `Gbaki-searcher-admin`). Tout tourne sur Railway, projet « Baki AI API ».

---

## Modèle de données

| Modèle | Rôle |
|---|---|
| `Class` | Classe (AS1, AS2, AS3, ISE…) |
| `Profile` | Profil applicatif d'un utilisateur Django (email, rôle, classe) |
| `Subject` | Matière, rattachée à une classe. La description finit par le préfixe R2 de la matière |
| `AcademicYear` | Année académique ; une seule `is_active` |
| `DocumentType` | Type (Cours, TD, Corrigé, Sujet d'examen…), code = préfixe des fichiers dans R2 |
| `Teacher` | Enseignant, lié aux documents en ManyToMany |
| `Document` | Métadonnées d'un fichier R2 (`file_path` = clé objet). `is_folder` : dossier-projet (préfixe R2) |
| `DocumentPage` | Texte extrait d'une page (recherche plein texte) |
| `SearchTerm` | Vocabulaire indexé, pour corriger les fautes de frappe |
| `OTPCode` | Codes de réinitialisation de mot de passe |

Champs d'indexation de `Document` : `page_count`, `thumbnail_key` (vignette PNG de la 1re page
dans R2, sous `_thumbs/`), `indexed_at`.

---

## Endpoints

Base : `/api/`. Authentification par token (`Authorization: Token <clé>`).

### Authentification

| Endpoint | Description |
|---|---|
| `POST auth/register/` | Inscription. **Email au format `nom@ensea.edu.ci` obligatoire** |
| `POST auth/login/` | Connexion. Un compte non admin dont l'email n'est pas `@ensea.edu.ci` est refusé (403) |
| `GET auth/me/` | Profil courant (même règle d'email) |
| `POST auth/logout/` | Déconnexion |
| `POST auth/forgot-password/`, `auth/verify-otp/`, `auth/reset-password/` | Mot de passe oublié (OTP par email). Si l'email ne part pas (SMTP bloqué), réponse 503 en moins de 10 s avec un message invitant à contacter un admin |
| `POST admin/users/<profile_id>/reset-password/` | Admin uniquement : `{"new_password": "…"}` (8 caractères min.), remplace le mot de passe et ferme les sessions |

Les comptes `is_staff` / `is_superuser` (admins) ne sont pas soumis à la règle d'email.

### Catalogue

| Endpoint | Description |
|---|---|
| `classes/`, `subjects/?class_id=`, `academic-years/`, `document-types/`, `teachers/` | Référentiels (CRUD) |
| `profiles/` | Authentifié. Un étudiant ne voit et ne modifie que son profil ; un admin voit tout |
| `documents/` | Liste **paginée** et CRUD |
| `documents/{id}/download/?mode=preview\|download` | URL signée R2 (authentifié) |
| `documents/{id}/thumbnail/` | Redirige vers la vignette de la 1re page (public, documents publiés) ; générée à la volée si absente |
| `documents/{id}/files/` | Fichiers d'un dossier-projet, avec URLs signées (authentifié) |
| `documents/{id}/page/?n=3&q=…` | Texte d'une page, ligne par ligne, avec plages à surligner (authentifié) |
| `search/fulltext/?q=…&class_id=` | Recherche plein texte (authentifié), voir plus bas |
| `notifications/today/` | Nombre de documents publiés aujourd'hui |
| `autocomplete/documents/?q=`, `autocomplete/teachers/?q=` | Suggestions |

### Liste des documents

`GET /api/documents/` accepte :

| Paramètre | Effet |
|---|---|
| `page`, `page_size` | Pagination (50 par défaut, 200 max) |
| `class_id`, `class_code`, `subject_id`, `academic_year_id`, `document_type_id`, `teacher_id`, `uploaded_by`, `status`, `is_published` | Filtres |
| `title` | Titre contenant le texte |
| `search` | Recherche sur les métadonnées (accents ignorés, synonymes : proba, td, exam…) |
| `ordering` | `title`, `-title`, `year` (défaut : plus récents d'abord) |

Réponse : `{count, page, page_size, num_pages, results[, suggestions]}`.

### Recherche plein texte

`GET /api/search/fulltext/?q=intervalle de confiance` renvoie les passages trouvés dans le texte
des documents publiés :

```json
{
  "query": "intervalle de confiance",
  "corrections": [{"from": "intervale", "to": "intervalle"}],
  "count": 7, "exact_count": 4, "close_count": 3, "documents_count": 3,
  "documents": {"<id>": {"title": "…", "subject": "…", "page_count": 48, "…": "…"}},
  "results": [
    {"document_id": "<id>", "page": 31, "line": 3, "kind": "exact",
     "text": "Un intervalle de confiance de niveau 1 − α…", "spans": [[3, 26]], "found": null}
  ]
}
```

- **exacte** : la requête complète apparaît telle quelle dans la ligne (casse et accents ignorés) ;
- **proche** : au moins la moitié des mots (ou leur racine, ou leur correction) apparaissent.

PostgreSQL : index GIN sur `to_tsvector('french', gbaki_unaccent(content))` et index trigramme
sur le vocabulaire (migration `0009`). Le code SQL est isolé dans `core/search.py`.

---

## Catalogue : import et indexation

Les CSV du catalogue sont versionnés dans `data/catalogue/` (années, types, matières, documents).

```bash
# Vide documents, matières, années et types (classes, enseignants, profils conservés),
# puis réimporte depuis les CSV. Tailles de fichiers lues dans R2, clés absentes signalées.
python manage.py import_catalogue --confirm
#   --if-needed   ne fait rien si la base contient déjà exactement les documents du CSV
#   --backup-r2   sauvegarde l'ancien catalogue (dumpdata) dans R2 sous _backups/
#   --skip-r2     ne lit pas le bucket

# Extrait le texte page par page (PyMuPDF) et crée les vignettes. Reprenable.
python manage.py index_documents                  # documents jamais indexés
python manage.py index_documents --class AS1 --limit 50 --workers 6
python manage.py index_documents --retry-empty    # relance les PDF / textes restés sans texte
python manage.py index_documents --force          # tout réindexer
```

Règles d'import :
- documents sans type → `DOCUMENT` ;
- année hors de la liste des années (lecture erronée du nom de fichier) → année par défaut `2025-2026`,
  listée dans le rapport ;
- lignes `_projet=oui` → `is_folder=True` (la taille est la somme du dossier).

Indexation :
- PDF : texte de chaque page + vignette de la page 1 ;
- images : vignette ;
- txt, py, html, csv, tex… : texte (une page) ;
- docx, pptx, xlsx, zip… : pas de texte ni d'aperçu ;
- PDF scannés : vignette mais pas de texte (pas d'OCR) ;
- fichiers de plus de 80 Mo ignorés.

### Sur Railway

Le conteneur lance `scripts/background_tasks.sh` en arrière-plan au démarrage, piloté par des
variables du service `Gbaki-backend` :

| Variable | Tâche |
|---|---|
| `GBAKI_IMPORT_CATALOGUE=1` | `import_catalogue --confirm --if-needed --backup-r2` |
| `GBAKI_INDEX=1` | `index_documents` (reprend où il s'était arrêté) |
| `GBAKI_INDEX_RETRY=1` | `index_documents --retry-empty` |
| `GBAKI_INDEX_WORKERS` | Nombre de threads (4 par défaut) |
| `GBAKI_ADMIN_EMAIL` + `GBAKI_ADMIN_PASSWORD` | `create_admin` : crée ou promeut ce compte administrateur |
| `GBAKI_PURGE_STUDENTS=dry-run` | `purge_students --dry-run` : rapport des comptes non admin, par classe |
| `GBAKI_PURGE_STUDENTS=confirm` + `GBAKI_PURGE_BEFORE=<date ISO>` | `purge_students --confirm --before …` : supprime les comptes non admin créés avant la date |

`purge_students` garde les comptes `is_staff` / `is_superuser` et leurs profils ; il supprime les
autres comptes de connexion (et tokens), profils et codes OTP. `GBAKI_PURGE_BEFORE` est obligatoire
en mode `confirm` : un redémarrage avec la variable oubliée n'efface pas les réinscriptions.

Retirer les variables une fois les tâches terminées. Suivi : `railway logs --service Gbaki-backend`.

---

## Installation locale

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
python manage.py migrate
python manage.py create_admin --email admin@exemple.com --password '…'
python manage.py runserver 8000
python manage.py test core       # 23 tests (la correction orthographique n'est testée que sous PostgreSQL)
```

Sans `DATABASE_URL`, la base est SQLite ; la recherche plein texte passe alors par un repli
simplifié (sans correction des fautes).

### Variables d'environnement

```env
DJANGO_SECRET_KEY=…
DEBUG=False
ALLOWED_HOSTS=*
DATABASE_URL=postgresql://…            # injectée par Railway
CF_R2_ACCESS_KEY=…
CF_R2_SECRET_KEY=…
CF_R2_BUCKET_NAME=gbaki-documents
CF_R2_ENDPOINT_URL=https://<ACCOUNT_ID>.r2.cloudflarestorage.com
CF_R2_PRESIGN_EXPIRY=3600
CF_R2_THUMBS_PREFIX=_thumbs            # préfixe des vignettes
EMAIL_HOST_USER=…
EMAIL_HOST_PASSWORD=…
CORS_ALLOW_ALL=True
EMAIL_TIMEOUT=10                       # secondes avant d'abandonner l'envoi SMTP
```

**Emails** (`core/emailing.py`, même principe que Prepaxia) : l'**API HTTP Gmail** (OAuth2) est
utilisée en priorité, car Railway bloque le SMTP sortant ; le SMTP Gmail (`EMAIL_HOST_*`) sert de
repli en local. Variables : `GMAIL_API_CLIENT_ID`, `GMAIL_API_CLIENT_SECRET`,
`GMAIL_API_REFRESH_TOKEN`, `GMAIL_API_SENDER` (obtention : `DEPLOY_RAILWAY.md`). Si aucune voie
ne fonctionne, « mot de passe oublié » répond 503 avec un message invitant à contacter un admin,
qui peut réinitialiser le mot de passe depuis le front admin (page Utilisateurs).

Déploiement : voir `DEPLOY_RAILWAY.md`.

---

## Stack

Django 6, Django REST Framework, PostgreSQL 18 (Railway), PyMuPDF, boto3 (Cloudflare R2),
WhiteNoise, gunicorn.

*G-baki — ENSEA Data Science Club*
