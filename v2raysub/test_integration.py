# -*- coding: utf-8 -*-
"""Integration tests for V2Ray Subscription Manager.

Covers: login page rendering, CRUD operations, path handling, subscriptions,
filters, statistics response shapes, chart data compatibility, and
form-encoded validation.
"""

import json
import os
import tempfile
import time
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

    def test_set_sort_order_ping(self):
        self._login()
        resp = self.client.post('/adminpanel/set_sort_order', data={'sort_order': 'ping'})
        data = json.loads(resp.data)
        self.assertTrue(data['success'])


class TestConfigPingSort(IntegrationTestBase):
    """'ping' display mode: lowest measured latency first, unmeasured configs last."""

    def _add_with_latency(self, config_text, latency=None):
        """Add one config and (optionally) stamp its latency directly, since
        latency is normally only written by the (external) scan engine.
        Returns the new config's id."""
        resp = self.client.post('/adminpanel/add', data={'config_text': config_text})
        self.assertTrue(json.loads(resp.data)['success'])
        from database import get_db
        db = get_db()
        config_id = db.execute(
            'SELECT id FROM configs WHERE config_text = ?', (config_text,)
        ).fetchone()['id']
        if latency is not None:
            db.execute('UPDATE configs SET latency = ? WHERE id = ?', (latency, config_id))
            db.commit()
        db.close()
        return config_id

    def _ordered_ids(self):
        resp = self.client.get('/adminpanel')
        # The admin page lists rows in the same order get_all_configs_for_admin
        # returns them; pull the ids out of the rendered markup in that order.
        import re
        return [int(m) for m in re.findall(r'id="config-(\d+)"', resp.data.decode('utf-8'))]

    def test_lowest_latency_first(self):
        self._login()
        slow = self._add_with_latency('vmess://eyJhZGQiOiJhLmNvbSIsInBvcnQiOiI0NDMiLCJ2IjoiMiJ9', latency=300)
        fast = self._add_with_latency('vless://b@c.com:443', latency=20)
        medium = self._add_with_latency('trojan://p@d.com:443', latency=120)
        self.client.post('/adminpanel/set_sort_order', data={'sort_order': 'ping'})
        self.assertEqual(self._ordered_ids(), [fast, medium, slow])

    def test_unmeasured_configs_sort_last(self):
        """A config never health-checked (latency IS NULL) must not be mistaken
        for a 0ms winner — it belongs after every measured config."""
        self._login()
        never_checked = self._add_with_latency('vmess://eyJhZGQiOiJhLmNvbSIsInBvcnQiOiI0NDMiLCJ2IjoiMiJ9')
        checked = self._add_with_latency('vless://b@c.com:443', latency=500)
        self.client.post('/adminpanel/set_sort_order', data={'sort_order': 'ping'})
        self.assertEqual(self._ordered_ids(), [checked, never_checked])

    def test_subscription_output_also_follows_ping_order(self):
        """The customer-facing list (not just the admin table) must respect the
        same ordering — that's the whole point of the setting."""
        self._login()
        # Plain (non-base64) URI schemes so the hostname is a literal substring
        # of the output — a vmess:// URI base64-encodes its host and would not be.
        self._add_with_latency('trojan://p@a.com:443', latency=300)
        self._add_with_latency('vless://b@c.com:443', latency=20)
        self.client.post('/adminpanel/set_sort_order', data={'sort_order': 'ping'})
        r = json.loads(self.client.post('/adminpanel/api/users',
                                        data=json.dumps({'name': 'p', 'duration_days': 30, 'path': 'pingsubuser1'}),
                                        content_type='application/json').data)
        self.assertTrue(r['success'])
        import base64
        resp = self.client.get('/sub/pingsubuser1')
        body = base64.b64decode(resp.data).decode('utf-8')
        self.assertLess(body.index('c.com'), body.index('a.com'))


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

    def _is_bot_placeholder(self, resp):
        return resp.data.decode('utf-8') == 'Content not available'

    def _is_browser_notice(self, resp):
        """The human-facing "import this into an app" page — and, just as
        importantly, no config anywhere in it."""
        body = resp.data.decode('utf-8')
        return ('این لینک را در مرورگر باز نکنید' in body
                and 'vmess://' not in body)

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

    def test_same_ip_different_clients_is_one_device(self):
        # One person, one connection, several client apps (different UAs) must
        # count as a SINGLE device — identity is the IP network only.
        self._login()
        self._seed_config()
        uid = self._add_user('A', 30, path='devmulticli1', max_devices=1)['user']['id']
        for ua in ('v2rayNG/1.8.29', 'Hiddify/2.5.0', 'NapsternetV/85', 'Streisand/1.6'):
            self.assertTrue(self._is_real(self._fetch('devmulticli1', ip='7.7.7.7', ua=ua)))
        # still exactly one device slot consumed
        self.assertEqual(self._get_user(uid)['active_device_count'], 1)
        # and all those UAs were still recorded in the history breakdown
        hist = json.loads(self.client.get('/adminpanel/api/users/%d/history' % uid).data)
        self.assertGreaterEqual(len(hist['user_agents']), 4)

    def test_known_device_never_blocked_when_full(self):
        self._login()
        self._seed_config()
        self._add_user('A', 30, path='devknown0001', max_devices=1)
        self.assertTrue(self._is_real(self._fetch('devknown0001', ip='1.1.1.1', ua='v2rayNG/1.0')))
        # a new device is turned away...
        self.assertTrue(self._is_dummy(self._fetch('devknown0001', ip='9.9.9.9', ua='v2rayNG/1.0')))
        # ...but the original device keeps getting the real list
        self.assertTrue(self._is_real(self._fetch('devknown0001', ip='1.1.1.1', ua='v2rayNG/1.0')))

    def test_preview_bot_gets_placeholder_not_real_config(self):
        self._login()
        self._seed_config()
        uid = self._add_user('A', 30, path='devbot000001', max_devices=1)['user']['id']
        # Telegram's link-preview bot fetches first — gets a neutral placeholder,
        # never the real config, and must NOT take the single device slot
        # (mirrors sharing the link in a Telegram chat).
        self.assertTrue(self._is_bot_placeholder(self._fetch(
            'devbot000001', ip='149.154.161.251', ua='TelegramBot (like TwitterBot)')))
        # The user's real client on a different network still gets the real list.
        self.assertTrue(self._is_real(self._fetch(
            'devbot000001', ip='65.108.154.95', ua='v2rayNG/2.2.5')))
        # Exactly one device (the real client) is registered.
        self.assertEqual(self._get_user(uid)['active_device_count'], 1)

    def test_browser_visit_does_not_consume_a_device_slot(self):
        """Tapping your own link opens it in a browser before it's ever imported
        into a VPN app. That visit must not burn a device slot — otherwise the
        very first real client already reads as the *second* device."""
        self._login()
        self._seed_config()
        uid = self._add_user('A', 30, path='devbrowser01', max_devices=3)['user']['id']
        chrome = ('Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/111.0.0.0 Mobile Safari/537.36')
        # Telegram previews the link, then the in-app browser opens it — from a
        # different network than the client will later use (IPv6 vs IPv4, CGNAT).
        self.assertTrue(self._is_bot_placeholder(self._fetch(
            'devbrowser01', ip='149.154.161.251', ua='TelegramBot (like TwitterBot)')))
        self.assertTrue(self._is_browser_notice(self._fetch(
            'devbrowser01', ip='5.201.130.7', ua=chrome)))
        self.assertEqual(self._get_user(uid)['active_device_count'], 0)
        # Only the real client registers — the user sees 1 of 3, not 2 of 3.
        self.assertTrue(self._is_real(self._fetch(
            'devbrowser01', ip='188.212.10.4', ua='HiddifyNext/1.1.1 (android) like ClashMeta v2ray sing-box')))
        self.assertEqual(self._get_user(uid)['active_device_count'], 1)

    def test_client_ua_with_browser_prefix_still_counts_as_a_device(self):
        """Some clients prefix a full browser UA. Known-client detection wins, so
        they must still register a device rather than be waved through."""
        self._login()
        self._seed_config()
        uid = self._add_user('A', 30, path='devuaprefix1', max_devices=2)['user']['id']
        self.assertTrue(self._is_real(self._fetch(
            'devuaprefix1', ip='3.3.3.3',
            ua='Mozilla/5.0 (Windows NT 10.0; Win64; x64) v2rayN/6.23')))
        self.assertEqual(self._get_user(uid)['active_device_count'], 1)

    def test_spoofed_browser_ua_cannot_bypass_device_cap(self):
        """A browser UA withholds the config for the same reason a bot UA does —
        otherwise the cap is one spoofed header away from meaningless."""
        self._login()
        self._seed_config()
        self._add_user('A', 30, path='devbrowser02', max_devices=1)
        self.assertTrue(self._is_real(self._fetch(
            'devbrowser02', ip='1.1.1.1', ua='v2rayNG/2.2.5')))
        resp = self._fetch('devbrowser02', ip='2.2.2.2',
                           ua='Mozilla/5.0 (X11; Linux x86_64) Firefox/126.0')
        self.assertTrue(self._is_browser_notice(resp))

    def test_browser_notice_shows_the_subscription_link(self):
        """The page is useless without the link it tells you to import, and the
        link must be the customer-facing one, not whatever host was requested."""
        self._login()
        self._seed_config()
        self._add_user('A', 30, path='devbrowser03', max_devices=2)
        from database import set_setting
        set_setting('public_base_url', 'https://vpn.example.com')
        resp = self._fetch('devbrowser03', ip='4.4.4.4',
                           ua='Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) Safari/605.1')
        self.assertIn('https://vpn.example.com/sub/devbrowser03', resp.data.decode('utf-8'))

    def test_browser_visit_is_logged_as_browser_view(self):
        self._login()
        self._seed_config()
        uid = self._add_user('A', 30, path='devbrowser04', max_devices=2)['user']['id']
        self._fetch('devbrowser04', ip='4.4.4.4',
                    ua='Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36')
        hist = json.loads(self.client.get('/adminpanel/api/users/%d/history' % uid).data)
        self.assertTrue(any(h['status'] == 'BROWSER_VIEW' for h in hist['history']))

    def test_spoofed_bot_ua_cannot_bypass_device_cap(self):
        self._login()
        self._seed_config()
        self._add_user('A', 30, path='devbot000002', max_devices=1)
        # First real device fills the single slot.
        self.assertTrue(self._is_real(self._fetch(
            'devbot000002', ip='1.1.1.1', ua='v2rayNG/2.2.5')))
        # A second, different network claiming a bot-like UA must NOT receive
        # the real config — that would bypass the cap entirely.
        resp = self._fetch('devbot000002', ip='2.2.2.2', ua='TotallyLegitBot/1.0')
        self.assertTrue(self._is_bot_placeholder(resp))

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

    def test_api_token_redacted_from_standard_backup(self):
        """The machine-API token grants full control over subscriptions, so it must
        never sit in cleartext inside a standard (unencrypted) backup — those are
        auto-delivered to Telegram."""
        self._login()
        from database import set_setting
        secret = 'super-secret-machine-token-xyz'
        set_setting('api_token', secret)

        resp = self.client.post('/adminpanel/api/backup/create',
                                data={'backup_type': 'standard'})
        data = json.loads(resp.data)
        self.assertTrue(data['success'])

        import zipfile
        from services.backup_service import BackupService
        path = os.path.join(BackupService.get_backup_dir(), data['filename'])
        try:
            with zipfile.ZipFile(path) as z:
                raw = z.read('database.json').decode('utf-8')
            self.assertIn('api_token', raw)      # the key is still exported…
            self.assertNotIn(secret, raw)        # …but its value is redacted
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass

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

    def test_restore_never_overwrites_the_live_database_file(self):
        """The archive carries a raw database.db snapshot, but restore must not
        copy it back: it would land on the live file while the restore
        transaction is still open, corrupting the database ("malformed database
        schema") and reverting the schema when the archive is from an older
        install. Rows come from database.json instead.

        Asserted by watching every file the restore writes: none of them may be
        the on-disk database."""
        import io
        import shutil
        import zipfile
        from unittest.mock import patch
        import utils.constants as constants

        self._login()
        self._add_config()

        resp_create = self.client.post('/adminpanel/api/backup/create', data={'backup_type': 'standard'})
        filename = json.loads(resp_create.data)['filename']
        zip_bytes = self.client.get(f'/adminpanel/api/backup/download/{filename}').data

        # The archive really does carry the raw DB file — otherwise this test
        # would pass for the wrong reason.
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
            self.assertIn('files/database.db', z.namelist())

        written = []
        real_copy2 = shutil.copy2

        def recording_copy2(src, dst, *a, **kw):
            written.append(os.path.abspath(dst))
            return real_copy2(src, dst, *a, **kw)

        with patch('services.backup_service.shutil.copy2', side_effect=recording_copy2):
            resp_res = self.client.post(
                '/adminpanel/api/backup/restore',
                data={'backup_file': (io.BytesIO(zip_bytes), filename), 'restore_env': 'false'},
                content_type='multipart/form-data')
        self.assertTrue(json.loads(resp_res.data)['success'])

        forbidden = os.path.abspath(os.path.join(constants.BASE_DIR, 'database.db'))
        self.assertNotIn(forbidden, written,
                         "restore copied the archived database.db over the live database file")

        from database import db_session
        with db_session() as db:
            self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0], 'ok')

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


