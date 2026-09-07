"""
Crée ou promeut un compte administrateur.

    python manage.py create_admin --email admin@gmail.com --password 'MotDePasse'

Si des comptes portant déjà cet email existent, ils sont fusionnés : le premier
est conservé et promu admin, les autres sont supprimés (--keep-duplicates pour
les conserver).
"""
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from rest_framework.authtoken.models import Token

from core.models import Profile


class Command(BaseCommand):
    help = "Crée ou promeut un compte administrateur à partir d'un email et d'un mot de passe."

    def add_arguments(self, parser):
        parser.add_argument('--email', required=True)
        parser.add_argument('--password', required=True)
        parser.add_argument('--full-name', default='')
        parser.add_argument(
            '--keep-duplicates',
            action='store_true',
            help="Ne pas supprimer les autres comptes partageant cet email.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        email = options['email'].strip().lower()
        password = options['password']
        full_name = options['full_name'].strip()

        if len(password) < 6:
            raise CommandError('Le mot de passe doit contenir au moins 6 caractères.')

        matches = list(
            User.objects.filter(email__iexact=email)
            .order_by('-is_superuser', '-is_staff', 'date_joined')
        )

        if matches:
            user = matches[0]
            duplicates = matches[1:]
            if duplicates and not options['keep_duplicates']:
                for dup in duplicates:
                    self.stdout.write(f'Suppression du doublon : {dup.username} (id={dup.pk})')
                    dup.delete()
            elif duplicates:
                self.stdout.write(
                    self.style.WARNING(f'{len(duplicates)} doublon(s) conservé(s) pour {email}.')
                )
        else:
            user = User(username=email)

        user.email = email
        user.is_staff = True
        user.is_superuser = True
        user.is_active = True
        if full_name:
            parts = full_name.split(' ', 1)
            user.first_name = parts[0]
            user.last_name = parts[1] if len(parts) > 1 else ''
        user.set_password(password)
        user.save()

        Token.objects.filter(user=user).delete()

        display_name = full_name or user.get_full_name() or email
        Profile.objects.update_or_create(
            email=email,
            defaults={'full_name': display_name, 'role': 'admin', 'is_active': True},
        )

        self.stdout.write(self.style.SUCCESS(
            f'Admin prêt : {email} (username={user.username})'
        ))
