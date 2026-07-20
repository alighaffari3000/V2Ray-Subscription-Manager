# -*- coding: utf-8 -*-
"""Integration tests for V2Ray Subscription Manager.

Covers: login page rendering, CRUD operations, path handling, subscriptions,
filters, statistics response shapes, chart data compatibility, and
form-encoded validation.
"""

import json
import os
import tempfile
import unittest

from werkzeug.security import generate_password_hash

# Patch env vars before importing anything else
_TEST_USERNAME = 'testadmin'
_TEST_PASSWORD = 'testpassword123'
_TEST_PASSWORD_HASH = generate_password_hash(_TEST_PASSWORD)

os.environ['ADMIN_USERNAME'] = _TEST_USERNAME
os.environ['ADMIN_PASSWORD'] = _TEST_PASSWORD_HASH
os.environ['SECRET_KEY'] = 'test-secret-key-for-integration'


class IntegrationTestBase(unittest.TestCase):
    """Base class that sets up a fresh app + temp database for each test."""

    def setUp(self):
        self.db_fd, self.db_path = tempfile.mkstemp(suffix='.db')

        # Point config and constants to temp database
        import utils.constants
        utils.constants.DATABASE = self.db_path

        from config import Config
        Config.ADMIN_USERNAME = _TEST_USERNAME
        Config.ADMIN_PASSWORD = _TEST_PASSWORD_HASH

        from app_factory import create_app
        self.app = create_app(testing=True)
        self.client = self.app.test_client()

    def tearDown(self):
        try:
            from services.automation_service import SCAN_LOCK, terminate_all_subprocesses
            if SCAN_LOCK.locked():
                SCAN_LOCK.release()
            terminate_all_subprocesses()
            import time
            time.sleep(0.3)
        except Exception:
            pass
        os.close(self.db_fd)
        try:
            os.unlink(self.db_path)
        except Exception:
            pass

    def _login(self):
        """Log in as admin and return the response."""
        return self.client.post('/adminpanel/login', data={
            'username': _TEST_USERNAME,
            'password': _TEST_PASSWORD,
        }, follow_redirects=True)


class TestRootRoute(IntegrationTestBase):
    """Issue 6: Root route should redirect to admin panel."""

    def test_root_redirects(self):
        resp = self.client.get('/')
        self.assertIn(resp.status_code, (301, 302, 308))
        self.assertIn('/adminpanel', resp.headers.get('Location', ''))


