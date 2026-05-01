# Guide de déploiement — Gbaki Backend sur Railway

## Résumé des fichiers modifiés / créés

| Fichier | Action | Raison |
|---|---|---|
| `gbaki_backend/settings.py` | ✏️ Modifié | Support PostgreSQL, WhiteNoise, sécurité prod |
| `requirements.txt` | ✏️ Modifié | Ajout gunicorn, psycopg2, whitenoise, dj-database-url |
| `Procfile` | ✅ Créé | Indique à Railway comment démarrer l'app |
| `runtime.txt` | ✅ Créé | Fixe la version Python (3.12.3) |
| `.gitignore` | ✏️ Mis à jour | Exclut .env, venv, db.sqlite3, staticfiles |
| `.env.example` | ✏️ Mis à jour | Template des variables d'environnement |
| `.env` | ❌ Supprimé du repo | Ne jamais committer les secrets |

---

## ÉTAPE 1 — Préparer le dépôt GitHub

```bash
# Dans le dossier du projet
git init
git add .
git commit -m "feat: backend Gbaki prêt pour Railway"

# Créer un repo sur github.com puis :
git remote add origin https://github.com/TON_USERNAME/gbaki-backend.git
git branch -M main
git push -u origin main
```

**Vérifier avant de pousser :**
- Le fichier `.env` n'apparaît PAS dans `git status`
- Les dossiers `venv/`, `__pycache__/`, `db.sqlite3` sont ignorés

---

## ÉTAPE 2 — Créer le projet sur Railway

1. Aller sur **[railway.app](https://railway.app)** → Se connecter avec GitHub
2. Cliquer **"New Project"**
3. Choisir **"Deploy from GitHub repo"**
4. Sélectionner **gbaki-backend**
5. Railway détecte automatiquement Python et lance le build

---

## ÉTAPE 3 — Ajouter PostgreSQL

Dans ton projet Railway :
1. Cliquer **"+ New"** → **"Database"** → **"PostgreSQL"**
2. Railway crée la base et injecte `DATABASE_URL` automatiquement dans l'environnement

---

## ÉTAPE 4 — Configurer les variables d'environnement

Dans Railway → ton service → onglet **"Variables"**, ajouter :

```
DJANGO_SECRET_KEY   = [génère une clé ici : python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"]
DEBUG               = False
ALLOWED_HOSTS       = ton-projet.up.railway.app

CF_R2_ACCESS_KEY    = [valeur de ton .env]
CF_R2_SECRET_KEY    = [valeur de ton .env]
CF_R2_BUCKET_NAME   = gbaki-documents
CF_R2_ENDPOINT_URL  = [valeur de ton .env]
CF_R2_PRESIGN_EXPIRY = 3600

EMAIL_HOST_USER     = [valeur de ton .env]
EMAIL_HOST_PASSWORD = [valeur de ton .env]

CORS_ALLOW_ALL      = True
```

> `DATABASE_URL` est déjà injectée automatiquement par le plugin PostgreSQL — ne pas la modifier.

---

## ÉTAPE 5 — Déploiement

Railway lance automatiquement à chaque `git push` :
1. `pip install -r requirements.txt`
2. `python manage.py migrate --noinput`  (via Procfile release)
3. `python manage.py collectstatic --noinput`
4. `gunicorn gbaki_backend.wsgi` sur le port Railway

Ton API sera disponible à : `https://ton-projet.up.railway.app/api/`

---

## Commandes utiles après déploiement

```bash
# Créer un superuser admin (via Railway CLI ou shell Railway)
python manage.py createsuperuser

# Voir les logs en direct
railway logs

# Lancer en local pour tester
python manage.py runserver
```

---

## Checklist finale avant mise en ligne

- [ ] `.env` absent du dépôt GitHub
- [ ] `DJANGO_SECRET_KEY` différente de la clé de dev
- [ ] `DEBUG=False` sur Railway
- [ ] PostgreSQL ajouté et `DATABASE_URL` visible dans les variables
- [ ] Toutes les variables CF_R2 et EMAIL renseignées
- [ ] Build Railway vert ✅
