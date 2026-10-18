import csv
import io
import shutil
import tempfile
from pathlib import Path
from unittest import skipUnless
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from .models import AcademicYear, Class, Document, DocumentPage, DocumentType, OTPCode, Profile, SearchTerm, Subject, Teacher
from .search import analyse_line, parse_query, search_fulltext

CATALOGUE = Path(settings.BASE_DIR) / 'data' / 'catalogue'
NO_R2 = override_settings(CF_R2_ENDPOINT_URL='', CF_R2_ACCESS_KEY='')


def make_catalogue_sample(dest: Path, n_docs=40):
    """Copie des CSV du catalogue avec un extrait des documents (AS1, AS2, AS3, dossiers, type vide)."""
    for name in ('app-annees-academiques.csv', 'app-types-documents.csv', 'app-matieres.csv'):
        shutil.copy(CATALOGUE / name, dest / name)
    with open(CATALOGUE / 'app-documents.csv', encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        fields = reader.fieldnames
    picked = rows[:n_docs]
    picked += [r for r in rows if r['Classe'] in ('AS2', 'AS3')][:10]
    picked += [r for r in rows if r['_projet'] == 'oui'][:2]
    picked += [r for r in rows if not r['_code_type']][:1]
    with open(dest / 'app-documents.csv', 'w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(picked)
    return picked


def make_classes():
    for i, code in enumerate(['AS1', 'AS2', 'AS3', 'ISE 2'], start=1):
        Class.objects.create(code=code, label=code, level_order=i)


@NO_R2
class ImportCatalogueTests(TestCase):
    def setUp(self):
        make_classes()
        self.teacher = Teacher.objects.create(full_name='Dr Test')
        old_year = AcademicYear.objects.create(label='1999-2000', start_year=1999, end_year=2000)
        old_type = DocumentType.objects.create(code='old', label='Old')
        old_subject = Subject.objects.create(name='Ancienne', class_id=Class.objects.get(code='AS1'))
        old_doc = Document.objects.create(
            title='Ancien', file_name='a.pdf', file_path='a.pdf', class_id=Class.objects.get(code='AS1'),
            subject_id=old_subject, academic_year_id=old_year, document_type_id=old_type,
        )
        old_doc.teachers.add(self.teacher)
        self.tmp = Path(tempfile.mkdtemp())
        self.rows = make_catalogue_sample(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_refuses_without_confirm(self):
        with self.assertRaises(CommandError):
            call_command('import_catalogue', dir=str(self.tmp), verbosity=0)
        self.assertEqual(Document.objects.count(), 1)

    def test_import_replaces_catalogue_and_keeps_classes_and_teachers(self):
        call_command('import_catalogue', dir=str(self.tmp), confirm=True, stdout=open(tempfile.mktemp(), 'w', encoding='utf-8'))
        self.assertEqual(AcademicYear.objects.count(), 23)
        self.assertEqual(list(AcademicYear.objects.filter(is_active=True).values_list('label', flat=True)), ['2026-2027'])
        self.assertEqual(DocumentType.objects.count(), 13)
        self.assertEqual(Subject.objects.count(), 133)
        self.assertEqual(Document.objects.count(), len(self.rows))
        self.assertFalse(Document.objects.filter(title='Ancien').exists())
        self.assertEqual(Class.objects.count(), 4)
        self.assertTrue(Teacher.objects.filter(pk=self.teacher.pk).exists())
        self.assertEqual(Document.objects.filter(is_published=True).count(), len(self.rows))
        folder = Document.objects.filter(is_folder=True).first()
        self.assertIsNotNone(folder)
        self.assertTrue(folder.file_path.endswith('/'))
        no_type = [r for r in self.rows if not r['_code_type']][0]
        self.assertEqual(Document.objects.get(file_path=no_type['Chemin Cloudflare R2 (cle objet)']).document_type_id.code, 'DOCUMENT')
        doc = Document.objects.get(file_path=self.rows[0]['Chemin Cloudflare R2 (cle objet)'])
        self.assertEqual(doc.subject_id.code, self.rows[0]['_code_matiere'])
        self.assertEqual(doc.subject_id.class_id.code, 'AS1')


@override_settings(EMAIL_VERIFICATION=False)
class EmailRuleTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_register_requires_ensea_email(self):
        r = self.client.post('/api/auth/register/', {'email': 'jean@gmail.com', 'password': 'secret123'}, format='json')
        self.assertEqual(r.status_code, 400)
        r = self.client.post('/api/auth/register/', {'email': 'jean@ensea.edu', 'password': 'secret123'}, format='json')
        self.assertEqual(r.status_code, 400)
        r = self.client.post('/api/auth/register/', {'email': 'Jean.Kouassi@ensea.edu.ci', 'password': 'secret123'}, format='json')
        self.assertEqual(r.status_code, 201)

    def test_login_blocks_non_ensea_student_but_not_admin(self):
        User.objects.create_user(username='eleve@gmail.com', email='eleve@gmail.com', password='secret123')
        User.objects.create_user(username='admin@gmail.com', email='admin@gmail.com', password='secret123', is_staff=True)
        User.objects.create_user(username='ok@ensea.edu.ci', email='ok@ensea.edu.ci', password='secret123')
        self.assertEqual(self.client.post('/api/auth/login/', {'email': 'eleve@gmail.com', 'password': 'secret123'}, format='json').status_code, 403)
        self.assertEqual(self.client.post('/api/auth/login/', {'email': 'admin@gmail.com', 'password': 'secret123'}, format='json').status_code, 200)
        self.assertEqual(self.client.post('/api/auth/login/', {'email': 'ok@ensea.edu.ci', 'password': 'secret123'}, format='json').status_code, 200)

    def test_existing_token_of_non_ensea_student_is_refused_on_me(self):
        user = User.objects.create_user(username='eleve@gmail.com', email='eleve@gmail.com', password='secret123')
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + Token.objects.create(user=user).key)
        self.assertEqual(self.client.get('/api/auth/me/').status_code, 403)


class EmailVerificationTests(TestCase):
    """Un compte étudiant n'appartient à personne tant que l'adresse n'est pas prouvée par code."""

    def setUp(self):
        self.client = APIClient()
        self.sent = []
        patcher = patch('core.auth_views.send_email', side_effect=lambda to, subject, text, html: self.sent.append(text))
        patcher.start()
        self.addCleanup(patcher.stop)

    def _code(self, email):
        return OTPCode.objects.get(email=email, purpose=OTPCode.PURPOSE_VERIFY).code

    def test_register_requires_code_before_session(self):
        r = self.client.post('/api/auth/register/', {'email': 'jean@ensea.edu.ci', 'password': 'secret123'}, format='json')
        self.assertEqual(r.status_code, 202)
        self.assertNotIn('token', r.data)
        self.assertEqual(len(self.sent), 1)
        bad = '0000' if self._code('jean@ensea.edu.ci') != '0000' else '1111'
        self.assertEqual(self.client.post('/api/auth/verify-email/', {'email': 'jean@ensea.edu.ci', 'code': bad}, format='json').status_code, 400)
        r = self.client.post('/api/auth/verify-email/', {'email': 'jean@ensea.edu.ci', 'code': self._code('jean@ensea.edu.ci')}, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertIn('token', r.data)
        self.assertTrue(Profile.objects.get(email='jean@ensea.edu.ci').email_verified)

    def test_unverified_account_can_be_reclaimed_and_old_token_refused(self):
        user = User.objects.create_user(username='a@ensea.edu.ci', email='a@ensea.edu.ci', password='intrus123')
        Profile.objects.create(email='a@ensea.edu.ci', role='student')
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + Token.objects.create(user=user).key)
        self.assertEqual(self.client.get('/api/auth/me/').status_code, 401)
        self.client.credentials()
        r = self.client.post('/api/auth/register/', {'email': 'a@ensea.edu.ci', 'password': 'vrai1234'}, format='json')
        self.assertEqual(r.status_code, 202)
        self.assertFalse(User.objects.filter(pk=user.pk).exists())

    def test_login_of_unverified_student_sends_code_and_locks_after_5_errors(self):
        User.objects.create_user(username='b@ensea.edu.ci', email='b@ensea.edu.ci', password='secret123')
        r = self.client.post('/api/auth/login/', {'email': 'b@ensea.edu.ci', 'password': 'secret123'}, format='json')
        self.assertEqual(r.status_code, 202)
        bad = '0000' if self._code('b@ensea.edu.ci') != '0000' else '1111'
        for _ in range(5):
            self.client.post('/api/auth/verify-email/', {'email': 'b@ensea.edu.ci', 'code': bad}, format='json')
        self.assertFalse(OTPCode.objects.filter(email='b@ensea.edu.ci').exists())

    def test_admin_is_not_asked_for_code(self):
        User.objects.create_user(username='admin@gmail.com', email='admin@gmail.com', password='secret123', is_staff=True)
        r = self.client.post('/api/auth/login/', {'email': 'admin@gmail.com', 'password': 'secret123'}, format='json')
        self.assertEqual(r.status_code, 200)


@override_settings(EMAIL_VERIFICATION=False)
class ProfilePrivacyTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.a = Profile.objects.create(email='a@ensea.edu.ci', role='student')
        Profile.objects.create(email='b@ensea.edu.ci', role='student')
        self.user = User.objects.create_user(username='a@ensea.edu.ci', email='a@ensea.edu.ci', password='x' * 8)
        self.admin = User.objects.create_user(username='admin', email='admin@gmail.com', password='x' * 8, is_staff=True)

    def test_anonymous_cannot_list_profiles(self):
        self.assertEqual(self.client.get('/api/profiles/').status_code, 401)

    def test_student_sees_only_own_profile(self):
        self.client.force_authenticate(self.user)
        data = self.client.get('/api/profiles/').json()
        self.assertEqual([p['email'] for p in data], ['a@ensea.edu.ci'])
        cls = Class.objects.create(code='AS1', label='AS 1')
        r = self.client.patch(f'/api/profiles/{self.a.id}/', {'class_id': str(cls.id)}, format='json')
        self.assertEqual(r.status_code, 200)

    def test_admin_sees_all(self):
        self.client.force_authenticate(self.admin)
        self.assertEqual(len(self.client.get('/api/profiles/').json()), 2)


def make_documents(n):
    cls = Class.objects.create(code='AS1', label='AS 1')
    subject = Subject.objects.create(name='Probabilités', code='PROBA', class_id=cls)
    year = AcademicYear.objects.create(label='2025-2026', start_year=2025, end_year=2026, is_active=True)
    dtype = DocumentType.objects.create(code='COURS', label='Cours')
    return [
        Document.objects.create(
            title=f'Doc {i:03d}', file_name=f'd{i}.pdf', file_path=f'as1/d{i}.pdf', mime_type='application/pdf',
            class_id=cls, subject_id=subject, academic_year_id=year, document_type_id=dtype, is_published=True,
        )
        for i in range(n)
    ]


@NO_R2
@override_settings(EMAIL_VERIFICATION=False)
class DocumentListTests(TestCase):
    def test_pagination(self):
        make_documents(7)
        client = APIClient()
        data = client.get('/api/documents/?page_size=3&page=3&class_code=AS1').json()
        self.assertEqual(data['count'], 7)
        self.assertEqual(data['num_pages'], 3)
        self.assertEqual(len(data['results']), 1)
        self.assertIn('has_thumbnail', data['results'][0])
        self.assertEqual(client.get('/api/documents/?page=99&page_size=5').json()['page'], 2)

    def test_notifications_today(self):
        make_documents(2)
        self.assertEqual(APIClient().get('/api/notifications/today/').json()['count'], 2)


class LineAnalysisTests(TestCase):
    def test_exact_ignores_accents_and_case(self):
        q = parse_query('intervalle de confiance')
        info = analyse_line('Un Intervalle de Confiance de niveau 1 − α', q)
        self.assertEqual(info['kind'], 'exact')
        self.assertEqual(info['spans'], [[3, 26]])

    def test_close_match_reports_found_word(self):
        q = parse_query('intervalle de confiance')
        info = analyse_line('6.3 Intervalles de confiance', q)
        self.assertEqual(info['kind'], 'close')
        self.assertEqual(info['found'], {'word': 'Intervalles', 'for': 'intervalle'})

    def test_accented_query_matches_plain_text(self):
        q = parse_query('probabilité')
        self.assertEqual(analyse_line('Les lois probabilistes', q)['kind'], 'close')
        self.assertEqual(analyse_line('la probabilite conditionnelle', q)['kind'], 'exact')

    def test_nul_characters_are_removed(self):
        from .text import clean_lines
        self.assertEqual(clean_lines("a\x00b\n\x00\nc"), ["ab", "c"])

    def test_no_match(self):
        self.assertIsNone(analyse_line('rien à voir', parse_query('estimateur')))


@override_settings(EMAIL_VERIFICATION=False)
class FulltextSearchTests(TestCase):
    def setUp(self):
        docs = make_documents(2)
        DocumentPage.objects.create(document=docs[0], page_number=31, content=(
            "Chapitre 6 - Estimation\n6.3 Intervalles de confiance\n"
            "Un intervalle de confiance de niveau 1 - alpha est un intervalle aleatoire"
        ))
        DocumentPage.objects.create(document=docs[1], page_number=2, content="Exercice 2 - Intervalle de confiance (8 points)")
        SearchTerm.objects.bulk_create([SearchTerm(word=w) for w in ['intervalle', 'intervalles', 'confiance', 'estimation']])
        self.docs = docs

    def test_search_returns_page_line_and_kind(self):
        data = search_fulltext('intervalle de confiance')
        self.assertEqual(data['documents_count'], 2)
        first = data['results'][0]
        self.assertEqual(first['kind'], 'exact')
        page31 = [h for h in data['results'] if h['page'] == 31]
        self.assertEqual({(h['line'], h['kind']) for h in page31}, {(2, 'close'), (3, 'exact')})

    def test_endpoint_requires_auth_and_page_lines(self):
        client = APIClient()
        self.assertEqual(client.get('/api/search/fulltext/?q=confiance').status_code, 401)
        client.force_authenticate(User.objects.create_user(username='u', password='x' * 8))
        self.assertEqual(client.get('/api/search/fulltext/?q=confiance').status_code, 200)
        page = client.get(f'/api/documents/{self.docs[0].id}/page/?n=31&q=confiance').json()
        self.assertEqual(len(page['lines']), 3)
        self.assertTrue(page['lines'][1]['spans'])

    @skipUnless(connection.vendor == 'postgresql', "correction orthographique : PostgreSQL uniquement")
    def test_typo_is_corrected(self):
        data = search_fulltext('intervale de confiance')
        self.assertTrue(data['corrections'])
        self.assertGreater(data['count'], 0)


@override_settings(EMAIL_VERIFICATION=False)
class AdminResetPasswordTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.student = User.objects.create_user(username='eleve@ensea.edu.ci', email='eleve@ensea.edu.ci', password='ancien123')
        Token.objects.create(user=self.student)
        self.profile = Profile.objects.create(email='eleve@ensea.edu.ci', role='student')
        self.admin = User.objects.create_user(username='admin', email='admin@gmail.com', password='x' * 8, is_staff=True)
        self.url = f'/api/admin/users/{self.profile.id}/reset-password/'

    def test_admin_resets_password_and_closes_sessions(self):
        self.client.force_authenticate(self.admin)
        r = self.client.post(self.url, {'new_password': 'nouveau2026'}, format='json')
        self.assertEqual(r.status_code, 200)
        self.student.refresh_from_db()
        self.assertTrue(self.student.check_password('nouveau2026'))
        self.assertFalse(Token.objects.filter(user=self.student).exists())

    def test_refused_for_students_and_short_passwords(self):
        self.client.force_authenticate(self.student)
        self.assertEqual(self.client.post(self.url, {'new_password': 'nouveau2026'}, format='json').status_code, 403)
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.client.post(self.url, {'new_password': 'court'}, format='json').status_code, 400)


@override_settings(EMAIL_HOST_USER='gbaki@gmail.com', EMAIL_HOST_PASSWORD='x')
class ForgotPasswordMailFailureTests(TestCase):
    def test_smtp_failure_returns_clear_message(self):
        from unittest import mock
        User.objects.create_user(username='eleve@ensea.edu.ci', email='eleve@ensea.edu.ci', password='x' * 8)
        with mock.patch('core.auth_views.send_email', side_effect=TimeoutError('timed out')):
            r = APIClient().post('/api/auth/forgot-password/', {'email': 'eleve@ensea.edu.ci'}, format='json')
        self.assertEqual(r.status_code, 503)
        self.assertIn('administrateur', r.json()['error'])


@override_settings(GMAIL_API_CLIENT_ID='cid', GMAIL_API_CLIENT_SECRET='secret',
                   GMAIL_API_REFRESH_TOKEN='refresh', GMAIL_API_SENDER='gbaki@gmail.com',
                   EMAIL_HOST_USER='', EMAIL_HOST_PASSWORD='')
class GmailApiTests(TestCase):
    def setUp(self):
        from . import emailing
        emailing._token.update(value=None, expires_at=0.0)
        self.emailing = emailing

    def test_forgot_password_sends_through_gmail_api(self):
        import base64, json
        from email import message_from_bytes
        from unittest import mock
        calls = []

        def fake_post(url, data, headers, timeout):
            calls.append((url, data, headers))
            if url == self.emailing.TOKEN_URL:
                return 200, json.dumps({'access_token': 'tok', 'expires_in': 3600})
            return 200, '{"id": "1"}'

        User.objects.create_user(username='eleve@ensea.edu.ci', email='eleve@ensea.edu.ci', password='x' * 8)
        with mock.patch.object(self.emailing, '_post', side_effect=fake_post):
            r = APIClient().post('/api/auth/forgot-password/', {'email': 'eleve@ensea.edu.ci'}, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertEqual([c[0] for c in calls], [self.emailing.TOKEN_URL, self.emailing.SEND_URL])
        self.assertEqual(calls[1][2]['Authorization'], 'Bearer tok')
        raw = json.loads(calls[1][1])['raw']
        msg = message_from_bytes(base64.urlsafe_b64decode(raw))
        self.assertEqual(msg['To'], 'eleve@ensea.edu.ci')
        code = OTPCode.objects.get(email='eleve@ensea.edu.ci').code
        body = msg.get_payload()[0].get_payload(decode=True).decode()
        self.assertIn(code, body)

    def test_gmail_failure_without_smtp_returns_503_and_drops_code(self):
        from unittest import mock
        User.objects.create_user(username='eleve@ensea.edu.ci', email='eleve@ensea.edu.ci', password='x' * 8)
        with mock.patch.object(self.emailing, '_post', return_value=(400, '{"error": "invalid_grant"}')):
            r = APIClient().post('/api/auth/forgot-password/', {'email': 'eleve@ensea.edu.ci'}, format='json')
        self.assertEqual(r.status_code, 503)
        self.assertFalse(OTPCode.objects.filter(email='eleve@ensea.edu.ci').exists())


@override_settings(EMAIL_VERIFICATION=False)
class DeleteAndReRegisterTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = User.objects.create_user(username='admin', email='admin@gmail.com', password='x' * 8, is_staff=True)

    def test_admin_delete_frees_the_email(self):
        r = self.client.post('/api/auth/register/', {'email': 'junior@ensea.edu.ci', 'password': 'secret123'}, format='json')
        self.assertEqual(r.status_code, 201)
        profile = Profile.objects.get(email='junior@ensea.edu.ci')
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.client.delete(f'/api/profiles/{profile.id}/').status_code, 204)
        self.assertFalse(User.objects.filter(email__iexact='junior@ensea.edu.ci').exists())
        self.client.force_authenticate(None)
        r = self.client.post('/api/auth/register/', {'email': 'junior@ensea.edu.ci', 'password': 'autre1234'}, format='json')
        self.assertEqual(r.status_code, 201)

    def test_orphan_account_from_old_deletion_is_released(self):
        User.objects.create_user(username='junior@ensea.edu.ci', email='junior@ensea.edu.ci', password='ancien123')
        r = self.client.post('/api/auth/register/', {'email': 'junior@ensea.edu.ci', 'password': 'nouveau123'}, format='json')
        self.assertEqual(r.status_code, 201)
        self.assertEqual(User.objects.filter(email__iexact='junior@ensea.edu.ci').count(), 1)

    def test_existing_account_with_profile_still_blocks_register(self):
        self.client.post('/api/auth/register/', {'email': 'junior@ensea.edu.ci', 'password': 'secret123'}, format='json')
        r = self.client.post('/api/auth/register/', {'email': 'junior@ensea.edu.ci', 'password': 'autre1234'}, format='json')
        self.assertEqual(r.status_code, 400)

    def test_admin_cannot_delete_own_profile(self):
        own = Profile.objects.create(email='admin@gmail.com', role='admin')
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.client.delete(f'/api/profiles/{own.id}/').status_code, 400)