class TestLogin(IntegrationTestBase):
    """Issue 1: Authentication with hashed password."""

    def test_login_page_renders(self):
        """Login page should return 200 without Jinja BuildError."""
        resp = self.client.get('/adminpanel/login')
        self.assertEqual(resp.status_code, 200)

    def test_login_page_contains_valid_form_action(self):
        """Login page form action should reference admin_pages.login endpoint."""
        resp = self.client.get('/adminpanel/login')
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode('utf-8')
        # Should contain a form action pointing to /adminpanel/login
        self.assertIn('/adminpanel/login', html)
        self.assertIn('<form', html)

    def test_login_success(self):
        resp = self.client.post('/adminpanel/login', data={
            'username': _TEST_USERNAME,
            'password': _TEST_PASSWORD,
        }, follow_redirects=False)
        self.assertIn(resp.status_code, (301, 302))
        self.assertIn('/adminpanel', resp.headers.get('Location', ''))

    def test_login_wrong_password(self):
        resp = self.client.post('/adminpanel/login', data={
            'username': _TEST_USERNAME,
            'password': 'wrongpass',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertIn('اشتباه', resp.data.decode('utf-8'))

    def test_admin_requires_login(self):
        resp = self.client.get('/adminpanel', follow_redirects=False)
        self.assertIn(resp.status_code, (301, 302))
        self.assertIn('login', resp.headers.get('Location', ''))

    def test_logout(self):
        self._login()
        # Logout is POST-only (CSRF-protected); CSRF is disabled under testing.
        resp = self.client.post('/adminpanel/logout', follow_redirects=False)
        self.assertIn(resp.status_code, (301, 302))
        # After logout, admin panel should redirect to login
        resp2 = self.client.get('/adminpanel', follow_redirects=False)
        self.assertIn('login', resp2.headers.get('Location', ''))


class TestConfigCRUD(IntegrationTestBase):
    """Config add, enable/disable, delete, bulk delete, reorder."""

    def test_add_config(self):
        self._login()
        resp = self.client.post('/adminpanel/add', data={
            'config_text': 'vmess://eyJhZGQiOiJ0ZXN0LmNvbSIsInBvcnQiOiI0NDMiLCJ2IjoiMiJ9'
        })
        data = json.loads(resp.data)
        self.assertTrue(data['success'])
        self.assertGreaterEqual(data['added'], 1)

    def test_add_valid_vmess_config(self):
        """Test with properly formatted VMess config."""
        self._login()
        valid_vmess = 'vmess://eyJhZGQiOiJ0ZXN0LmNvbSIsInBvcnQiOiI0NDMiLCJ2IjoiMiJ9'
        resp = self.client.post('/adminpanel/add', data={'config_text': valid_vmess})
        data = json.loads(resp.data)
        self.assertTrue(data['success'])
        self.assertEqual(data['added'], 1)

    def test_add_empty_config(self):
        self._login()
        resp = self.client.post('/adminpanel/add', data={'config_text': ''})
        data = json.loads(resp.data)
        self.assertFalse(data['success'])

    def test_set_enabled(self):
        self._login()
        # First add a config
        self.client.post('/adminpanel/add', data={
            'config_text': 'vless://test@example.com:443'
        })
        # Disable it (id=1)
        resp = self.client.post('/adminpanel/config/set_enabled/1',
                                data=json.dumps({'enabled': False}),
                                content_type='application/json')
        data = json.loads(resp.data)
        self.assertTrue(data['success'])

    def test_delete_config(self):
        self._login()
        self.client.post('/adminpanel/add', data={
            'config_text': 'trojan://password@host:443'
        })
        resp = self.client.post('/adminpanel/delete/1')
        data = json.loads(resp.data)
        self.assertTrue(data['success'])

    def test_bulk_delete(self):
        self._login()
        valid_vmess = 'vmess://eyJhZGQiOiJ0ZXN0LmNvbSIsInBvcnQiOiI0NDMiLCJ2IjoiMiJ9'
        valid_vless = 'vless://b@c:443'
        self.client.post('/adminpanel/add', data={
            'config_text': f'{valid_vmess}\n{valid_vless}'
        })
        resp = self.client.post('/adminpanel/bulk_delete',
                                data=json.dumps({'ids': [1, 2]}),
                                content_type='application/json')
        data = json.loads(resp.data)
        self.assertTrue(data['success'])

    def test_renumber(self):
        self._login()
        resp = self.client.post('/adminpanel/renumber')
        data = json.loads(resp.data)
        self.assertTrue(data['success'])


class TestSettings(IntegrationTestBase):
    """Issue 2: set_format and set_sort_order endpoints."""

    def test_set_format(self):
        self._login()
        resp = self.client.post('/adminpanel/set_format', data={'format': 'plain'})
        data = json.loads(resp.data)
        self.assertTrue(data['success'])

    def test_set_format_invalid(self):
        self._login()
        resp = self.client.post('/adminpanel/set_format', data={'format': 'invalid'})
        data = json.loads(resp.data)
        self.assertFalse(data['success'])

    def test_set_sort_order(self):
        self._login()
        resp = self.client.post('/adminpanel/set_sort_order', data={'sort_order': 'desc'})
        data = json.loads(resp.data)
        self.assertTrue(data['success'])

    def test_set_sort_order_invalid(self):
        self._login()
        resp = self.client.post('/adminpanel/set_sort_order', data={'sort_order': 'random'})
        data = json.loads(resp.data)
        self.assertFalse(data['success'])


class TestSubscription(IntegrationTestBase):
    """Subscription endpoint returns configs for valid paths."""

    def test_user_subscription(self):
        self._login()
        # Add a config to the global pool
        self.client.post('/adminpanel/add', data={
            'config_text': 'vmess://eyJhZGQiOiJ0ZXN0LmNvbSIsInBvcnQiOiI0NDMiLCJ2IjoiMiJ9'
        })
        # A user link serves the pool (there is no default/public path anymore)
        r = json.loads(self.client.post('/adminpanel/api/users',
                                        data=json.dumps({'name': 'sub', 'duration_days': 30, 'path': 'subuser0001'}),
                                        content_type='application/json').data)
        self.assertTrue(r['success'])
        resp = self.client.get('/sub/subuser0001')
        self.assertEqual(resp.status_code, 200)

    def test_invalid_path_404(self):
        resp = self.client.get('/sub/nonexistentpath')
        self.assertIn(resp.status_code, (403, 404))


class TestStats(IntegrationTestBase):
    """Statistics and chart data endpoints."""

    def test_stats(self):
        self._login()
        resp = self.client.get('/adminpanel/stats')
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertIn('total_configs', data)
        self.assertIn('active_configs', data)

    def test_usage_stats_response_shape(self):
        """usage_stats must include frontend-expected fields."""
        self._login()
        resp = self.client.get('/adminpanel/usage_stats?range=24h')
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        # Frontend-required fields
        self.assertIn('today_unique', data)
        self.assertIn('today_total', data)
        self.assertIn('labels', data)
        self.assertIn('data', data)
        self.assertIn('unique_data', data)
        # Types
        self.assertIsInstance(data['today_unique'], int)
        self.assertIsInstance(data['today_total'], int)
        self.assertIsInstance(data['labels'], list)
        self.assertIsInstance(data['data'], list)
        self.assertIsInstance(data['unique_data'], list)
        # Arrays should be same length
        self.assertEqual(len(data['labels']), len(data['data']))
        self.assertEqual(len(data['labels']), len(data['unique_data']))

    def test_usage_stats_7d_has_date_labels(self):
        """For range=7d, labels should be date strings."""
        self._login()
        resp = self.client.get('/adminpanel/usage_stats?range=7d')
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertIn('labels', data)
        self.assertEqual(len(data['labels']), 7)
        # Each label should look like a date (YYYY-MM-DD)
        for label in data['labels']:
            self.assertRegex(label, r'^\d{4}-\d{2}-\d{2}$')

    def test_usage_stats_extended_fields(self):
        """Extended fields should also be present for other consumers."""
        self._login()
        resp = self.client.get('/adminpanel/usage_stats?range=24h')
        data = json.loads(resp.data)
        self.assertIn('total_requests', data)
        self.assertIn('successful_downloads', data)
        self.assertIn('unique_ips', data)

    def test_chart_data_daily_format(self):
        """daily must have 'downloads' key (not just 'data')."""
        self._login()
        resp = self.client.get('/adminpanel/chart_data')
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)

        self.assertIn('daily', data)
        self.assertIn('downloads', data['daily'])
        self.assertIn('labels', data['daily'])
        self.assertIsInstance(data['daily']['downloads'], list)
        self.assertIsInstance(data['daily']['labels'], list)
        self.assertEqual(len(data['daily']['labels']), len(data['daily']['downloads']))

    def test_chart_data_clients_timeseries_format(self):
        """clients must have date labels and per-client arrays of same length."""
        self._login()
        resp = self.client.get('/adminpanel/chart_data?client_range=7d')
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)

        self.assertIn('clients', data)
        clients = data['clients']

        # Must have date labels
        self.assertIn('labels', clients)
        self.assertIsInstance(clients['labels'], list)
        num_labels = len(clients['labels'])
        self.assertEqual(num_labels, 7)

        # Each label should be a date
        for label in clients['labels']:
            self.assertRegex(label, r'^\d{4}-\d{2}-\d{2}$')

        # Must have per-client arrays
        expected_clients = ['v2rayNG', 'Nekobox', 'Clash', 'Shadowrocket', 'Sing-box', 'Other']
        for client_name in expected_clients:
            self.assertIn(client_name, clients,
                          f"clients response missing key '{client_name}'")
            self.assertIsInstance(clients[client_name], list,
                                 f"clients['{client_name}'] should be a list")
            self.assertEqual(len(clients[client_name]), num_labels,
                             f"clients['{client_name}'] length should match labels length")

    def test_chart_data_has_protocols(self):
        """Chart data should include protocol distribution."""
        self._login()
        resp = self.client.get('/adminpanel/chart_data')
        data = json.loads(resp.data)
        self.assertIn('protocols', data)
        self.assertIn('labels', data['protocols'])
        self.assertIn('data', data['protocols'])