class TestManualConfigTest(IntegrationTestBase):
    """On-demand ('test this config now') probing from the configs tab."""

    HEALTHY_URI = 'vmess://healthy-one'
    BROKEN_URI = 'vmess://broken-one'

    def setUp(self):
        super().setUp()
        import utils.constants as constants
        from services import automation_service

        self.automation_service = automation_service
        # Keep the shared result slot out of the project directory. A temp dir
        # (not mkstemp) because the writer os.replace()s onto this path, which
        # Windows refuses while mkstemp still holds the file open.
        self.state_dir = tempfile.mkdtemp()
        constants.MANUAL_TEST_STATE_FILE = os.path.join(self.state_dir, 'state.json')

        self._orig_run_subprocess = automation_service.Runner.run_subprocess
        # probe_timeout_args() shells out to `worker --help`; short-circuit it.
        self._orig_supports_flag = automation_service.worker_supports_flag
        automation_service.worker_supports_flag = lambda path, flag: False

    def tearDown(self):
        self.automation_service.Runner.run_subprocess = self._orig_run_subprocess
        self.automation_service.worker_supports_flag = self._orig_supports_flag
        import shutil
        shutil.rmtree(self.state_dir, ignore_errors=True)
        super().tearDown()

    def _stub_engine(self):
        """Make the engine report HEALTHY_URI as fast and BROKEN_URI as dead."""
        payload = {
            'schema_version': 1,
            'success': True,
            'worker_version': 'test',
            'job_id': 'test',
            'duration_ms': 5,
            'results': [
                {'uri': self.HEALTHY_URI, 'protocol': 'vmess', 'reachable': True,
                 'latency_ms': 142, 'country_code': 'DE', 'validation': 'active_http',
                 'error': None, 'source': 'manual'},
                {'uri': self.BROKEN_URI, 'protocol': 'vmess', 'reachable': False,
                 'latency_ms': None, 'country_code': None, 'validation': 'tcp_connect',
                 'error': 'connection refused', 'source': 'manual'},
            ],
        }
        self.automation_service.Runner.run_subprocess = (
            lambda cmd, input_json, timeout=600: (0, json.dumps(payload), '', 12)
        )

    def _seed(self, uri, **overrides):
        from database import get_db
        cols = {'consecutive_failures': 0, 'health_status': 'unknown',
                'is_enabled': 1, 'status': 'active', 'latency': None}
        cols.update(overrides)
        db = get_db()
        cur = db.execute(
            f'INSERT INTO configs (config_text, config_type, mode, '
            f'{", ".join(cols)}) VALUES (?, ?, ?, {", ".join("?" * len(cols))})',
            [uri, 'vmess', 'manual'] + list(cols.values())
        )
        db.commit()
        cid = cur.lastrowid
        db.close()
        return cid

    def _row(self, cid):
        from database import get_db
        db = get_db()
        row = db.execute('SELECT * FROM configs WHERE id = ?', (cid,)).fetchone()
        db.close()
        return row

    def test_reports_real_delay_and_records_it(self):
        self._stub_engine()
        cid = self._seed(self.HEALTHY_URI)

        ok, _msg, results = self.automation_service.AutomationService.run_manual_test([cid])

        self.assertTrue(ok)
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0]['reachable'])
        self.assertEqual(results[0]['latency_ms'], 142)
        self.assertEqual(results[0]['id'], cid)

        row = self._row(cid)
        self.assertEqual(row['latency'], 142)
        self.assertEqual(row['health_status'], 'healthy')
        self.assertIsNotNone(row['last_check'])

    def test_failed_probe_reports_the_error(self):
        self._stub_engine()
        cid = self._seed(self.BROKEN_URI)

        ok, _msg, results = self.automation_service.AutomationService.run_manual_test([cid])

        self.assertTrue(ok)  # the run succeeded; the config did not
        self.assertFalse(results[0]['reachable'])
        self.assertIsNone(results[0]['latency_ms'])
        self.assertEqual(results[0]['error'], 'connection refused')

    def test_failed_probe_never_disables_or_deletes(self):
        """The whole point of a manual test: it reads, it does not prune.

        The config is seeded one failure short of the threshold with the
        cleanup policy set to 'delete' — the scheduled health check would
        remove it here.
        """
        from database import set_setting
        set_setting('failure_threshold', '2')
        set_setting('cleanup_policy', 'delete')

        self._stub_engine()
        cid = self._seed(self.BROKEN_URI, consecutive_failures=1, health_status='healthy')

        ok, _msg, _results = self.automation_service.AutomationService.run_manual_test([cid])
        self.assertTrue(ok)

        row = self._row(cid)
        self.assertEqual(row['status'], 'active', 'manual test must not delete a config')
        self.assertEqual(row['is_enabled'], 1, 'manual test must not disable a config')
        self.assertEqual(row['consecutive_failures'], 1,
                         'manual test must not count toward the cleanup threshold')

    def test_endpoint_starts_job_and_status_returns_results(self):
        self._stub_engine()
        cid = self._seed(self.HEALTHY_URI)
        self._login()

        resp = json.loads(self.client.post(
            '/adminpanel/config/test',
            json={'ids': [cid]},
        ).data)
        self.assertTrue(resp['success'], resp)
        job_id = resp['job_id']
        self.assertTrue(job_id)

        # The probe runs on a background thread; wait for it to publish.
        for _ in range(50):
            status = json.loads(self.client.get(
                f'/adminpanel/config/test/status?job_id={job_id}'
            ).data)
            if status['state'] != 'running':
                break
            time.sleep(0.1)

        self.assertEqual(status['state'], 'done', status)
        self.assertEqual(status['results'][0]['latency_ms'], 142)

    def test_status_of_a_superseded_job_is_not_reported_as_running(self):
        self._stub_engine()
        self._login()
        status = json.loads(self.client.get(
            '/adminpanel/config/test/status?job_id=does-not-exist'
        ).data)
        self.assertEqual(status['state'], 'unknown')

    def test_rejects_oversized_selection(self):
        ok, msg, job_id = self.automation_service.AutomationService.start_manual_test(
            list(range(1, self.automation_service.MANUAL_TEST_MAX_CONFIGS + 2))
        )
        self.assertFalse(ok)
        self.assertIsNone(job_id)
        self.assertIn(str(self.automation_service.MANUAL_TEST_MAX_CONFIGS), msg)

    def test_requires_login(self):
        resp = self.client.post('/adminpanel/config/test', json={'ids': [1]})
        self.assertEqual(resp.status_code, 401)


