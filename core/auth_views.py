# ================================================================
# gbaki_backend/core/auth_views.py
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
from .models import Profile
import random
import string

# Stockage temporaire des codes OTP en mémoire
# { email: { 'code': '1234', 'expires': datetime } }
_otp_store: dict = {}


def _generate_otp() -> str:
    return ''.join(random.choices(string.digits, k=4))


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
    """Superuser ou staff Django => toujours 'admin'."""
    if user.is_superuser or user.is_staff:
        return 'admin'
    return 'student'


def _authenticate_by_email(email, password):
    """
    Django authenticate() utilise username, pas email.
    On cherche d'abord le User par email, puis on tente avec son username.
    Cela permet : admin@ensea.ed.ci + admin1234 -> trouve User(username='admin').
    """
    # 1. Chercher le User dont l'email correspond
    try:
        user_obj = User.objects.get(email__iexact=email)
        username = user_obj.username
    except User.DoesNotExist:
        # 2. Fallback : peut-être que username == email (comptes étudiants)
        username = email

    return authenticate(username=username, password=password)


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
        return Response({'error': 'Le mot de passe doit contenir au moins 6 caracteres.'}, status=status.HTTP_400_BAD_REQUEST)
    if User.objects.filter(username=email).exists():
        return Response({'error': 'Un compte avec cet email existe deja.'}, status=status.HTTP_400_BAD_REQUEST)

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
    """POST /api/auth/login/ — accepte email même si username != email (ex: superuser)"""
    email    = request.data.get('email', '').strip().lower()
    password = request.data.get('password', '')

    if not email or not password:
        return Response({'error': 'Email et mot de passe requis.'}, status=status.HTTP_400_BAD_REQUEST)

    # Authentification par email (résout le cas admin@ensea.ed.ci -> username=admin)
    user = _authenticate_by_email(email, password)
    if not user:
        return Response({'error': 'Email ou mot de passe incorrect.'}, status=status.HTTP_401_UNAUTHORIZED)
    if not user.is_active:
        return Response({'error': 'Compte desactive.'}, status=status.HTTP_403_FORBIDDEN)

    role = _resolve_role(user)
    display_name = (f"{user.first_name} {user.last_name}".strip() or user.email or email)

    # Créer/récupérer le Profile lié à cet email
    profile, _ = Profile.objects.get_or_create(
        email=email,
        defaults={'full_name': display_name, 'role': role, 'is_active': True}
    )

    # Toujours synchro le rôle pour superuser/staff
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
    return Response({'message': 'Deconnecte.'})


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


# ── Mot de passe oublié ─────────────────────────────────────────────────────

@api_view(['POST'])
@permission_classes([AllowAny])
def forgot_password(request):
    """
    POST /api/auth/forgot-password/
    Body : { "email": "user@example.com" }

    Génère un OTP 4 chiffres, l'envoie par email, le stocke en mémoire 10 min.
    Répond toujours 200 (pour ne pas révéler si l'email existe ou non).
    """
    email = request.data.get('email', '').strip().lower()
    if not email:
        return Response({'error': 'Email requis.'}, status=400)

    # Vérifier que l'email existe en base
    try:
        user = User.objects.get(email__iexact=email)
    except User.DoesNotExist:
        # Réponse générique pour ne pas révéler les comptes existants
        return Response({'message': 'Si cet email est enregistré, un code vous a été envoyé.'})

    # Générer l'OTP
    otp = _generate_otp()
    _otp_store[email] = {
        'code': otp,
        'expires': timezone.now() + timezone.timedelta(minutes=10),
    }

    # Envoyer l'email
    email_user = django_settings.EMAIL_HOST_USER
    email_pass = django_settings.EMAIL_HOST_PASSWORD

    if not email_user or not email_pass:
        return Response(
            {'error': f'Configuration email manquante. EMAIL_HOST_USER="{email_user}" non défini dans .env.'},
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

    Vérifie que le code est valide et non expiré.
    Répond 200 + reset_token si OK, 400 sinon.
    """
    email = request.data.get('email', '').strip().lower()
    code  = request.data.get('code', '').strip()

    if not email or not code:
        return Response({'error': 'Email et code requis.'}, status=400)

    entry = _otp_store.get(email)
    if not entry:
        return Response({'error': 'Aucun code trouvé pour cet email.'}, status=400)
    if timezone.now() > entry['expires']:
        del _otp_store[email]
        return Response({'error': 'Code expiré. Demandez un nouveau code.'}, status=400)
    if entry['code'] != code:
        return Response({'error': 'Code incorrect.'}, status=400)

    # Code valide → on génère un reset_token éphémère (20 chars) et on l'associe à l'email
    reset_token = ''.join(random.choices(string.ascii_letters + string.digits, k=20))
    # On réutilise _otp_store pour stocker le reset_token 15 min
    _otp_store[email] = {
        'code': code,
        'reset_token': reset_token,
        'expires': timezone.now() + timezone.timedelta(minutes=15),
    }

    return Response({'reset_token': reset_token, 'email': email})


@api_view(['POST'])
@permission_classes([AllowAny])
def reset_password(request):
    """
    POST /api/auth/reset-password/
    Body : { "email": "...", "reset_token": "...", "new_password": "..." }

    Vérifie le reset_token, met à jour le mot de passe, invalide le token.
    """
    email       = request.data.get('email', '').strip().lower()
    reset_token = request.data.get('reset_token', '').strip()
    new_password = request.data.get('new_password', '')

    if not email or not reset_token or not new_password:
        return Response({'error': 'Champs manquants.'}, status=400)
    if len(new_password) < 6:
        return Response({'error': 'Le mot de passe doit contenir au moins 6 caractères.'}, status=400)

    entry = _otp_store.get(email)
    if not entry or entry.get('reset_token') != reset_token:
        return Response({'error': 'Token invalide ou expiré.'}, status=400)
    if timezone.now() > entry['expires']:
        del _otp_store[email]
        return Response({'error': 'Session expirée. Recommencez la procédure.'}, status=400)

    # Mettre à jour le mot de passe
    try:
        user = User.objects.get(email__iexact=email)
        user.set_password(new_password)
        user.save()
        # Invalider tous les tokens de session existants
        Token.objects.filter(user=user).delete()
    except User.DoesNotExist:
        return Response({'error': 'Utilisateur introuvable.'}, status=404)

    # Nettoyer l'OTP store
    del _otp_store[email]

    return Response({'message': 'Mot de passe réinitialisé avec succès. Vous pouvez vous connecter.'})