class TestLogs(IntegrationTestBase):
    """Log viewing and clearing."""

    def test_logs_endpoint(self):
        self._login()
        resp = self.client.get('/adminpanel/logs')
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertIsInstance(data, list)

    def test_clear_logs(self):
        """Issue 2: Frontend calls /adminpanel/clear_logs."""
        self._login()
        resp = self.client.post('/adminpanel/clear_logs')
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertTrue(data['success'])


class TestUnauthorizedAccess(IntegrationTestBase):
    """Ensure API endpoints reject unauthenticated requests."""

    def test_api_requires_auth(self):
        endpoints = [
            ('GET', '/adminpanel/stats'),
            ('GET', '/adminpanel/paths'),
            ('GET', '/adminpanel/usage_stats'),
            ('GET', '/adminpanel/chart_data'),
            ('GET', '/adminpanel/logs'),
            ('POST', '/adminpanel/add'),
            ('POST', '/adminpanel/set_format'),
            ('POST', '/adminpanel/clear_logs'),
            ('POST', '/adminpanel/paths/add'),
            ('GET', '/adminpanel/paths/generate_random'),
            ('POST', '/adminpanel/auto_sources/add'),
            ('POST', '/adminpanel/settings/automation'),
            ('POST', '/adminpanel/automation/trigger'),
        ]
        for method, url in endpoints:
            if method == 'GET':
                resp = self.client.get(url)
            else:
                resp = self.client.post(url)
            self.assertEqual(resp.status_code, 401,
                             f'{method} {url} should return 401 without login')


class TestAutomationIntegration(IntegrationTestBase):
    """Integration tests for the V2RayDAR automation integration features."""

    def test_auto_sources_crud(self):
        self._login()
        # 1. Add auto source
        resp = self.client.post('/adminpanel/auto_sources/add', data={
            'name': 'Test Source',
            'url': 'https://example.com/sub',
            'priority': '150'
        })
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertTrue(data['success'])

        # Check in DB
        from database import get_db
        db = get_db()
        row = db.execute('SELECT * FROM auto_sources WHERE name = "Test Source"').fetchone()
        db.close()
        self.assertIsNotNone(row)
        self.assertEqual(row['url'], 'https://example.com/sub')
        self.assertEqual(row['priority'], 150)
        self.assertEqual(row['is_enabled'], 1)

        source_id = row['id']

        # 2. Toggle auto source
        resp = self.client.post(f'/adminpanel/auto_sources/toggle/{source_id}', json={'enabled': False})
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertTrue(data['success'])

        db = get_db()
        row = db.execute('SELECT * FROM auto_sources WHERE id = ?', (source_id,)).fetchone()
        db.close()
        self.assertEqual(row['is_enabled'], 0)

        # 3. Update priority
        resp = self.client.post(f'/adminpanel/auto_sources/priority/{source_id}', json={'priority': 250})
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertTrue(data['success'])

        db = get_db()
        row = db.execute('SELECT * FROM auto_sources WHERE id = ?', (source_id,)).fetchone()
        db.close()
        self.assertEqual(row['priority'], 250)

        # 4. Delete auto source
        resp = self.client.post(f'/adminpanel/auto_sources/delete/{source_id}')
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertTrue(data['success'])

        db = get_db()
        row = db.execute('SELECT * FROM auto_sources WHERE id = ?', (source_id,)).fetchone()
        db.close()
        self.assertIsNone(row)

    def test_save_automation_settings(self):
        self._login()
        resp = self.client.post('/adminpanel/settings/automation', data={
            'scan_interval': '500',
            'health_check_interval': '900',
            'max_active_configs': '200',
            'max_new_configs_per_scan': '25',
            'failure_threshold': '4',
            'cleanup_policy': 'delete',
            'scan_timeout': '1800'
        })
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertTrue(data['success'])

        from database import get_setting
        self.assertEqual(get_setting('scan_interval'), '500')
        self.assertEqual(get_setting('health_check_interval'), '900')
        self.assertEqual(get_setting('max_active_configs'), '200')
        self.assertEqual(get_setting('max_new_configs_per_scan'), '25')
        self.assertEqual(get_setting('failure_threshold'), '4')
        self.assertEqual(get_setting('cleanup_policy'), 'delete')
        self.assertEqual(get_setting('scan_timeout'), '1800')

    def test_stats_contains_automation_counters(self):
        self._login()
        # Add mock configs
        from database import get_db
        db = get_db()
        db.execute("INSERT INTO configs (config_text, config_type, mode, health_status, status, is_enabled) VALUES ('ss://abc', 'shadowsocks', 'manual', 'healthy', 'active', 1)")
        db.execute("INSERT INTO configs (config_text, config_type, mode, health_status, status, is_enabled) VALUES ('vmess://def', 'vmess', 'auto', 'unhealthy', 'active', 1)")
        db.commit()
        db.close()

        resp = self.client.get('/adminpanel/stats')
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertEqual(data['manual_configs'], 1)
        self.assertEqual(data['auto_configs'], 1)
        self.assertEqual(data['healthy_configs'], 1)
        self.assertEqual(data['unhealthy_configs'], 1)

    def test_trigger_automation_api(self):
        self._login()
        resp = self.client.post('/adminpanel/automation/trigger', data={'mode': 'invalid'})
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertFalse(data['success'])

        resp = self.client.post('/adminpanel/automation/trigger', data={'mode': 'health_check'})
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertTrue(data['success'])


