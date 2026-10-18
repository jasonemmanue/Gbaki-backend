"""
Supprime tous les comptes non administrateurs (étudiants de toutes les classes),
pour qu'ils se réinscrivent.

    python manage.py purge_students --dry-run                         # rapport seul
    python manage.py purge_students --confirm
    python manage.py purge_students --confirm --before 2026-10-18T12:00:00

Un admin est un compte de connexion is_staff ou is_superuser. Sont conservés : ces
comptes et les profils portant leur email. Sont supprimés : les autres comptes de
connexion (et leurs tokens), les autres profils et leurs codes OTP. Les documents
envoyés par un profil supprimé restent (uploaded_by passe à vide).

--before ne touche que les comptes créés avant cette date : relancée par erreur,
la commande n'efface pas les réinscriptions. Tout se fait dans une transaction.
"""
from collections import Counter
from datetime import datetime, time

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

from core.models import Document, OTPCode, Profile


def parse_before(value):
    moment = parse_datetime(value)
    if moment is None:
        day = parse_date(value)
        if day is None:
            raise CommandError(f"--before : date illisible « {value} » (attendu 2026-10-18 ou 2026-10-18T12:00:00).")
        moment = datetime.combine(day, time.min)
    if timezone.is_naive(moment):
        moment = timezone.make_aware(moment)
    return moment


class Command(BaseCommand):
    help = "Supprime tous les comptes non administrateurs (profils, comptes de connexion, codes OTP)."

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help="Afficher ce qui serait supprimé, sans rien supprimer.")
        parser.add_argument('--confirm', action='store_true', help="Obligatoire pour supprimer.")
        parser.add_argument('--before', help="Ne supprimer que les comptes créés avant cette date (ISO).")

    def handle(self, *args, **opts):
        dry_run = opts['dry_run']
        if not dry_run and not opts['confirm']:
            raise CommandError("Ajoutez --confirm pour supprimer, ou --dry-run pour un simple rapport.")
        before = parse_before(opts['before']) if opts['before'] else None

        admins = list(User.objects.filter(Q(is_staff=True) | Q(is_superuser=True)))
        if not admins:
            raise CommandError("Aucun compte administrateur : suppression refusée.")
        admin_emails = {e.strip().lower() for u in admins for e in (u.email, u.username) if e}

        users = User.objects.filter(is_staff=False, is_superuser=False)
        if before:
            users = users.filter(date_joined__lt=before)
        profiles = [p for p in Profile.objects.select_related('class_id') if p.email.lower() not in admin_emails]
        if before:
            profiles = [p for p in profiles if p.created_at < before]
        emails = {p.email.lower() for p in profiles} | {u.email.lower() for u in users if u.email}
        otps = [o.pk for o in OTPCode.objects.all() if o.email.lower() in emails]
        uploads = Document.objects.filter(uploaded_by__in=[p.pk for p in profiles]).count()

        self.stdout.write("Admins conservés : " + ", ".join(sorted(u.email or u.username for u in admins)))
        if before:
            self.stdout.write(f"Limité aux comptes créés avant {before.isoformat()}")
        by_class = Counter(p.class_id.code if p.class_id else '(sans classe)' for p in profiles)
        self.stdout.write(f"Profils à supprimer : {len(profiles)}")
        for code, n in sorted(by_class.items()):
            self.stdout.write(f"  {code} : {n}")
        n_users = users.count()
        self.stdout.write(f"Comptes de connexion à supprimer : {n_users}")
        self.stdout.write(f"Codes OTP à supprimer : {len(otps)}")
        if uploads:
            self.stdout.write(f"Documents envoyés par ces profils (conservés, sans auteur) : {uploads}")
        orphan_admins = sorted(p.email for p in profiles if p.role == 'admin')
        if orphan_admins:
            self.stdout.write(self.style.WARNING(
                "Profils role=admin sans compte admin, supprimés aussi : " + ", ".join(orphan_admins)))

        if dry_run:
            self.stdout.write(self.style.WARNING("--dry-run : rien n'a été supprimé."))
            return

        with transaction.atomic():
            users.delete()
            Profile.objects.filter(pk__in=[p.pk for p in profiles]).delete()
            OTPCode.objects.filter(pk__in=otps).delete()
        self.stdout.write(self.style.SUCCESS(
            f"Supprimés : {len(profiles)} profil(s), {n_users} compte(s) de connexion, {len(otps)} code(s) OTP."))
