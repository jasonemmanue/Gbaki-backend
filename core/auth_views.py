# ================================================================
# core/auth_views.py  —  OTP stocké en base (compatible serverless)
# ================================================================
from django.contrib.auth.models import User
from django.db.models import Q
from django.contrib.auth import authenticate
from django.conf import settings as django_settings
from django.utils import timezone
from django.utils.html import escape
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from rest_framework.authtoken.models import Token
from .authentication import needs_verification
from .emailing import send_email
from .models import Profile, OTPCode
import logging
import random
import re
import string


# ── Helpers ──────────────────────────────────────────────────────────────────

def _generate_otp() -> str:
    return ''.join(random.choices(string.digits, k=4))


def _generate_reset_token() -> str:
    return ''.join(random.choices(string.ascii_letters + string.digits, k=20))


def _profile_data(profile):
    return {
        'id':             str(profile.id),
        'email':          profile.email,
        'full_name':      profile.full_name or '',
        'role':           profile.role or 'student',
        'class_id':       str(profile.class_id.id) if profile.class_id else None,
        'class_code':     profile.class_id.code    if profile.class_id else None,
        'class_label':    profile.class_id.label   if profile.class_id else None,
        'is_first_login': profile.class_id is None,
        'email_verified': profile.email_verified,
    }


logger = logging.getLogger(__name__)

VERIFY_UNAVAILABLE_ERROR = (
    "L'envoi du code de vérification est momentanément indisponible. Réessaie dans quelques minutes."
)

EMAIL_UNAVAILABLE_ERROR = (
    "L'envoi du code par email est momentanément indisponible. "
    "Demande à un administrateur de réinitialiser ton mot de passe."
)

OTP_MAX_ATTEMPTS = 5   # codes faux acceptés avant d'invalider le code

ENSEA_EMAIL_RE = re.compile(r'^[a-z0-9][a-z0-9._-]*@ensea\.edu\.ci$')
ENSEA_EMAIL_ERROR = "Seules les adresses institutionnelles au format nom@ensea.edu.ci sont acceptées."


def _is_ensea_email(email: str) -> bool:
    return bool(ENSEA_EMAIL_RE.match((email or '').strip().lower()))


def _is_staff(user) -> bool:
    return bool(user.is_superuser or user.is_staff)


def _resolve_role(user):
    if user.is_superuser or user.is_staff:
        return 'admin'
    return 'student'


def _users_by_email(email):
    """Tous les comptes portant cet email, superusers/staff d'abord."""
    return list(
        User.objects.filter(email__iexact=email)
        .order_by('-is_superuser', '-is_staff', 'date_joined')
    )


def _authenticate_by_email(email, password):
    """
    Django authenticate() utilise username, pas email.
    Plusieurs comptes peuvent partager le même email : on tente chaque username
    jusqu'à ce que le mot de passe corresponde, puis on retombe sur l'email
    utilisé directement comme username.
    """
    for user_obj in _users_by_email(email):
        user = authenticate(username=user_obj.username, password=password)
        if user:
            return user
    return authenticate(username=email, password=password)


_CODE_TEXTS = {
    OTPCode.PURPOSE_RESET: (
        'Gbaki-AI : votre code de réinitialisation',
        'Votre code de réinitialisation de mot de passe Gbaki-AI est :',
        "Si vous n'avez pas demandé de réinitialisation, ignorez cet email.",
    ),
    OTPCode.PURPOSE_VERIFY: (
        'Gbaki-AI : confirmez votre adresse ENSEA',
        'Votre code de vérification Gbaki-AI est :',
        "Si vous n'avez pas créé de compte Gbaki-AI, ignorez cet email : "
        "sans ce code, personne ne peut utiliser votre adresse.",
    ),
}