class TestUsers(IntegrationTestBase):
    """User management: CRUD, cross-table unique paths, activation-on-first-use,
    and expiry/pause/disabled subscription serving."""

    def _add_user(self, name='کاربر', days=30, path=None, note=None):
        payload = {'name': name, 'duration_days': days}
        if path is not None:
            payload['path'] = path
        if note is not None:
            payload['note'] = note
        resp = self.client.post('/adminpanel/api/users',
                                data=json.dumps(payload),
                                content_type='application/json')
        return json.loads(resp.data)

    def _get_user(self, user_id):
        users = json.loads(self.client.get('/adminpanel/api/users').data)
        return next((u for u in users if u['id'] == user_id), None)

    def _force_expired(self, user_id):
        """Mark a user as activated in the past and already expired (UTC)."""
        from database import get_db
        db = get_db()
        db.execute("UPDATE users SET activated_at = datetime('now', '-10 day'), "
                   "expire_at = datetime('now', '-1 hour') WHERE id = ?", (user_id,))
        db.commit()
        db.close()

    def _decode(self, resp):
        import base64
        return base64.b64decode(resp.data).decode('utf-8')

    # ── auth ──
    def test_users_api_requires_auth(self):
        resp = self.client.get('/adminpanel/api/users')
        self.assertEqual(resp.status_code, 401)

    # ── create / validation ──
    def test_create_user_auto_path(self):
        self._login()
        r = self._add_user('علی', 30)
        self.assertTrue(r['success'])
        self.assertTrue(r['user']['path'])
        self.assertTrue(r['user']['sub_url'].endswith('sub/' + r['user']['path']))

    def test_reject_duplicate_path_users_table(self):
        self._login()
        self.assertTrue(self._add_user('A', 30, path='custompath1')['success'])
        self.assertFalse(self._add_user('B', 30, path='custompath1')['success'])

    def test_reject_path_colliding_with_legacy_path(self):
        # Defensive: a user must not claim a path that still lives in the legacy
        # subscription_paths table (normally emptied by migration).
        self._login()
        from database import get_db
        db = get_db()
        db.execute("INSERT INTO subscription_paths (path, is_primary, is_enabled) VALUES ('legacypath01', 0, 1)")
        db.commit()
        db.close()
        self.assertFalse(self._add_user('A', 30, path='legacypath01')['success'])

    def test_reject_short_path(self):
        self._login()
        self.assertFalse(self._add_user('A', 30, path='short')['success'])

    # ── activation on first use ──
    def test_first_use_activation(self):
        self._login()
        r = self._add_user('A', 30, path='activateme1')
        uid = r['user']['id']
        self.assertIsNone(self._get_user(uid)['activated_at'])
        self.client.get('/sub/activateme1')  # first fetch activates
        u = self._get_user(uid)
        self.assertIsNotNone(u['activated_at'])
        self.assertIsNotNone(u['expire_at'])

    # ── serving states ──
    def test_active_serves_real_configs(self):
        self._login()
        self.client.post('/adminpanel/add', data={
            'config_text': 'vmess://eyJhZGQiOiJ0ZXN0LmNvbSIsInBvcnQiOiI0NDMiLCJ2IjoiMiJ9'})
        self._add_user('A', 30, path='activeserve1')
        resp = self.client.get('/sub/activeserve1')
        self.assertEqual(resp.status_code, 200)
        body = self._decode(resp)
        self.assertIn('vmess://', body)
        self.assertNotIn('expired-user', body)

    def test_expired_serves_dummy(self):
        self._login()
        r = self._add_user('A', 30, path='expireuser1')
        self.client.get('/sub/expireuser1')  # activate
        self._force_expired(r['user']['id'])
        resp = self.client.get('/sub/expireuser1')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('expired-user', self._decode(resp))

    def test_paused_serves_dummy(self):
        self._login()
        r = self._add_user('A', 30, path='pauseuser1')
        self.client.post('/adminpanel/api/users/%d/pause' % r['user']['id'])
        resp = self.client.get('/sub/pauseuser1')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('expired-user', self._decode(resp))

    def test_disabled_returns_404(self):
        self._login()
        r = self._add_user('A', 30, path='disableuser1')
        self.client.post('/adminpanel/api/users/%d/toggle' % r['user']['id'],
                         data=json.dumps({'enabled': False}), content_type='application/json')
        resp = self.client.get('/sub/disableuser1')
        self.assertEqual(resp.status_code, 404)

    def test_dummy_respects_plain_format(self):
        self._login()
        self.client.post('/adminpanel/set_format', data={'format': 'plain'})
        r = self._add_user('A', 30, path='plainuser1')
        self.client.get('/sub/plainuser1')  # activate
        self._force_expired(r['user']['id'])
        resp = self.client.get('/sub/plainuser1')
        body = resp.data.decode('utf-8')
        self.assertTrue(body.startswith('trojan://expired-user'))

    # ── lifecycle ──
    def test_pause_resume_delete(self):
        self._login()
        uid = self._add_user('A', 30, path='lifecycle01')['user']['id']
        self.assertTrue(json.loads(self.client.post('/adminpanel/api/users/%d/pause' % uid).data)['success'])
        self.assertEqual(self._get_user(uid)['effective_status'], 'PAUSED')
        self.assertTrue(json.loads(self.client.post('/adminpanel/api/users/%d/resume' % uid).data)['success'])
        self.assertEqual(self._get_user(uid)['effective_status'], 'ACTIVE')
        self.assertTrue(json.loads(self.client.delete('/adminpanel/api/users/%d' % uid).data)['success'])
        self.assertIsNone(self._get_user(uid))

    # ── unlimited (duration 0) ──
    def test_unlimited_never_expires(self):
        self._login()
        self.client.post('/adminpanel/add', data={
            'config_text': 'vmess://eyJhZGQiOiJ0ZXN0LmNvbSIsInBvcnQiOiI0NDMiLCJ2IjoiMiJ9'})
        uid = self._add_user('نامحدود', 0, path='unlimited001')['user']['id']
        u = self._get_user(uid)
        self.assertEqual(u['remaining_text'], 'نامحدود')
        # first fetch activates but sets no expiry, and serves the real pool
        resp = self.client.get('/sub/unlimited001')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('vmess://', self._decode(resp))
        u = self._get_user(uid)
        self.assertIsNotNone(u['activated_at'])
        self.assertIsNone(u['expire_at'])
        self.assertEqual(u['effective_status'], 'ACTIVE')

    # ── migration of legacy public link ──
    def test_migration_public_link_becomes_user(self):
        self._login()
        from database import get_db, init_db
        db = get_db()
        db.execute("INSERT INTO subscription_paths (path, is_primary, is_enabled) VALUES ('oldpublic01', 1, 1)")
        db.commit()
        db.close()
        init_db()  # migration runs here
        users = json.loads(self.client.get('/adminpanel/api/users').data)
        migrated = [u for u in users if u['path'] == 'oldpublic01']
        self.assertEqual(len(migrated), 1)
        self.assertEqual(migrated[0]['duration_days'], 0)  # unlimited
        # legacy row was removed; deleting the user now kills the link for good
        db = get_db()
        remaining = db.execute("SELECT COUNT(*) c FROM subscription_paths WHERE path='oldpublic01'").fetchone()['c']
        db.close()
        self.assertEqual(remaining, 0)

    # ── per-user usage history ──
    def test_user_history(self):
        self._login()
        uid = self._add_user('H', 30, path='historyuser1')['user']['id']
        self.client.get('/sub/historyuser1', headers={'User-Agent': 'v2rayNG/1.2'})
        self.client.get('/sub/historyuser1', headers={'User-Agent': 'Hiddify/2.0'})
        resp = self.client.get('/adminpanel/api/users/%d/history' % uid)
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertGreaterEqual(len(data['history']), 2)
        self.assertIn('user_agent', data['history'][0])
        self.assertIn('ip_address', data['history'][0])
        self.assertIsNotNone(data['last_user_agent'])
        self.assertGreaterEqual(len(data['user_agents']), 2)


