#!/bin/sh
# Tâches ponctuelles lancées au démarrage du conteneur Railway, en arrière-plan de gunicorn.
# Pilotées par des variables Railway (à retirer une fois la tâche terminée) :
#   GBAKI_IMPORT_CATALOGUE=1  import du catalogue (data/catalogue), sauvegarde R2 de l'ancien,
#                             sans effet si la base est déjà à jour
#   GBAKI_ADD_CATALOGUE=1     ajoute les matières et documents manquants des CSV, sans rien supprimer
#   GBAKI_INDEX=1             indexation plein texte + vignettes (reprend où elle s'est arrêtée)
#   GBAKI_INDEX_RETRY=1       relance les documents restés sans texte
#   GBAKI_ADMIN_EMAIL + GBAKI_ADMIN_PASSWORD   crée ou promeut ce compte administrateur
#   GBAKI_PURGE_STUDENTS=dry-run   rapport des comptes non admin qui seraient supprimés
#   GBAKI_PURGE_STUDENTS=confirm + GBAKI_PURGE_BEFORE=<date ISO>   les supprime (créés avant la date)
set -u
# Voie d'envoi des codes « mot de passe oublié » (noms seulement, jamais les valeurs)
python manage.py shell -c "from django.conf import settings as s; from core.emailing import gmail_api_configured as g; print('[tasks] email :', 'API Gmail configurée' if g() else ('SMTP seul (bloqué sur Railway)' if s.EMAIL_HOST_USER else 'AUCUNE voie configurée'))"
if [ -n "${GBAKI_ADMIN_EMAIL:-}" ] && [ -n "${GBAKI_ADMIN_PASSWORD:-}" ]; then
  echo "[tasks] create_admin ${GBAKI_ADMIN_EMAIL}"
  python manage.py create_admin --email "$GBAKI_ADMIN_EMAIL" --password "$GBAKI_ADMIN_PASSWORD" --keep-duplicates
fi
case "${GBAKI_PURGE_STUDENTS:-}" in
  dry-run)
    echo "[tasks] purge_students --dry-run"
    python manage.py purge_students --dry-run ${GBAKI_PURGE_BEFORE:+--before "$GBAKI_PURGE_BEFORE"} ;;
  confirm)
    if [ -z "${GBAKI_PURGE_BEFORE:-}" ]; then
      echo "[tasks] purge_students refusé : GBAKI_PURGE_BEFORE manquant"
    else
      echo "[tasks] purge_students --confirm --before $GBAKI_PURGE_BEFORE"
      python manage.py purge_students --confirm --before "$GBAKI_PURGE_BEFORE"
    fi ;;
  "") ;;
  *) echo "[tasks] GBAKI_PURGE_STUDENTS inconnu : ${GBAKI_PURGE_STUDENTS} (dry-run ou confirm)" ;;
esac
if [ "${GBAKI_IMPORT_CATALOGUE:-0}" = "1" ]; then
  echo "[tasks] import_catalogue"
  python manage.py import_catalogue --confirm --if-needed --backup-r2 || { echo "[tasks] import en échec"; exit 1; }
fi
if [ "${GBAKI_ADD_CATALOGUE:-0}" = "1" ]; then
  echo "[tasks] import_catalogue --add-only"
  python manage.py import_catalogue --confirm --add-only || { echo "[tasks] ajout en échec"; exit 1; }
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
