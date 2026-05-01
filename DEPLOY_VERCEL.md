# Guide de déploiement — Gbaki Backend sur Vercel

## Fichiers modifiés / créés pour Vercel

| Fichier | Action | Rôle |
|---|---|---|
| `vercel.json` | ✅ Créé | Config Vercel : routes, runtime Python, fichiers statiques |
| `build_files.sh` | ✅ Créé | Script de build : install, migrate, collectstatic |
| `gbaki_backend/wsgi.py` | ✏️ Modifié | Ajout de l'alias `app` requis par @vercel/python |
| `gbaki_backend/settings.py` | ✏️ Modifié | Neon PostgreSQL, WhiteNoise, VERCEL_URL automatique |
| `requirements.txt` | ✏️ Modifié | Ajout psycopg2, whitenoise, dj-database-url, python-dotenv |
| `.env.example` | ✏️ Mis à jour | Template avec DATABASE_URL format Neon |

---

## ÉTAPE 1 — Créer la base PostgreSQL sur Neon (gratuit)

Vercel ne fournit pas de base de données — on utilise **Neon** (PostgreSQL serverless).

1. Aller sur **[neon.tech](https://neon.tech)** → créer un compte (gratuit)
2. Créer un projet → choisir la région **AWS / Europe West** ou **US East**
3. Dans le dashboard Neon, copier la **Connection String** :
   ```
   postgresql://user:password@ep-xxxx.us-east-2.aws.neon.tech/neondb?sslmode=require
   ```
4. Garder cette URL — elle sera utilisée comme `DATABASE_URL`

---

## ÉTAPE 2 — Pousser sur GitHub

```bash
git init
git add .
git commit -m "feat: backend Gbaki prêt pour Vercel"
git remote add origin https://github.com/TON_USERNAME/gbaki-backend.git
git branch -M main
git push -u origin main
```

**Vérifier :**
- `.env` absent du repo (`git status` ne doit pas le montrer)
- `vercel.json` et `build_files.sh` bien présents

---

## ÉTAPE 3 — Créer le projet sur Vercel

1. Aller sur **[vercel.com](https://vercel.com)** → Se connecter avec GitHub
2. Cliquer **"Add New Project"**
3. Importer le repo **gbaki-backend**
4. Framework Preset → laisser **"Other"**
5. Ne pas modifier le Build Command (il lit `vercel.json`)
6. Cliquer **"Deploy"** (le 1er build échouera si les variables ne sont pas encore définies)

---

## ÉTAPE 4 — Configurer les variables d'environnement

Dans Vercel → ton projet → **Settings** → **Environment Variables**, ajouter :

| Variable | Valeur |
|---|---|
| `DJANGO_SECRET_KEY` | Clé aléatoire longue (voir commande ci-dessous) |
| `DEBUG` | `False` |
| `ALLOWED_HOSTS` | `ton-projet.vercel.app` |
| `DATABASE_URL` | URL Neon copiée à l'étape 1 |
| `CF_R2_ACCESS_KEY` | Valeur de ton ancien `.env` |
| `CF_R2_SECRET_KEY` | Valeur de ton ancien `.env` |
| `CF_R2_BUCKET_NAME` | `gbaki-documents` |
| `CF_R2_ENDPOINT_URL` | Valeur de ton ancien `.env` |
| `CF_R2_PRESIGN_EXPIRY` | `3600` |
| `EMAIL_HOST_USER` | ton email Gmail |
| `EMAIL_HOST_PASSWORD` | mot de passe d'application Gmail |
| `CORS_ALLOW_ALL` | `True` |

**Générer une SECRET_KEY :**
```bash
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

---

## ÉTAPE 5 — Redéployer

Après avoir ajouté les variables :
1. Vercel → onglet **Deployments**
2. Cliquer sur les `...` du dernier déploiement → **Redeploy**

Vercel exécutera automatiquement `build_files.sh` qui :
- Installe les dépendances
- Lance `python manage.py collectstatic`
- Lance `python manage.py migrate` (crée les tables sur Neon)

---

## ÉTAPE 6 — Créer le superadmin

Après le déploiement, dans Vercel → **Functions** → **View Logs** (ou via Vercel CLI) :

```bash
# Installer Vercel CLI
npm i -g vercel

# Se connecter et ouvrir un shell
vercel login
vercel env pull .env.local   # récupérer les variables
python manage.py createsuperuser
```

Ou directement via Neon console SQL :
```sql
-- Solution alternative : créer le superuser via SQL dans la console Neon
```

---

## Ton API sera disponible à

```
https://ton-projet.vercel.app/api/
https://ton-projet.vercel.app/admin/
```

---

## ⚠️ Limites de Vercel à connaître

| Limite | Impact |
|---|---|
| Fonctions serverless (pas de serveur persistant) | Les codes OTP stockés en mémoire (`_otp_store`) sont perdus entre deux requêtes |
| Timeout 30s max par requête | Uploads de gros fichiers PDF à faire directement vers R2 côté client |
| Pas de cron intégré (plan gratuit) | Pas de tâches planifiées |

**Note sur l'OTP :** Le `_otp_store` en mémoire dans `auth_views.py` ne fonctionnera pas de façon fiable sur Vercel (serverless). Si c'est critique, il faudra stocker les OTP en base de données. Dis-moi et je fais la modification.

---

## Checklist finale

- [ ] Neon créé et `DATABASE_URL` copiée
- [ ] `.env` absent du repo GitHub
- [ ] `vercel.json` et `build_files.sh` présents dans le repo
- [ ] Toutes les variables d'environnement renseignées dans Vercel
- [ ] Redéploiement lancé après ajout des variables
- [ ] Build vert ✅ dans Vercel → `/api/` répond