def _send_code(email, name, purpose) -> bool:
    """
    Remplace le code en cours (même usage) par un nouveau code 4 chiffres valable
    10 minutes et l'envoie (API Gmail en priorité, SMTP sinon : core/emailing.py).
    Retourne False si aucun envoi n'a abouti (le code est alors supprimé).
    """
    OTPCode.objects.filter(email=email, purpose=purpose).delete()
    otp = _generate_otp()
    OTPCode.objects.create(email=email, purpose=purpose, code=otp,
                           expires_at=timezone.now() + timezone.timedelta(minutes=10))

    name = name or email.split('@')[0]
    subject, intro, outro = _CODE_TEXTS[purpose]
    text = (
        f"Bonjour {name},\n\n{intro}\n\n    {otp}\n\n"
        f"Ce code est valable 10 minutes.\n{outro}\n\n"
        f"L'équipe Gbaki-AI, ENSEA Data Science Club"
    )
    html = (
        '<div style="font-family:Arial,sans-serif;max-width:460px;margin:auto;color:#1b2430">'
        '<h2 style="margin:0 0 12px">Gbaki-AI</h2>'
        f'<p>Bonjour {escape(name)},</p>'
        f'<p>{escape(intro)}</p>'
        f'<p style="font-size:30px;font-weight:bold;letter-spacing:8px;margin:18px 0">{otp}</p>'
        '<p>Ce code est valable <strong>10 minutes</strong>.</p>'
        f'<p style="color:#6b7480;font-size:13px">{escape(outro)}</p>'
        '<p style="color:#6b7480;font-size:13px">L\'équipe Gbaki-AI, ENSEA Data Science Club</p></div>'
    )
    try:
        send_email(email, subject, text, html)
        return True
    except Exception as e:
        logger.warning("Envoi du code (%s) à %s impossible : %s", purpose, email, e)
        OTPCode.objects.filter(email=email, purpose=purpose).delete()
        return False


def _check_code(email, code, purpose):
    """Retourne (entrée OTP valide, None) ou (None, message d'erreur). Compte les essais faux."""
    entry = OTPCode.objects.filter(email=email, purpose=purpose).order_by('-created_at').first()
    if entry is None:
        return None, 'Aucun code trouvé pour cet email. Demandez un nouveau code.'
    if entry.is_expired():
        entry.delete()
        return None, 'Code expiré. Demandez un nouveau code.'
    if entry.reset_token:
        return None, 'Code déjà utilisé. Demandez un nouveau code.'
    if entry.code != code:
        entry.attempts += 1
        left = OTP_MAX_ATTEMPTS - entry.attempts
        if left <= 0:
            entry.delete()
            return None, "Trop d'essais. Demandez un nouveau code."
        entry.save(update_fields=['attempts'])
        return None, f'Code incorrect. Encore {left} essai{"s" if left > 1 else ""}.'
    return entry, None


def _verification_pending(email):
    return Response({
        'verification_required': True,
        'email': email,
        'message': f'Un code à 4 chiffres a été envoyé à {email}.',
    }, status=status.HTTP_202_ACCEPTED)


# ── Auth classique ───────────────────────────────────────────────────────────

