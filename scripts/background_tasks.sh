#!/bin/sh
# Tâches ponctuelles lancées au démarrage du conteneur Railway, en arrière-plan de gunicorn.
# Pilotées par des variables Railway (à retirer une fois la tâche terminée) :
#   GBAKI_IMPORT_CATALOGUE=1  import du catalogue (data/catalogue), sauvegarde R2 de l'ancien,
#                             sans effet si la base est déjà à jour
#   GBAKI_INDEX=1             indexation plein texte + vignettes (reprend où elle s'est arrêtée)
set -u
if [ "${GBAKI_IMPORT_CATALOGUE:-0}" = "1" ]; then
  echo "[tasks] import_catalogue"
  python manage.py import_catalogue --confirm --if-needed --backup-r2 || { echo "[tasks] import en échec"; exit 1; }
fi
if [ "${GBAKI_INDEX:-0}" = "1" ]; then
  echo "[tasks] index_documents"
  python manage.py index_documents --workers "${GBAKI_INDEX_WORKERS:-4}"
fi
if [ "${GBAKI_INDEX_RETRY:-0}" = "1" ]; then
  echo "[tasks] index_documents --retry-empty"
  python manage.py index_documents --retry-empty --workers "${GBAKI_INDEX_WORKERS:-4}"
fi
echo "[tasks] terminé"
