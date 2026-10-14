"""Jeton DRF refusé tant que l'étudiant n'a pas vérifié son adresse email."""
from django.conf import settings
from rest_framework import exceptions
from rest_framework.authentication import TokenAuthentication

from .models import Profile

NOT_VERIFIED_ERROR = "Adresse email non vérifiée. Reconnecte-toi pour recevoir ton code."


def needs_verification(user) -> bool:
    if not settings.EMAIL_VERIFICATION or user.is_staff or user.is_superuser:
        return False
    email = (user.email or user.username).strip().lower()
    return not Profile.objects.filter(email__iexact=email, email_verified=True).exists()


class VerifiedTokenAuthentication(TokenAuthentication):
    def authenticate_credentials(self, key):
        user, token = super().authenticate_credentials(key)
        if needs_verification(user):
            raise exceptions.AuthenticationFailed(NOT_VERIFIED_ERROR)
        return user, token