class TestDeviceLimit(IntegrationTestBase):
    """Per-user device cap: fingerprint = UA + IP/24, rolling-window slots,
    known devices never blocked, over-limit devices get the dummy config."""

    def _add_user(self, name='کاربر', days=30, path=None, max_devices=1):
        payload = {'name': name, 'duration_days': days, 'max_devices': max_devices}
        if path is not None:
            payload['path'] = path
        resp = self.client.post('/adminpanel/api/users',
                                data=json.dumps(payload),
                                content_type='application/json')
        return json.loads(resp.data)

    def _seed_config(self):
        self.client.post('/adminpanel/add', data={
            'config_text': 'vmess://eyJhZGQiOiJ0ZXN0LmNvbSIsInBvcnQiOiI0NDMiLCJ2IjoiMiJ9'})

    def _fetch(self, path, ip='1.1.1.1', ua='v2rayNG/1.0'):
        return self.client.get('/sub/' + path,
                               headers={'User-Agent': ua},
                               environ_base={'REMOTE_ADDR': ip})

    def _decode(self, resp):
        import base64
        return base64.b64decode(resp.data).decode('utf-8')

    def _is_real(self, resp):
        body = self._decode(resp)
        return ('vmess://' in body) and ('expired-user' not in body)

    def _is_dummy(self, resp):
        return 'expired-user' in self._decode(resp)

    def _get_user(self, user_id):
        users = json.loads(self.client.get('/adminpanel/api/users').data)
        return next((u for u in users if u['id'] == user_id), None)

    # ── happy path ──
    def test_under_limit_serves_real(self):
        self._login()
        self._seed_config()
        self._add_user('A', 30, path='devunder0001', max_devices=2)
        self.assertTrue(self._is_real(self._fetch('devunder0001', ip='1.1.1.1')))

    def test_new_device_over_limit_blocked(self):
        self._login()
        self._seed_config()
        uid = self._add_user('A', 30, path='devlimit0001', max_devices=1)['user']['id']
        # first device (network 1.1.1.0/24) registers and is served
        self.assertTrue(self._is_real(self._fetch('devlimit0001', ip='1.1.1.1', ua='v2rayNG/1.0')))
        # a second, different network is over the cap -> dummy
        r2 = self._fetch('devlimit0001', ip='9.9.9.9', ua='v2rayNG/1.0')
        self.assertTrue(self._is_dummy(r2))
        # and it was logged as DEVICE_LIMIT
        hist = json.loads(self.client.get('/adminpanel/api/users/%d/history' % uid).data)
        self.assertTrue(any(h['status'] == 'DEVICE_LIMIT' for h in hist['history']))

    def test_same_network_not_double_counted(self):
        self._login()
        self._seed_config()
        self._add_user('A', 30, path='devsamenet01', max_devices=1)
        # same UA, two IPs inside the same /24 -> one device, both served real
        self.assertTrue(self._is_real(self._fetch('devsamenet01', ip='5.5.5.5', ua='v2rayNG/1.0')))
        self.assertTrue(self._is_real(self._fetch('devsamenet01', ip='5.5.5.200', ua='v2rayNG/1.0')))

    def test_known_device_never_blocked_when_full(self):
        self._login()
        self._seed_config()
        self._add_user('A', 30, path='devknown0001', max_devices=1)
        self.assertTrue(self._is_real(self._fetch('devknown0001', ip='1.1.1.1', ua='v2rayNG/1.0')))
        # a new device is turned away...
        self.assertTrue(self._is_dummy(self._fetch('devknown0001', ip='9.9.9.9', ua='v2rayNG/1.0')))
        # ...but the original device keeps getting the real list
        self.assertTrue(self._is_real(self._fetch('devknown0001', ip='1.1.1.1', ua='v2rayNG/1.0')))

    def test_preview_bot_does_not_consume_a_device_slot(self):
        self._login()
        self._seed_config()
        uid = self._add_user('A', 30, path='devbot000001', max_devices=1)['user']['id']
        # Telegram's link-preview bot fetches first — served, but must NOT take
        # the single device slot (mirrors sharing the link in a Telegram chat).
        self.assertTrue(self._is_real(self._fetch(
            'devbot000001', ip='149.154.161.251', ua='TelegramBot (like TwitterBot)')))
        # The user's real client on a different network still gets the real list.
        self.assertTrue(self._is_real(self._fetch(
            'devbot000001', ip='65.108.154.95', ua='v2rayNG/2.2.5')))
        # Exactly one device (the real client) is registered.
        self.assertEqual(self._get_user(uid)['active_device_count'], 1)

    def test_rolling_window_frees_slot(self):
        self._login()
        self._seed_config()
        uid = self._add_user('A', 30, path='devwindow001', max_devices=1)['user']['id']
        self.assertTrue(self._is_real(self._fetch('devwindow001', ip='1.1.1.1', ua='v2rayNG/1.0')))
        # age the only device well past the 7-day window
        from database import get_db
        db = get_db()
        db.execute("UPDATE user_devices SET last_seen = datetime('now', '-30 day') WHERE user_id = ?", (uid,))
        db.commit()
        db.close()
        # a new device now finds a free slot
        self.assertTrue(self._is_real(self._fetch('devwindow001', ip='9.9.9.9', ua='v2rayNG/1.0')))

    def test_max_devices_zero_is_unlimited(self):
        self._login()
        self._seed_config()
        self._add_user('A', 30, path='devunlimit01', max_devices=0)
        for ip in ('1.1.1.1', '2.2.2.2', '3.3.3.3', '4.4.4.4'):
            self.assertTrue(self._is_real(self._fetch('devunlimit01', ip=ip)))

    def test_active_device_count_reported(self):
        self._login()
        self._seed_config()
        uid = self._add_user('A', 30, path='devcount0001', max_devices=3)['user']['id']
        self._fetch('devcount0001', ip='1.1.1.1', ua='v2rayNG/1.0')
        self._fetch('devcount0001', ip='2.2.2.2', ua='Hiddify/1.0')
        self.assertEqual(self._get_user(uid)['active_device_count'], 2)

    # ── management ──
    def test_reset_devices_frees_slots(self):
        self._login()
        self._seed_config()
        uid = self._add_user('A', 30, path='devreset0001', max_devices=1)['user']['id']
        self._fetch('devreset0001', ip='1.1.1.1', ua='v2rayNG/1.0')
        self.assertTrue(self._is_dummy(self._fetch('devreset0001', ip='9.9.9.9', ua='v2rayNG/1.0')))
        # clearing devices frees the slot
        self.assertTrue(json.loads(self.client.post(
            '/adminpanel/api/users/%d/devices/reset' % uid).data)['success'])
        self.assertTrue(self._is_real(self._fetch('devreset0001', ip='9.9.9.9', ua='v2rayNG/1.0')))

    def test_list_and_kick_device(self):
        self._login()
        self._seed_config()
        uid = self._add_user('A', 30, path='devkick00001', max_devices=2)['user']['id']
        self._fetch('devkick00001', ip='1.1.1.1', ua='v2rayNG/1.0')
        data = json.loads(self.client.get('/adminpanel/api/users/%d/devices' % uid).data)
        self.assertEqual(len(data['devices']), 1)
        dev_id = data['devices'][0]['id']
        self.assertTrue(json.loads(self.client.delete(
            '/adminpanel/api/users/%d/devices/%d' % (uid, dev_id)).data)['success'])
        data2 = json.loads(self.client.get('/adminpanel/api/users/%d/devices' % uid).data)
        self.assertEqual(len(data2['devices']), 0)

    # ── format ──
    def test_device_limit_dummy_respects_plain_format(self):
        self._login()
        self._seed_config()
        self.client.post('/adminpanel/set_format', data={'format': 'plain'})
        self._add_user('A', 30, path='devplain0001', max_devices=1)
        self._fetch('devplain0001', ip='1.1.1.1', ua='v2rayNG/1.0')
        resp = self._fetch('devplain0001', ip='9.9.9.9', ua='v2rayNG/1.0')
        self.assertTrue(resp.data.decode('utf-8').startswith('trojan://expired-user'))