@api_view(['POST'])
@permission_classes([AllowAny])
def register(request):
    """POST /api/auth/register/"""
    email     = request.data.get('email', '').strip().lower()
    password  = request.data.get('password', '')
    full_name = request.data.get('full_name', '').strip()

    if not email or not password:
        return Response({'error': 'Email et mot de passe requis.'}, status=status.HTTP_400_BAD_REQUEST)
    if not _is_ensea_email(email):
        return Response({'error': ENSEA_EMAIL_ERROR}, status=status.HTTP_400_BAD_REQUEST)
    if len(password) < 6:
        return Response({'error': 'Le mot de passe doit contenir au moins 6 caractères.'}, status=status.HTTP_400_BAD_REQUEST)
    existing = User.objects.filter(Q(username__iexact=email) | Q(email__iexact=email))
    profile  = Profile.objects.filter(email__iexact=email).first()
    # On libère l'adresse quand le compte n'appartient à personne :
    # - compte orphelin (profil supprimé depuis l'admin avant la correction de la suppression) ;
    # - compte jamais vérifié par code email (n'importe qui a pu le créer avec cette adresse).
    unclaimed = profile is None or (django_settings.EMAIL_VERIFICATION and not profile.email_verified)
    if existing.exists() and unclaimed \
            and not existing.filter(Q(is_staff=True) | Q(is_superuser=True)).exists():
        existing.delete()
    if existing.exists():
        return Response({'error': 'Un compte avec cet email existe déjà.'}, status=status.HTTP_400_BAD_REQUEST)

    parts = full_name.split(' ', 1) if full_name else ['', '']
    user  = User.objects.create_user(
        username=email, email=email, password=password,
        first_name=parts[0], last_name=parts[1] if len(parts) > 1 else '',
    )
    role = _resolve_role(user)
    profile, _ = Profile.objects.update_or_create(
        email=email,
        defaults={'full_name': full_name or email, 'role': role, 'is_active': True, 'class_id': None,
                  'email_verified': not django_settings.EMAIL_VERIFICATION}
    )
    if django_settings.EMAIL_VERIFICATION:
        if not _send_code(email, user.first_name, OTPCode.PURPOSE_VERIFY):
            user.delete()
            profile.delete()
            return Response({'error': VERIFY_UNAVAILABLE_ERROR}, status=503)
        return _verification_pending(email)

    token, _ = Token.objects.get_or_create(user=user)
    return Response({'token': token.key, 'is_first_login': True, 'profile': _profile_data(profile)}, status=status.HTTP_201_CREATED)


@api_view(['POST'])
@permission_classes([AllowAny])
def login_view(request):
    """POST /api/auth/login/"""
    email    = request.data.get('email', '').strip().lower()
    password = request.data.get('password', '')

    if not email or not password:
        return Response({'error': 'Email et mot de passe requis.'}, status=status.HTTP_400_BAD_REQUEST)

    user = _authenticate_by_email(email, password)
    if not user:
        return Response({'error': 'Email ou mot de passe incorrect.'}, status=status.HTTP_401_UNAUTHORIZED)
    if not user.is_active:
        return Response({'error': 'Compte désactivé.'}, status=status.HTTP_403_FORBIDDEN)
    if not _is_staff(user) and not _is_ensea_email(email):
        return Response({'error': ENSEA_EMAIL_ERROR}, status=status.HTTP_403_FORBIDDEN)
    if needs_verification(user):
        if not _send_code(email, user.first_name, OTPCode.PURPOSE_VERIFY):
            return Response({'error': VERIFY_UNAVAILABLE_ERROR}, status=503)
        return _verification_pending(email)

    return _session_response(user, email)


def _session_response(user, email):
    """Profil créé ou mis à jour, jeton de session : la réponse d'une connexion réussie."""
    role         = _resolve_role(user)
    display_name = f"{user.first_name} {user.last_name}".strip() or user.email or email

    profile = Profile.objects.select_related('class_id').filter(email__iexact=email).first()
    if profile is None:
        profile = Profile.objects.create(
            email=email, full_name=display_name, role=role, is_active=True
        )

    needs_save = False
    if (user.is_superuser or user.is_staff) and profile.role != 'admin':
        profile.role = 'admin'
        needs_save = True
    if not profile.full_name:
        profile.full_name = display_name
        needs_save = True
    if needs_save:
        profile.save()

    token, _ = Token.objects.get_or_create(user=user)
    return Response({
        'token': token.key,
        'is_first_login': profile.class_id is None,
        'profile': _profile_data(profile),
    })


