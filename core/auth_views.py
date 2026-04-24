# ================================================================
# gbaki_backend/core/auth_views.py
# ================================================================
from django.contrib.auth.models import User
from django.contrib.auth import authenticate
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from rest_framework.authtoken.models import Token
from .models import Profile


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