class TestBackupRestore(IntegrationTestBase):
    """Integration tests for Backup & Disaster Recovery system."""

    def _add_config(self):
        return self.client.post('/adminpanel/add', data={
            'config_text': 'vmess://eyJhZGQiOiJ0ZXN0LmNvbSIsInBvcnQiOiI0NDMiLCJ2IjoiMiJ9'
        })

    def _add_user(self, name, duration=30, path=None):
        payload = {'name': name, 'duration_days': duration}
        if path:
            payload['path'] = path
        resp = self.client.post('/adminpanel/api/users', data=payload)
        return json.loads(resp.data.decode('utf-8'))

    def test_manual_backup_creation_and_download(self):
        self._login()
        
        # Add dummy data
        self._add_config()
        self._add_user("User A", 30)

        # Create backup
        resp = self.client.post('/adminpanel/api/backup/create', data={'backup_type': 'standard'})
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertTrue(data['success'])
        self.assertIn('filename', data)
        self.assertIn('checksum', data)
        self.assertGreater(data['size'], 0)

        filename = data['filename']

        # Download backup
        resp_dl = self.client.get(f'/adminpanel/api/backup/download/{filename}')
        self.assertEqual(resp_dl.status_code, 200)
        self.assertEqual(len(resp_dl.data), data['size'])

    def test_backup_logs(self):
        self._login()
        self.client.post('/adminpanel/api/backup/create', data={'backup_type': 'standard'})
        
        resp_logs = self.client.get('/adminpanel/api/backup/logs')
        self.assertEqual(resp_logs.status_code, 200)
        logs = json.loads(resp_logs.data)
        self.assertGreaterEqual(len(logs), 1)
        self.assertEqual(logs[0]['operation'], 'backup')
        self.assertEqual(logs[0]['status'], 'SUCCESS')

    def test_backup_verify_and_restore(self):
        self._login()
        
        # 1. Populate database
        self._add_config()
        self._add_user("User to Backup", 30, path="backupuserpath1")

        # 2. Create backup
        resp_create = self.client.post('/adminpanel/api/backup/create', data={'backup_type': 'standard'})
        data_create = json.loads(resp_create.data)
        filename = data_create['filename']

        # Download backup zip bytes
        resp_dl = self.client.get(f'/adminpanel/api/backup/download/{filename}')
        zip_bytes = resp_dl.data

        # 3. Modify database (add new user, delete old user)
        self._add_user("New User", 15, path="newuserpath1")
        # Verify database has changed
        users_before = json.loads(self.client.get('/adminpanel/api/users').data)
        paths_before = [u['path'] for u in users_before]
        self.assertIn("newuserpath1", paths_before)

        # 4. Verify backup non-destructively
        import io
        verify_data = {
            'backup_file': (io.BytesIO(zip_bytes), filename)
        }
        resp_ver = self.client.post('/adminpanel/api/backup/verify', data=verify_data, content_type='multipart/form-data')
        self.assertEqual(resp_ver.status_code, 200)
        data_ver = json.loads(resp_ver.data)
        self.assertTrue(data_ver['success'])
        self.assertEqual(data_ver['stats']['backup_type'], 'standard')

        # 5. Restore backup
        restore_data = {
            'backup_file': (io.BytesIO(zip_bytes), filename),
            'restore_env': 'false'
        }
        resp_res = self.client.post('/adminpanel/api/backup/restore', data=restore_data, content_type='multipart/form-data')
        self.assertEqual(resp_res.status_code, 200)
        data_res = json.loads(resp_res.data)
        self.assertTrue(data_res['success'])

        # 6. Verify database is restored back (New User is gone, User to Backup is back)
        users_after = json.loads(self.client.get('/adminpanel/api/users').data)
        paths_after = [u['path'] for u in users_after]
        self.assertIn("backupuserpath1", paths_after)
        self.assertNotIn("newuserpath1", paths_after)

    def test_backup_encryption_full_dr(self):
        self._login()
        self._add_user("Secret User", 90, path="secretpath99")

        # Create encrypted Full DR backup
        resp_create = self.client.post('/adminpanel/api/backup/create', data={
            'backup_type': 'full_dr',
            'password': 'testsecretpass123'
        })
        self.assertEqual(resp_create.status_code, 200)
        data_create = json.loads(resp_create.data)
        filename = data_create['filename']

        # Download ZIP and check encryption header ENC\x00
        resp_dl = self.client.get(f'/adminpanel/api/backup/download/{filename}')
        zip_bytes = resp_dl.data
        self.assertTrue(zip_bytes.startswith(b'ENC\x00'))

        # Verify with wrong password (should fail)
        import io
        verify_data_wrong = {
            'backup_file': (io.BytesIO(zip_bytes), filename),
            'password': 'wrongpassword'
        }
        resp_ver_wrong = self.client.post('/adminpanel/api/backup/verify', data=verify_data_wrong, content_type='multipart/form-data')
        data_ver_wrong = json.loads(resp_ver_wrong.data)
        self.assertFalse(data_ver_wrong['success'])

        # Verify with correct password (should succeed)
        verify_data_correct = {
            'backup_file': (io.BytesIO(zip_bytes), filename),
            'password': 'testsecretpass123'
        }
        resp_ver_correct = self.client.post('/adminpanel/api/backup/verify', data=verify_data_correct, content_type='multipart/form-data')
        data_ver_correct = json.loads(resp_ver_correct.data)
        self.assertTrue(data_ver_correct['success'])

        # Restore using correct password
        restore_data = {
            'backup_file': (io.BytesIO(zip_bytes), filename),
            'password': 'testsecretpass123',
            'restore_env': 'true'
        }
        resp_res = self.client.post('/adminpanel/api/backup/restore', data=restore_data, content_type='multipart/form-data')
        self.assertEqual(resp_res.status_code, 200)
        data_res = json.loads(resp_res.data)
        self.assertTrue(data_res['success'])

    def test_restore_rollback_on_failure(self):
        self._login()
        self._add_user("User to Protect", 30, path="protectpath123")

        # Restore with a corrupted file
        import io
        restore_data = {
            'backup_file': (io.BytesIO(b'INVALID_ZIP_DATA'), 'corrupted_backup.zip')
        }
        resp_res = self.client.post('/adminpanel/api/backup/restore', data=restore_data, content_type='multipart/form-data')
        # Should fail verification and return an error JSON
        data_res = json.loads(resp_res.data)
        self.assertFalse(data_res['success'])

        # Verify database is intact (User to Protect is still there)
        users = json.loads(self.client.get('/adminpanel/api/users').data)
        paths = [u['path'] for u in users]
        self.assertIn("protectpath123", paths)

    def test_retention_cleanup(self):
        self._login()
        # Save retention max = 2
        self.client.post('/adminpanel/api/settings/backup', data={
            'backup_retention_max': '2'
        })

        # Create 3 backups
        r1 = json.loads(self.client.post('/adminpanel/api/backup/create', data={'backup_type': 'standard'}).data)
        r2 = json.loads(self.client.post('/adminpanel/api/backup/create', data={'backup_type': 'standard'}).data)
        r3 = json.loads(self.client.post('/adminpanel/api/backup/create', data={'backup_type': 'standard'}).data)

        # Get list of backups
        resp_list = self.client.get('/adminpanel/api/backup/list')
        backups = json.loads(resp_list.data)
        
        # Max retention is 2, so the first backup (r1) should be purged!
        filenames = [b['filename'] for b in backups]
        self.assertNotIn(r1['filename'], filenames)
        self.assertIn(r2['filename'], filenames)
        self.assertIn(r3['filename'], filenames)

    def test_disk_space_validation(self):
        self._login()
        
        # Mock shutil.disk_usage to return 0 free space
        import shutil
        orig_disk_usage = shutil.disk_usage
        shutil.disk_usage = lambda path: (1000, 1000, 0) # 0 free bytes

        try:
            resp = self.client.post('/adminpanel/api/backup/create', data={'backup_type': 'standard'})
            data = json.loads(resp.data)
            self.assertFalse(data['success'])
            self.assertIn('دیسک کافی نیست', data['message'])
        finally:
            shutil.disk_usage = orig_disk_usage

    def test_telegram_and_bale_delivery_mock(self):
        self._login()
        
        # Enable Telegram delivery and set Bale API Server
        self.client.post('/adminpanel/api/settings/backup', data={
            'backup_telegram_enabled': '1',
            'backup_telegram_bot_token': '123456:ABC-DEF',
            'backup_telegram_chat_id': '987654321',
            'backup_telegram_api_server': 'https://tapi.bale.ai'
        })

        # Mock requests.post to check URL endpoint
        import requests
        orig_post = requests.post
        
        url_called = []
        def mock_post(url, *args, **kwargs):
            url_called.append(url)
            # Create a mock response
            class MockResponse:
                status_code = 200
                text = "OK"
            return MockResponse()

        requests.post = mock_post
        try:
            # Create backup and let it trigger delivery (deliver_backup runs delivery synchronously or via timer)
            # Wait, in BackupService.create_backup, it spawns a Thread to run deliver_backup.
            # To test it synchronously, we can call BackupService.deliver_backup directly!
            from services.backup_service import BackupService
            
            # Create a backup zip to send
            b = BackupService.create_backup(user='admin', backup_type='standard', trigger_delivery=False)
            filepath = os.path.join(BackupService.get_backup_dir(), b['filename'])
            
            # Run delivery directly
            BackupService.deliver_backup(filepath)
            
            # Verify it hit bale API server instead of Telegram
            self.assertGreater(len(url_called), 0)
            self.assertTrue(url_called[0].startswith('https://tapi.bale.ai/bot123456:ABC-DEF/sendDocument'))
        finally:
            requests.post = orig_post