@api_view(['POST'])
@permission_classes([AllowAny])
def verify_email(request):
    """
    POST /api/auth/verify-email/
    Body : { "email": "nom@ensea.edu.ci", "code": "1234" }

    Valide le code envoyé à l'inscription (ou à la 1re connexion), marque l'adresse
    comme vérifiée et ouvre la session (même réponse que /auth/login/).
    """
    email = request.data.get('email', '').strip().lower()
    code  = request.data.get('code', '').strip()
    if not email or not code:
        return Response({'error': 'Email et code requis.'}, status=400)

    entry, error = _check_code(email, code, OTPCode.PURPOSE_VERIFY)
    if error:
        return Response({'error': error}, status=400)

    users = [u for u in _users_by_email(email) if u.is_active]
    if not users:
        entry.delete()
        return Response({'error': 'Compte introuvable. Recommence l\'inscription.'}, status=404)

    entry.delete()
    profile = Profile.objects.filter(email__iexact=email).first()
    if profile is None:
        Profile.objects.create(email=email, full_name=users[0].get_full_name() or email,
                               role=_resolve_role(users[0]), is_active=True, email_verified=True)
    elif not profile.email_verified:
        profile.email_verified = True
        profile.save(update_fields=['email_verified'])
    return _session_response(users[0], email)


@api_view(['POST'])
@permission_classes([AllowAny])
def resend_verification(request):
    """
    POST /api/auth/resend-verification/
    Body : { "email": "nom@ensea.edu.ci" }   — renvoie un code si le compte attend sa vérification.
    """
    email = request.data.get('email', '').strip().lower()
    users = _users_by_email(email) if email else []
    if users and needs_verification(users[0]):
        if not _send_code(email, users[0].first_name, OTPCode.PURPOSE_VERIFY):
            return Response({'error': VERIFY_UNAVAILABLE_ERROR}, status=503)
    return Response({'message': 'Si ce compte attend sa vérification, un nouveau code a été envoyé.'})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def logout_view(request):
    try:
        request.user.auth_token.delete()
    except Exception:
        pass
    return Response({'message': 'Déconnecté.'})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def me(request):
    email = (request.user.email or request.user.username).strip().lower()
    role  = _resolve_role(request.user)
    if not _is_staff(request.user) and not _is_ensea_email(email):
        return Response({'error': ENSEA_EMAIL_ERROR}, status=status.HTTP_403_FORBIDDEN)

    profile = Profile.objects.select_related('class_id').filter(email__iexact=email).first()
    if profile is None:
        profile = Profile.objects.create(
            email=email,
            full_name=request.user.get_full_name() or email,
            role=role,
            is_active=True,
        )
    elif (request.user.is_superuser or request.user.is_staff) and profile.role != 'admin':
        profile.role = 'admin'
        profile.save(update_fields=['role'])

    return Response(_profile_data(profile))


# ── Mot de passe oublié — OTP stocké en base ─────────────────────────────────

@api_view(['POST'])
@permission_classes([AllowAny])
def forgot_password(request):
    """
    POST /api/auth/forgot-password/
    Body : { "email": "user@example.com" }

    Génère un OTP 4 chiffres, l'envoie par email et le persiste en base.
    Expire après 10 minutes. Les anciens OTP pour cet email sont supprimés.
    """
    email = request.data.get('email', '').strip().lower()
    if not email:
        return Response({'error': 'Email requis.'}, status=400)

    users = _users_by_email(email)
    if users and not _is_staff(users[0]) and not _is_ensea_email(email):
        return Response({'error': ENSEA_EMAIL_ERROR}, status=400)
    if not users:
        # Réponse générique pour ne pas révéler les comptes existants
        return Response({'message': 'Si cet email est enregistré, un code vous a été envoyé.'})
    user = users[0]

    if not _send_code(email, user.first_name, OTPCode.PURPOSE_RESET):
        return Response({'error': EMAIL_UNAVAILABLE_ERROR}, status=503)

    return Response({'message': 'Si cet email est enregistré, un code vous a été envoyé.'})


