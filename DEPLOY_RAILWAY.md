# Déploiement Railway — Gbaki

Projet Railway **Baki AI API**, environnement `production`. Tout se pilote avec le CLI Railway
(`railway whoami` pour vérifier la connexion, `railway login` sinon).

| Service | Contenu | Domaine |
|---|---|---|
| `Gbaki-backend` | Ce dépôt (Django) | https://gbaki-backend-production-link.up.railway.app |
| `Gbaki-user` | Front étudiant Gbaki-AI (`Gbaki-AI-interface`) | https://gbaki-user-production.up.railway.app |
| `Gbaki-admin` | Front admin (`Gbaki-searcher-admin`) | https://gbaki-admin-production.up.railway.app |
| `Postgres` | Base PostgreSQL 18 (volume) | interne |

## Backend

```bash
cd Gbaki_back-end
railway service link Gbaki-backend
railway up --service Gbaki-backend --ci      # build + déploiement, logs en direct
```

Le service est aussi relié au dépôt GitHub `jasonemmanue/Gbaki-backend` (branche `main`).

Au démarrage (`Procfile`) : `migrate`, `collectstatic`, tâches de fond (`scripts/background_tasks.sh`),
puis gunicorn. Railpack ignore la ligne `release:` d'un Procfile : les migrations sont donc dans `web:`.

Python : `runtime.txt` contient `python-3.12` (une version figée comme `3.12.3` fait échouer le
build : le builder refuse les versions sans attestation GitHub).

Tâches ponctuelles (import du catalogue, indexation) : variables `GBAKI_*`, voir le `Readme.md`.

```bash
railway variable set GBAKI_INDEX=1 --service Gbaki-backend --skip-deploys
railway redeploy --service Gbaki-backend --yes
railway logs --service Gbaki-backend
```

Ajouter un administrateur (le mot de passe ne passe que par les variables Railway, retirées ensuite) :

```bash
railway variable set GBAKI_ADMIN_EMAIL=prenom.nom@exemple.com --service Gbaki-backend --skip-deploys
# PowerShell : le mot de passe est demandé puis transmis par le tube (--stdin lit un tube, pas le clavier)
Read-Host "Mot de passe admin" | railway variable set GBAKI_ADMIN_PASSWORD --stdin --service Gbaki-backend   # redéploie
railway logs --service Gbaki-backend | grep create_admin                     # « Admin prêt : … »
railway variable delete GBAKI_ADMIN_PASSWORD --service Gbaki-backend
railway variable delete GBAKI_ADMIN_EMAIL --service Gbaki-backend
```

SMTP : bloqué en sortie sur l'offre Hobby de Railway (l'email « mot de passe oublié » ne part pas).

## Fronts Next.js

Chaque front a un `Dockerfile` (build Next.js, `next start` sur `$PORT`) et un `.railwayignore`.

```bash
cd gbaki-searcher
railway up --service Gbaki-user --ci

cd "gbaki searcher Admin"
railway up --service Gbaki-admin --ci
```

`NEXT_PUBLIC_API_URL` vaut `https://${{Gbaki-backend.RAILWAY_PUBLIC_DOMAIN}}/api` : elle suit
le domaine du backend et est injectée au build (`ARG` du Dockerfile).

**Next.js doit rester à jour** (14.2.35 aujourd'hui) : Railway refuse de construire une version de
Next.js connue comme vulnérable. Le déploiement échoue alors juste après « scheduling build »,
sans aucun log.

## Vérifications après déploiement

```bash
railway service list                          # tous les services « Online »
railway logs --service Gbaki-backend          # migrations, tâches, erreurs
curl https://gbaki-backend-production-link.up.railway.app/api/documents/?page_size=1
```

## Checklist

- [ ] `DEBUG=False`, `DJANGO_SECRET_KEY` propre à la prod
- [ ] Variables `CF_R2_*` et `EMAIL_*` renseignées sur `Gbaki-backend`
- [ ] Variables `GBAKI_*` retirées une fois les tâches terminées
- [ ] Les 3 services « Online »
