# Configuration Cloudflare D1 + R2 pour GBAKI Backend

node --version
npm --version

npm install -g wrangler

npx wrangler --version

npx wrangler login

## 1. Cloudflare D1 (Base de données)

### Créer la base D1
```bash
npx wrangler d1 create gbaki-db
```
Copie l'ID affiché dans ton wrangler.toml.

### Exporter la structure SQLite → D1
```bash
# Génère le schéma SQL depuis Django
pip install django-storages boto3

python manage.py sqlmigrate core 0001 > schema.sql
# ...répète pour chaque migration 0002→0006

# Importe dans D1
npx wrangler d1 execute gbaki-db --file=schema.sql
```

### Connexion Django ↔ D1

## 2. Cloudflare R2 (Stockage fichiers)

### Créer le bucket R2
```bash
npx wrangler r2 bucket create gbaki-documents
```

### Variables d'environnement (.env)
```env
CF_R2_ENDPOINT_URL=https://<ACCOUNT_ID>.r2.cloudflarestorage.com
CF_R2_ACCESS_KEY=<ton_access_key_id>
CF_R2_SECRET_KEY=<ton_secret_key>
CF_R2_BUCKET_NAME=gbaki-documents
CF_R2_PUBLIC_DOMAIN=https://pub-xxx.r2.dev   # si bucket public
CF_R2_PRESIGN_EXPIRY=3600
```


pip install python-dotenv

python manage.py shell  /// pour les tests

### Uploader un fichier vers R2
```bash
wrangler r2 object put gbaki-documents/documents/cours_proba.pdf \
  --file=./cours_proba.pdf
```

### Compte Cloudflare utilisé
sakamemmanuel@gmail.com → https://dash.cloudflare.com

---

## 3. Démarrage local (SQLite — développement)
```bash
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver 9000
```