@api_view(['POST'])
@permission_classes([AllowAny])
def verify_otp(request):
    """
    POST /api/auth/verify-otp/
    Body : { "email": "user@example.com", "code": "1234" }

    Vérifie l'OTP en base. Si valide, génère un reset_token (15 min) et le persiste.
    """
    email = request.data.get('email', '').strip().lower()
    code  = request.data.get('code', '').strip()

    if not email or not code:
        return Response({'error': 'Email et code requis.'}, status=400)

    entry, error = _check_code(email, code, OTPCode.PURPOSE_RESET)
    if error:
        return Response({'error': error}, status=400)

    # Code valide → générer un reset_token et prolonger la validité à 15 min
    reset_token        = _generate_reset_token()
    entry.reset_token  = reset_token
    entry.expires_at   = timezone.now() + timezone.timedelta(minutes=15)
    entry.save(update_fields=['reset_token', 'expires_at'])

    return Response({'reset_token': reset_token, 'email': email})


@api_view(['POST'])
@permission_classes([AllowAny])
def reset_password(request):
    """
    POST /api/auth/reset-password/
    Body : { "email": "...", "reset_token": "...", "new_password": "..." }

    Vérifie le reset_token en base, met à jour le mot de passe, supprime l'OTP.
    """
    email        = request.data.get('email', '').strip().lower()
    reset_token  = request.data.get('reset_token', '').strip()
    new_password = request.data.get('new_password', '')

    if not email or not reset_token or not new_password:
        return Response({'error': 'Champs manquants.'}, status=400)
    if len(new_password) < 6:
        return Response({'error': 'Le mot de passe doit contenir au moins 6 caractères.'}, status=400)

    entry = OTPCode.objects.filter(email=email, purpose=OTPCode.PURPOSE_RESET).order_by('-created_at').first()
    if entry is None or not entry.reset_token:
        return Response({'error': 'Token invalide ou expiré.'}, status=400)

    if entry.reset_token != reset_token:
        return Response({'error': 'Token invalide.'}, status=400)

    if entry.is_expired():
        entry.delete()
        return Response({'error': 'Session expirée. Recommencez la procédure.'}, status=400)

    # Mettre à jour le mot de passe (sur tous les comptes portant cet email)
    users = _users_by_email(email)
    if not users:
        return Response({'error': 'Utilisateur introuvable.'}, status=404)
    for user in users:
        user.set_password(new_password)
        user.save()
        Token.objects.filter(user=user).delete()   # invalider les sessions actives

    # Le code reçu par email prouve que l'adresse appartient bien à l'utilisateur
    Profile.objects.filter(email__iexact=email).update(email_verified=True)

    # Supprimer l'OTP utilisé
    entry.delete()

    return Response({'message': 'Mot de passe réinitialisé avec succès. Vous pouvez vous connecter.'})


# ── Administration : réinitialisation du mot de passe d'un utilisateur ───────

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def admin_reset_password(request, profile_id):
    """
    POST /api/admin/users/<profile_id>/reset-password/
    Body : { "new_password": "..." }  (réservé aux comptes staff / superuser)

    Remplace le mot de passe de tous les comptes portant l'email du profil et
    ferme leurs sessions. Sert notamment quand l'envoi d'email est indisponible.
    """
    if not _is_staff(request.user):
        return Response({'error': 'Réservé aux administrateurs.'}, status=status.HTTP_403_FORBIDDEN)

    new_password = request.data.get('new_password', '')
    if len(new_password) < 8:
        return Response({'error': 'Le nouveau mot de passe doit contenir au moins 8 caractères.'},
                        status=status.HTTP_400_BAD_REQUEST)

    profile = Profile.objects.filter(pk=profile_id).first()
    if profile is None:
        return Response({'error': 'Profil introuvable.'}, status=status.HTTP_404_NOT_FOUND)

    users = _users_by_email(profile.email)
    if not users:
        return Response({'error': "Aucun compte de connexion n'est lié à ce profil."},
                        status=status.HTTP_404_NOT_FOUND)
    for user in users:
        user.set_password(new_password)
        user.save(update_fields=['password'])
        Token.objects.filter(user=user).delete()
    OTPCode.objects.filter(email__iexact=profile.email).delete()

    logger.info("Mot de passe de %s réinitialisé par %s", profile.email, request.user.email or request.user.username)
    return Response({'message': f'Mot de passe de {profile.email} réinitialisé.'})
