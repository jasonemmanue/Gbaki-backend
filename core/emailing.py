"""
core/emailing.py — envoi d'emails, même principe que Prepaxia :

  1. API HTTP Gmail (OAuth2, refresh_token)  ← sur Railway (le SMTP sortant y est bloqué)
  2. SMTP Gmail (EMAIL_HOST_USER / EMAIL_HOST_PASSWORD) ← en local

Variables pour l'API Gmail : GMAIL_API_CLIENT_ID, GMAIL_API_CLIENT_SECRET,
GMAIL_API_REFRESH_TOKEN, GMAIL_API_SENDER (voir DEPLOY_RAILWAY.md).
"""
import base64
import json
import logging
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr

from django.conf import settings
from django.core.mail import EmailMultiAlternatives

logger = logging.getLogger(__name__)

TOKEN_URL = 'https://oauth2.googleapis.com/token'
SEND_URL = 'https://gmail.googleapis.com/gmail/v1/users/me/messages/send'
FROM_NAME = 'Gbaki-AI · ENSEA Data Science Club'

# Jeton d'accès Gmail mis en cache (valable ~1 h) pour ne pas le rafraîchir à chaque envoi
_token_lock = threading.Lock()
_token = {'value': None, 'expires_at': 0.0}


class EmailError(Exception):
    """Aucune voie d'envoi n'a fonctionné."""


def gmail_api_configured() -> bool:
    return all((settings.GMAIL_API_CLIENT_ID, settings.GMAIL_API_CLIENT_SECRET,
                settings.GMAIL_API_REFRESH_TOKEN, settings.GMAIL_API_SENDER))


def _post(url, data: bytes, headers: dict, timeout: int):
    req = urllib.request.Request(url, data=data, headers=headers, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode('utf-8', 'replace')
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode('utf-8', 'replace')


def _gmail_access_token() -> str:
    with _token_lock:
        if _token['value'] and time.time() < _token['expires_at'] - 60:
            return _token['value']
        status, body = _post(TOKEN_URL, urllib.parse.urlencode({
            'client_id': settings.GMAIL_API_CLIENT_ID,
            'client_secret': settings.GMAIL_API_CLIENT_SECRET,
            'refresh_token': settings.GMAIL_API_REFRESH_TOKEN,
            'grant_type': 'refresh_token',
        }).encode(), {'Content-Type': 'application/x-www-form-urlencoded'}, settings.EMAIL_TIMEOUT)
        if status != 200:
            raise EmailError(f"Gmail OAuth HTTP {status} : {body[:200]}")
        data = json.loads(body)
        _token['value'] = data['access_token']
        _token['expires_at'] = time.time() + int(data.get('expires_in', 3600))
        return _token['value']


def _send_gmail_api(to: str, subject: str, text: str, html: str | None):
    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From'] = formataddr((FROM_NAME, settings.GMAIL_API_SENDER))
    msg['To'] = to
    msg.attach(MIMEText(text, 'plain', 'utf-8'))
    if html:
        msg.attach(MIMEText(html, 'html', 'utf-8'))
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    status, body = _post(SEND_URL, json.dumps({'raw': raw}).encode(), {
        'Authorization': f'Bearer {_gmail_access_token()}',
        'Content-Type': 'application/json',
    }, settings.EMAIL_TIMEOUT)
    if status not in (200, 202):
        if status == 401:   # jeton révoqué ou expiré : on forcera un rafraîchissement
            _token['value'] = None
        raise EmailError(f"Gmail API HTTP {status} : {body[:200]}")


def _send_smtp(to: str, subject: str, text: str, html: str | None):
    if not (settings.EMAIL_HOST_USER and settings.EMAIL_HOST_PASSWORD):
        raise EmailError('SMTP non configuré (EMAIL_HOST_USER / EMAIL_HOST_PASSWORD).')
    mail = EmailMultiAlternatives(subject, text, formataddr((FROM_NAME, settings.EMAIL_HOST_USER)), [to])
    if html:
        mail.attach_alternative(html, 'text/html')
    mail.send(fail_silently=False)


def send_email(to: str, subject: str, text: str, html: str | None = None) -> str:
    """Envoie un email ; retourne la voie utilisée ('gmail_api' ou 'smtp'), sinon lève EmailError."""
    errors = []
    if gmail_api_configured():
        try:
            _send_gmail_api(to, subject, text, html)
            logger.info("Email envoyé via l'API Gmail à %s : %s", to, subject)
            return 'gmail_api'
        except Exception as exc:   # on tente encore le SMTP
            errors.append(f'API Gmail : {exc}')
            logger.warning("API Gmail en échec pour %s : %s", to, exc)
    try:
        _send_smtp(to, subject, text, html)
        logger.info("Email envoyé via SMTP à %s : %s", to, subject)
        return 'smtp'
    except Exception as exc:
        errors.append(f'SMTP : {exc}')
    raise EmailError(' | '.join(errors))