class TestMachineApi(IntegrationTestBase):
    """Token-authenticated /api/v1 machine API used by an external sales bot."""

    _TOKEN = 'test-machine-token-abc123'

    def _set_token(self, value=_TOKEN):
        from database import set_setting
        set_setting('api_token', value)

    def _auth(self, token=_TOKEN):
        return {'Authorization': f'Bearer {token}'}

    def _create(self, name='ربات‌ساز', days=30, max_devices=2):
        return self.client.post(
            '/api/v1/subs',
            data=json.dumps({'name': name, 'duration_days': days, 'max_devices': max_devices}),
            content_type='application/json', headers=self._auth())

    # ── auth ──
    def test_disabled_when_no_token(self):
        # Fresh install: api_token is '' -> API disabled (503), even with a header.
        resp = self.client.get('/api/v1/health', headers=self._auth('anything'))
        self.assertEqual(resp.status_code, 503)

    def test_wrong_token_rejected(self):
        self._set_token()
        resp = self.client.get('/api/v1/health', headers=self._auth('wrong-token'))
        self.assertEqual(resp.status_code, 401)

    def test_missing_header_rejected(self):
        self._set_token()
        resp = self.client.get('/api/v1/health')
        self.assertEqual(resp.status_code, 401)

    def test_health_ok_with_token(self):
        self._set_token()
        resp = self.client.get('/api/v1/health', headers=self._auth())
        self.assertEqual(resp.status_code, 200)
        body = json.loads(resp.data)
        self.assertTrue(body['ok'])
        self.assertEqual(body['service'], 'v2raysub')

    # ── create ──
    def test_create_returns_sub_url(self):
        self._set_token()
        resp = self._create()
        self.assertEqual(resp.status_code, 201)
        body = json.loads(resp.data)
        self.assertTrue(body['success'])
        sub = body['subscription']
        self.assertIn('/sub/', sub['sub_url'])
        self.assertEqual(sub['duration_days'], 30)
        self.assertEqual(sub['max_devices'], 2)
        self.assertEqual(sub['effective_status'], 'ACTIVE')

    def test_create_with_duplicate_path_is_idempotent_conflict(self):
        """A caller supplying its own deterministic path (an order id) must get a
        retry-safe create: the duplicate is a distinct machine-readable conflict
        carrying the existing subscription, so a retried payment webhook recovers
        the original rather than minting a second one."""
        self._set_token()
        body = {'name': 'order-42', 'duration_days': 30, 'path': 'order000042'}
        first = self.client.post('/api/v1/subs', data=json.dumps(body),
                                 content_type='application/json', headers=self._auth())
        self.assertEqual(first.status_code, 201)
        first_id = json.loads(first.data)['subscription']['id']

        retry = self.client.post('/api/v1/subs', data=json.dumps(body),
                                 content_type='application/json', headers=self._auth())
        self.assertEqual(retry.status_code, 409)
        retry_body = json.loads(retry.data)
        self.assertEqual(retry_body['error'], 'path_taken')
        self.assertEqual(retry_body['subscription']['id'], first_id)

        # A different failure must stay distinguishable from the conflict — including
        # when it arrives together with the duplicate path, or a retry that fixed the
        # real problem would read the 409 as "already created" and give up.
        bad = self.client.post('/api/v1/subs',
                               data=json.dumps({'name': 'x', 'duration_days': -5}),
                               content_type='application/json', headers=self._auth())
        self.assertEqual(bad.status_code, 400)
        self.assertEqual(json.loads(bad.data)['error'], 'invalid_request')

        both = self.client.post('/api/v1/subs',
                                data=json.dumps({'name': 'x', 'path': 'order000042',
                                                 'duration_days': -5}),
                                content_type='application/json', headers=self._auth())
        self.assertEqual(both.status_code, 400)
        self.assertEqual(json.loads(both.data)['error'], 'invalid_request')

        # Exactly one subscription exists.
        listed = json.loads(self.client.get('/api/v1/subs', headers=self._auth()).data)
        self.assertEqual(listed['count'], 1)

    def test_create_colliding_with_legacy_path_is_not_a_conflict(self):
        """A path clashing with the legacy global-paths table has no subscription to
        hand back, so it must not be reported as a recoverable conflict."""
        self._set_token()
        from services.path_service import add_path
        add_path('legacypath01')
        resp = self.client.post('/api/v1/subs',
                                data=json.dumps({'name': 'x', 'path': 'legacypath01'}),
                                content_type='application/json', headers=self._auth())
        self.assertEqual(resp.status_code, 400)
        body = json.loads(resp.data)
        self.assertEqual(body['error'], 'create_failed')
        self.assertNotIn('subscription', body)

    def test_create_requires_name(self):
        self._set_token()
        resp = self.client.post('/api/v1/subs', data=json.dumps({'duration_days': 10}),
                                content_type='application/json', headers=self._auth())
        self.assertEqual(resp.status_code, 400)

    # ── read ──
    def test_get_sub(self):
        self._set_token()
        sub_id = json.loads(self._create().data)['subscription']['id']
        resp = self.client.get(f'/api/v1/subs/{sub_id}', headers=self._auth())
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(json.loads(resp.data)['subscription']['id'], sub_id)

    def test_get_missing_is_404(self):
        self._set_token()
        resp = self.client.get('/api/v1/subs/999999', headers=self._auth())
        self.assertEqual(resp.status_code, 404)

    # ── update (extend) ──
    def test_patch_extends_duration(self):
        self._set_token()
        sub_id = json.loads(self._create(days=30).data)['subscription']['id']
        resp = self.client.patch(f'/api/v1/subs/{sub_id}',
                                 data=json.dumps({'duration_days': 60}),
                                 content_type='application/json', headers=self._auth())
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(json.loads(resp.data)['subscription']['duration_days'], 60)

    # ── transitions ──
    def test_pause_and_resume(self):
        self._set_token()
        sub_id = json.loads(self._create().data)['subscription']['id']
        r1 = self.client.post(f'/api/v1/subs/{sub_id}/pause', headers=self._auth())
        self.assertEqual(json.loads(r1.data)['subscription']['status'], 'PAUSED')
        r2 = self.client.post(f'/api/v1/subs/{sub_id}/resume', headers=self._auth())
        self.assertEqual(json.loads(r2.data)['subscription']['status'], 'ACTIVE')

    def test_toggle_disable(self):
        self._set_token()
        sub_id = json.loads(self._create().data)['subscription']['id']
        resp = self.client.post(f'/api/v1/subs/{sub_id}/toggle',
                                data=json.dumps({'enabled': False}),
                                content_type='application/json', headers=self._auth())
        self.assertEqual(json.loads(resp.data)['subscription']['status'], 'DISABLED')

    # ── delete ──
    def test_delete_sub(self):
        self._set_token()
        sub_id = json.loads(self._create().data)['subscription']['id']
        resp = self.client.delete(f'/api/v1/subs/{sub_id}', headers=self._auth())
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(json.loads(resp.data)['success'])
        # Gone now.
        self.assertEqual(self.client.get(f'/api/v1/subs/{sub_id}',
                                         headers=self._auth()).status_code, 404)

    def test_token_endpoint_requires_login(self):
        resp = self.client.post('/adminpanel/api/api_token/generate')
        self.assertEqual(resp.status_code, 401)

    # ── list ──
    def test_list_subs(self):
        self._set_token()
        self._create(name='A')
        self._create(name='B')
        resp = self.client.get('/api/v1/subs', headers=self._auth())
        self.assertEqual(resp.status_code, 200)
        body = json.loads(resp.data)
        self.assertEqual(body['count'], 2)
        self.assertEqual({s['name'] for s in body['subscriptions']}, {'A', 'B'})

    def test_list_requires_token(self):
        self._set_token()
        self.assertEqual(self.client.get('/api/v1/subs').status_code, 401)

    # ── extend / renewal ──
    def _force_state(self, sub_id, activated_days_ago, expired_days_ago):
        """Pin a sub to an activated-and-expired state (UTC)."""
        from database import get_db
        db = get_db()
        db.execute("UPDATE users SET activated_at = datetime('now', ?), "
                   "expire_at = datetime('now', ?) WHERE id = ?",
                   (f'-{activated_days_ago} day', f'-{expired_days_ago} day', sub_id))
        db.commit()
        db.close()

    def test_extend_adds_days_to_active_sub(self):
        self._set_token()
        sub_id = json.loads(self._create(days=30).data)['subscription']['id']
        # Activate it by fetching the link, so a real expiry exists.
        path = json.loads(self.client.get(f'/api/v1/subs/{sub_id}',
                                          headers=self._auth()).data)['subscription']['path']
        self.client.get(f'/sub/{path}')
        before = json.loads(self.client.get(f'/api/v1/subs/{sub_id}',
                                            headers=self._auth()).data)['subscription']
        resp = self.client.post(f'/api/v1/subs/{sub_id}/extend',
                                data=json.dumps({'days': 15}),
                                content_type='application/json', headers=self._auth())
        self.assertEqual(resp.status_code, 200)
        after = json.loads(resp.data)['subscription']
        gained = after['remaining_seconds'] - before['remaining_seconds']
        self.assertAlmostEqual(gained, 15 * 86400, delta=120)
        self.assertEqual(after['duration_days'], 45)

    def test_extend_expired_sub_restarts_from_now(self):
        """The renewal bug guard: extending a sub that expired 10 days ago by 30
        must give a full 30 days, not 20 (which a delta-shift would produce)."""
        self._set_token()
        sub_id = json.loads(self._create(days=30).data)['subscription']['id']
        self._force_state(sub_id, activated_days_ago=40, expired_days_ago=10)
        self.assertEqual(json.loads(self.client.get(
            f'/api/v1/subs/{sub_id}', headers=self._auth()).data
        )['subscription']['effective_status'], 'EXPIRED')

        resp = self.client.post(f'/api/v1/subs/{sub_id}/extend',
                                data=json.dumps({'days': 30}),
                                content_type='application/json', headers=self._auth())
        after = json.loads(resp.data)['subscription']
        self.assertEqual(after['effective_status'], 'ACTIVE')
        self.assertAlmostEqual(after['remaining_seconds'], 30 * 86400, delta=120)

    def test_extend_not_yet_activated_only_grows_duration(self):
        self._set_token()
        sub_id = json.loads(self._create(days=30).data)['subscription']['id']
        resp = self.client.post(f'/api/v1/subs/{sub_id}/extend',
                                data=json.dumps({'days': 30}),
                                content_type='application/json', headers=self._auth())
        after = json.loads(resp.data)['subscription']
        self.assertEqual(after['duration_days'], 60)
        self.assertFalse(after['activated_at'])   # countdown still starts on first use

    def test_extend_unlimited_is_noop(self):
        self._set_token()
        sub_id = json.loads(self._create(days=0).data)['subscription']['id']
        resp = self.client.post(f'/api/v1/subs/{sub_id}/extend',
                                data=json.dumps({'days': 30}),
                                content_type='application/json', headers=self._auth())
        self.assertEqual(json.loads(resp.data)['subscription']['duration_days'], 0)

    def test_concurrent_extends_both_land(self):
        """Two renewals arriving at once (a retried payment webhook, say) must both
        count. A Python-side read-modify-write would have each read the same expiry
        and write the same result, so the customer would pay twice and gain one
        extension — the expiry is therefore computed inside the UPDATE itself."""
        import threading
        import database
        import services.user_service as us

        self._set_token()
        sub_id = json.loads(self._create(days=30).data)['subscription']['id']
        db = database.get_db()
        db.execute("UPDATE users SET activated_at = datetime('now'), "
                   "expire_at = datetime('now', '+30 day') WHERE id = ?", (sub_id,))
        db.commit()
        db.close()
        before = us.get_user(sub_id)['remaining_seconds']

        # Park each thread right after its SELECT so both have read the row before
        # either writes — the interleaving that loses an update.
        class SyncConn:
            def __init__(self, real, barrier):
                self._real, self._b, self._done = real, barrier, False

            def execute(self, sql, *a, **k):
                result = self._real.execute(sql, *a, **k)
                if not self._done and sql.strip().upper().startswith('SELECT'):
                    self._done = True
                    try:
                        self._b.wait(timeout=5)
                    except Exception:
                        pass
                return result

            def __getattr__(self, name):
                return getattr(self._real, name)

        barrier = threading.Barrier(2)
        real_get_db = database.get_db
        us.get_db = lambda: SyncConn(real_get_db(), barrier)
        try:
            threads = [threading.Thread(target=us.extend_user, args=(sub_id, 30),
                                        daemon=True) for _ in range(2)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=15)
        finally:
            us.get_db = real_get_db

        after = us.get_user(sub_id)
        gained = after['remaining_seconds'] - before
        self.assertAlmostEqual(gained, 60 * 86400, delta=300,
                               msg='both 30-day renewals must be counted')
        self.assertEqual(after['duration_days'], 90)

    def test_extend_rejects_non_positive_days(self):
        self._set_token()
        sub_id = json.loads(self._create().data)['subscription']['id']
        for bad in (0, -5, 'abc'):
            resp = self.client.post(f'/api/v1/subs/{sub_id}/extend',
                                    data=json.dumps({'days': bad}),
                                    content_type='application/json', headers=self._auth())
            self.assertEqual(resp.status_code, 400, f'days={bad!r} should be rejected')

    def test_extend_rejects_absurd_day_counts(self):
        """SQLite's datetime() returns NULL past year 9999, which would store "no
        expiry" on an activated subscription and leave it servable forever. A caller
        confusing units (seconds for days) must be rejected, not silently granted."""
        self._set_token()
        sub_id = json.loads(self._create(days=30).data)['subscription']['id']
        self.client.get(f"/sub/{json.loads(self.client.get(f'/api/v1/subs/{sub_id}', headers=self._auth()).data)['subscription']['path']}")
        resp = self.client.post(f'/api/v1/subs/{sub_id}/extend',
                                data=json.dumps({'days': 7776000}),
                                content_type='application/json', headers=self._auth())
        self.assertEqual(resp.status_code, 400)
        import services.user_service as us
        self.assertIsNotNone(us.get_user(sub_id)['expire_at'])

    def test_extend_rejects_non_integer_days(self):
        self._set_token()
        sub_id = json.loads(self._create().data)['subscription']['id']
        for bad in (True, 1.9, '30'):
            resp = self.client.post(f'/api/v1/subs/{sub_id}/extend',
                                    data=json.dumps({'days': bad}),
                                    content_type='application/json', headers=self._auth())
            self.assertEqual(resp.status_code, 400, f'days={bad!r} must be rejected')

    def test_extend_paused_sub_keeps_the_frozen_remainder(self):
        """A paused subscription's expiry is frozen with the real remainder held as
        (expire_at - paused_at), and resume adds the whole paused span back. Extending
        must not rebase to now, or the customer is gifted the entire pause."""
        self._set_token()
        import database
        import services.user_service as us
        sub_id = json.loads(self._create(days=30).data)['subscription']['id']
        db = database.get_db()
        db.execute("UPDATE users SET status = 'PAUSED', activated_at = datetime('now','-95 day'), "
                   "paused_at = datetime('now','-100 day'), "
                   "expire_at = datetime('now','-95 day') WHERE id = ?", (sub_id,))
        db.commit()
        db.close()

        self.client.post(f'/api/v1/subs/{sub_id}/extend', data=json.dumps({'days': 30}),
                         content_type='application/json', headers=self._auth())
        self.client.post(f'/api/v1/subs/{sub_id}/resume', headers=self._auth())
        remaining_days = us.get_user(sub_id)['remaining_seconds'] / 86400
        self.assertAlmostEqual(remaining_days, 35, delta=1,
                               msg='5 frozen days + 30 bought, not the 100-day pause')

    def test_toggle_rejects_non_boolean(self):
        """bool("false") is True, so coercing would turn a suspend into an enable."""
        self._set_token()
        import services.user_service as us
        sub_id = json.loads(self._create().data)['subscription']['id']
        us.set_user_enabled(sub_id, False)
        for bad in ('false', 'False', 0, 'no'):
            resp = self.client.post(f'/api/v1/subs/{sub_id}/toggle',
                                    data=json.dumps({'enabled': bad}),
                                    content_type='application/json', headers=self._auth())
            self.assertEqual(resp.status_code, 400, f'enabled={bad!r} must be rejected')
            self.assertEqual(us.get_user(sub_id)['status'], 'DISABLED')

    def test_negative_max_devices_rejected(self):
        """max_devices 0 means unlimited, so a negative value would lift the cap that
        prices the plan rather than tighten it."""
        self._set_token()
        sub_id = json.loads(self._create(max_devices=2).data)['subscription']['id']
        resp = self.client.patch(f'/api/v1/subs/{sub_id}',
                                 data=json.dumps({'max_devices': -1}),
                                 content_type='application/json', headers=self._auth())
        self.assertEqual(resp.status_code, 400)
        import services.user_service as us
        self.assertEqual(us.get_user(sub_id)['max_devices'], 2)
        create = self.client.post('/api/v1/subs',
                                  data=json.dumps({'name': 'x', 'max_devices': -999}),
                                  content_type='application/json', headers=self._auth())
        self.assertEqual(create.status_code, 400)

    def test_invalid_field_does_not_silently_drop_the_others(self):
        """A rejected max_devices used to leave an unbound placeholder that killed the
        whole UPDATE, so name/note/duration were dropped while the caller saw 400."""
        self._set_token()
        import services.user_service as us
        sub_id = json.loads(self._create().data)['subscription']['id']
        resp = self.client.patch(f'/api/v1/subs/{sub_id}',
                                 data=json.dumps({'name': 'RENAMED', 'duration_days': 90,
                                                  'max_devices': '3 devices'}),
                                 content_type='application/json', headers=self._auth())
        self.assertEqual(resp.status_code, 400)
        user = us.get_user(sub_id)
        self.assertNotEqual(user['name'], 'RENAMED')   # rejected as a whole, atomically
        self.assertEqual(user['duration_days'], 30)

    def test_non_ascii_token_is_rejected_not_a_server_error(self):
        """compare_digest raises on non-ASCII str, which would turn this pre-auth,
        rate-limit-exempt path into an unhandled 500."""
        self._set_token()
        resp = self.client.get('/api/v1/health',
                               headers={'Authorization': 'Bearer café'})
        self.assertEqual(resp.status_code, 401)

    # ── devices ──
    def test_list_and_reset_devices(self):
        self._set_token()
        # A config must exist for the sub to be served (and register a device).
        self.client.post('/adminpanel/login', data={
            'username': _TEST_USERNAME, 'password': _TEST_PASSWORD}, follow_redirects=True)
        self.client.post('/adminpanel/add', data={
            'config_text': 'vmess://eyJhZGQiOiJ0ZXN0LmNvbSIsInBvcnQiOiI0NDMiLCJ2IjoiMiJ9'})

        sub = json.loads(self._create(max_devices=2).data)['subscription']
        self.client.get(f"/sub/{sub['path']}", environ_overrides={'REMOTE_ADDR': '5.5.5.5'},
                        headers={'User-Agent': 'v2rayNG/1.0'})

        listed = json.loads(self.client.get(f"/api/v1/subs/{sub['id']}/devices",
                                            headers=self._auth()).data)
        self.assertEqual(listed['max_devices'], 2)
        self.assertEqual(listed['active_device_count'], 1)
        self.assertEqual(len(listed['devices']), 1)

        reset = self.client.post(f"/api/v1/subs/{sub['id']}/devices/reset",
                                 headers=self._auth())
        self.assertTrue(json.loads(reset.data)['success'])
        after = json.loads(self.client.get(f"/api/v1/subs/{sub['id']}/devices",
                                           headers=self._auth()).data)
        self.assertEqual(after['devices'], [])

    def test_devices_of_missing_sub_is_404(self):
        self._set_token()
        self.assertEqual(self.client.get('/api/v1/subs/999999/devices',
                                         headers=self._auth()).status_code, 404)

    # ── public_base_url ──
    def test_public_base_url_overrides_sub_url(self):
        """A configured public URL wins over the requesting host, so links handed
        to customers never point at an internal address the bot happened to use."""
        self._set_token()
        from database import set_setting
        set_setting('public_base_url', 'https://vpn.example.com')
        sub = json.loads(self._create().data)['subscription']
        self.assertTrue(sub['sub_url'].startswith('https://vpn.example.com/sub/'),
                        sub['sub_url'])

    def test_public_base_url_requires_a_bare_origin(self):
        """This value also builds the links shown in the admin panel, so a value like
        'https://' (which yields 'https://sub/abc') must be refused, not stored."""
        self._login()

        def save(value):
            return self.client.post('/adminpanel/api/settings/public_base_url',
                                    data=json.dumps({'public_base_url': value}),
                                    content_type='application/json').status_code

        for bad in ('example.com', 'https://', 'https://a.example/?x=1',
                    'https://a b.example', 'https://a.example/panel', 'ftp://a.example'):
            self.assertEqual(save(bad), 400, f'{bad!r} must be rejected')
        for good in ('https://a.example', 'HTTPS://a.example',
                     'https://a.example:8443', 'http://a.example/', ''):
            self.assertEqual(save(good), 200, f'{good!r} must be accepted')

    def test_base_url_is_resolved_once_per_request(self):
        """Building one link per row used to re-read the setting — and open a fresh
        SQLite connection — for every subscription in the list."""
        import sqlite3
        self._set_token()
        for i in range(12):
            self._create(name=f'u{i}')
        real_connect = sqlite3.connect
        count = [0]

        def counting(*args, **kwargs):
            count[0] += 1
            return real_connect(*args, **kwargs)

        sqlite3.connect = counting
        try:
            self.client.get('/api/v1/subs', headers=self._auth())
        finally:
            sqlite3.connect = real_connect
        self.assertLess(count[0], 12, f'opened {count[0]} connections for 12 rows')


if __name__ == '__main__':
    unittest.main()