class PurgeStudentsTests(TestCase):
    def setUp(self):
        self.as1 = Class.objects.create(code='AS1', label='AS 1')
        self.ise1 = Class.objects.create(code='ISE1', label='ISE 1')
        self.admin = User.objects.create_user(username='admin@gmail.com', email='admin@gmail.com', password='x' * 8, is_staff=True)
        Profile.objects.create(email='admin@gmail.com', role='admin')
        for email, cls in (('a@ensea.edu.ci', self.as1), ('b@ensea.edu.ci', self.ise1), ('c@ensea.edu.ci', None)):
            user = User.objects.create_user(username=email, email=email, password='secret123')
            Token.objects.create(user=user)
            Profile.objects.create(email=email, role='student', class_id=cls)
        User.objects.create_user(username='orphelin@ensea.edu.ci', email='orphelin@ensea.edu.ci', password='secret123')
        OTPCode.objects.create(email='a@ensea.edu.ci', code='1234', expires_at=timezone.now())

    def run_purge(self, *args):
        out = io.StringIO()
        call_command('purge_students', *args, stdout=out)
        return out.getvalue()

    def test_dry_run_deletes_nothing(self):
        out = self.run_purge('--dry-run')
        self.assertIn('Profils à supprimer : 3', out)
        self.assertIn('Comptes de connexion à supprimer : 4', out)
        self.assertEqual(Profile.objects.count(), 4)
        self.assertEqual(User.objects.count(), 5)

    def test_confirm_keeps_only_admins(self):
        self.run_purge('--confirm')
        self.assertEqual(list(User.objects.values_list('email', flat=True)), ['admin@gmail.com'])
        self.assertEqual(list(Profile.objects.values_list('email', flat=True)), ['admin@gmail.com'])
        self.assertFalse(Token.objects.exists())
        self.assertFalse(OTPCode.objects.exists())
        self.assertEqual(Class.objects.count(), 2)

    def test_requires_confirm_or_dry_run(self):
        with self.assertRaises(CommandError):
            call_command('purge_students')
        self.assertEqual(Profile.objects.count(), 4)

    def test_refused_without_any_admin(self):
        self.admin.delete()
        with self.assertRaises(CommandError):
            call_command('purge_students', '--confirm')
        self.assertEqual(Profile.objects.count(), 4)

    def test_before_spares_new_registrations(self):
        cutoff = timezone.now()
        late = User.objects.create_user(username='new@ensea.edu.ci', email='new@ensea.edu.ci', password='secret123')
        Profile.objects.create(email='new@ensea.edu.ci', role='student')
        self.run_purge('--confirm', '--before', cutoff.isoformat())
        self.assertTrue(User.objects.filter(pk=late.pk).exists())
        self.assertEqual(sorted(Profile.objects.values_list('email', flat=True)), ['admin@gmail.com', 'new@ensea.edu.ci'])