class TestCSRF(IntegrationTestBase):
    """CSRF protection on state-changing admin routes."""

    def setUp(self):
        super().setUp()
        # Force-enable CSRF (disabled by default under testing) to exercise it.
        self.app.config['CSRF_ENABLED'] = True

    def _csrf_token(self, html):
        import re
        m = (re.search(r'name="csrf_token" value="([0-9a-f]+)"', html)
             or re.search(r'name="csrf-token" content="([0-9a-f]+)"', html))
        return m.group(1) if m else None

    def _login_with_token(self):
        html = self.client.get('/adminpanel/login').get_data(as_text=True)
        token = self._csrf_token(html)
        self.client.post('/adminpanel/login', data={
            'username': _TEST_USERNAME, 'password': _TEST_PASSWORD, 'csrf_token': token,
        })
        return token

    def test_login_requires_csrf_token(self):
        # Without a token the login must not succeed (re-renders the form).
        resp = self.client.post('/adminpanel/login', data={
            'username': _TEST_USERNAME, 'password': _TEST_PASSWORD,
        })
        self.assertEqual(resp.status_code, 200)  # error render, not a 302 redirect

    def test_api_post_rejected_without_token(self):
        self._login_with_token()
        resp = self.client.post('/adminpanel/renumber')
        self.assertEqual(resp.status_code, 403)

    def test_api_post_accepted_with_token(self):
        token = self._login_with_token()
        resp = self.client.post('/adminpanel/renumber', headers={'X-CSRF-Token': token})
        self.assertEqual(resp.status_code, 200)

    def test_logout_is_post_only_and_csrf_protected(self):
        token = self._login_with_token()
        self.assertEqual(self.client.get('/adminpanel/logout').status_code, 405)
        self.assertEqual(self.client.post('/adminpanel/logout').status_code, 403)
        self.assertIn(self.client.post('/adminpanel/logout', data={'csrf_token': token}).status_code, (301, 302, 308))


class TestSSRF(IntegrationTestBase):
    """Auto-source URLs must reject internal/non-HTTP targets (SSRF guard)."""

    def _add(self, url):
        return json.loads(self.client.post('/adminpanel/auto_sources/add', data={
            'name': 'S', 'url': url,
        }).data)

    def test_blocks_internal_and_non_http_urls(self):
        self._login()
        for bad in ('http://127.0.0.1/x', 'http://169.254.169.254/x',
                    'http://10.0.0.1/x', 'http://2130706433/x',
                    'file:///etc/passwd', 'ftp://h/x'):
            self.assertFalse(self._add(bad)['success'], f'should block {bad}')

    def test_allows_public_hostname(self):
        self._login()
        # DNS resolution is skipped under testing, so a public hostname is allowed.
        self.assertTrue(self._add('https://example.com/sub')['success'])


if __name__ == '__main__':
    unittest.main()