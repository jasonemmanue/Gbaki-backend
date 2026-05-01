# ================================================================
# core/auth_views.py  —  OTP stocké en base (compatible serverless)
# ================================================================
from django.contrib.auth.models import User
from django.contrib.auth import authenticate
from django.core.mail import send_mail
from django.conf import settings as django_settings
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from rest_framework.authtoken.models import Token
from .models import Profile, OTPCode
import random
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
    }


def _resolve_role(user):
    if user.is_superuser or user.is_staff:
        return 'admin'
    return 'student'


def _authenticate_by_email(email, password):
    """
    Django authenticate() utilise username, pas email.
    On cherche d'abord le User par email, puis on tente avec son username.
    """
    try:
        user_obj = User.objects.get(email__iexact=email)
        username = user_obj.username
    except User.DoesNotExist:
        username = email
    return authenticate(username=username, password=password)


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
    if len(password) < 6:
        return Response({'error': 'Le mot de passe doit contenir au moins 6 caractères.'}, status=status.HTTP_400_BAD_REQUEST)
    if User.objects.filter(username=email).exists():
        return Response({'error': 'Un compte avec cet email existe déjà.'}, status=status.HTTP_400_BAD_REQUEST)

    parts = full_name.split(' ', 1) if full_name else ['', '']
    user  = User.objects.create_user(
        username=email, email=email, password=password,
        first_name=parts[0], last_name=parts[1] if len(parts) > 1 else '',
    )
    role = _resolve_role(user)
    profile, _ = Profile.objects.update_or_create(
        email=email,
        defaults={'full_name': full_name or email, 'role': role, 'is_active': True, 'class_id': None}
    )
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

    role         = _resolve_role(user)
    display_name = f"{user.first_name} {user.last_name}".strip() or user.email or email

    profile, _ = Profile.objects.get_or_create(
        email=email,
        defaults={'full_name': display_name, 'role': role, 'is_active': True}
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
    email = request.user.email
    role  = _resolve_role(request.user)
    try:
        profile = Profile.objects.select_related('class_id').get(email=email)
        if (request.user.is_superuser or request.user.is_staff) and profile.role != 'admin':
            profile.role = 'admin'
            profile.save(update_fields=['role'])
    except Profile.DoesNotExist:
        profile = Profile.objects.create(
            email=email,
            full_name=request.user.get_full_name() or email,
            role=role,
            is_active=True,
        )
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

    try:
        user = User.objects.get(email__iexact=email)
    except User.DoesNotExist:
        # Réponse générique pour ne pas révéler les comptes existants
        return Response({'message': 'Si cet email est enregistré, un code vous a été envoyé.'})

    # Supprimer tous les anciens OTP pour cet email (nettoyage)
    OTPCode.objects.filter(email=email).delete()

    # Créer le nouvel OTP en base
    otp        = _generate_otp()
    expires_at = timezone.now() + timezone.timedelta(minutes=10)
    OTPCode.objects.create(email=email, code=otp, expires_at=expires_at)

    # Envoyer l'email
    email_user = django_settings.EMAIL_HOST_USER
    email_pass = django_settings.EMAIL_HOST_PASSWORD

    if not email_user or not email_pass:
        return Response(
            {'error': f'Configuration email manquante. EMAIL_HOST_USER non défini.'},
            status=500
        )

    try:
        send_mail(
            subject='GBAKI — Votre code de réinitialisation',
            message=(
                f"Bonjour {user.first_name or user.email},\n\n"
                f"Votre code de réinitialisation de mot de passe est :\n\n"
                f"    {otp}\n\n"
                f"Ce code est valable 10 minutes.\n"
                f"Si vous n'avez pas demandé de réinitialisation, ignorez cet email.\n\n"
                f"— L'équipe GBAKI / ENSEA Data Science Club"
            ),
            from_email=email_user,
            recipient_list=[email],
            fail_silently=False,
        )
    except Exception as e:
        return Response({'error': f'Erreur envoi email : {str(e)}'}, status=500)

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

    # Chercher le dernier OTP actif pour cet email
    try:
        entry = OTPCode.objects.filter(email=email).latest('created_at')
    except OTPCode.DoesNotExist:
        return Response({'error': 'Aucun code trouvé pour cet email.'}, status=400)

    if entry.is_expired():
        entry.delete()
        return Response({'error': 'Code expiré. Demandez un nouveau code.'}, status=400)

    if entry.code != code:
        return Response({'error': 'Code incorrect.'}, status=400)

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

    try:
        entry = OTPCode.objects.filter(email=email).latest('created_at')
    except OTPCode.DoesNotExist:
        return Response({'error': 'Token invalide ou expiré.'}, status=400)

    if entry.reset_token != reset_token:
        return Response({'error': 'Token invalide.'}, status=400)

    if entry.is_expired():
        entry.delete()
        return Response({'error': 'Session expirée. Recommencez la procédure.'}, status=400)

    # Mettre à jour le mot de passe
    try:
        user = User.objects.get(email__iexact=email)
        user.set_password(new_password)
        user.save()
        Token.objects.filter(user=user).delete()   # invalider les sessions actives
    except User.DoesNotExist:
        return Response({'error': 'Utilisateur introuvable.'}, status=404)

    # Supprimer l'OTP utilisé
    entry.delete()

    return Response({'message': 'Mot de passe réinitialisé avec succès. Vous pouvez vous connecter.'})
