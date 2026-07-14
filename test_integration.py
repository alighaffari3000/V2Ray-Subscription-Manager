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
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()

    def tearDown(self):
        os.close(self.db_fd)
        os.unlink(self.db_path)

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
        resp = self.client.get('/adminpanel/logout', follow_redirects=False)
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


class TestPaths(IntegrationTestBase):
    """Issue 2 & 4: Path listing, adding (FormData), generating, enabling, deleting."""

    def test_list_paths(self):
        self._login()
        resp = self.client.get('/adminpanel/paths')
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertIsInstance(data, list)
        # Should have at least the default 'freeconfigs' path
        self.assertGreaterEqual(len(data), 1)

    def test_add_path_formdata(self):
        """Issue 4: Frontend sends FormData with path=<value> to change primary path."""
        self._login()
        new_path = 'testpath123'
        resp = self.client.post('/adminpanel/paths/add', data={'path': new_path})
        data = json.loads(resp.data)
        self.assertTrue(data['success'])
        self.assertEqual(data['current_path'], new_path)
        self.assertTrue(data['current_url'].endswith(f'/sub/{new_path}'))

        # Verify the path is now primary
        paths_resp = self.client.get('/adminpanel/paths')
        paths = json.loads(paths_resp.data)
        primary_paths = [p for p in paths if p.get('is_primary')]
        self.assertEqual(len(primary_paths), 1)
        self.assertEqual(primary_paths[0]['path'], new_path)

        # Verify subscription works
        sub_resp = self.client.get(f'/sub/{new_path}')
        self.assertEqual(sub_resp.status_code, 200)

    def test_add_path_json(self):
        self._login()
        resp = self.client.post('/adminpanel/paths/add',
                                data=json.dumps({'path': 'jsonpath456'}),
                                content_type='application/json')
        data = json.loads(resp.data)
        self.assertTrue(data['success'])

    def test_add_empty_path_formdata(self):
        """Empty form submission should return JSON validation error, not HTTP 415."""
        self._login()
        resp = self.client.post('/adminpanel/paths/add', data={'path': ''})
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertFalse(data['success'])
        self.assertIn('message', data)

    def test_add_empty_path_no_content_type(self):
        """Submitting with no content-type should not raise 415."""
        self._login()
        resp = self.client.post('/adminpanel/paths/add', data='path=')
        # Should get 200 with JSON validation error, not 415
        self.assertIn(resp.status_code, (200, 400))
        if resp.status_code == 200:
            data = json.loads(resp.data)
            self.assertFalse(data['success'])

    def test_generate_random_get(self):
        """Issue 2: Frontend calls GET, not just POST."""
        self._login()
        resp = self.client.get('/adminpanel/paths/generate_random')
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertTrue(data['success'])
        self.assertIn('path', data)
        self.assertTrue(len(data['path']) > 0)

    def test_generate_random_post(self):
        self._login()
        resp = self.client.post('/adminpanel/paths/generate_random')
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertTrue(data['success'])

    def test_delete_secondary_path(self):
        self._login()
        # First, add a path that will become secondary
        new_path = 'deleteme'
        add_resp = self.client.post('/adminpanel/paths/add', data={'path': new_path})
        add_data = json.loads(add_resp.data)
        self.assertTrue(add_data['success'], f"Failed to add path: {add_resp.data}")

        # Now add another path which becomes primary, making the first one secondary
        primary_path = 'primarypath'
        self.client.post('/adminpanel/paths/add', data={'path': primary_path})

        # Get the path ID of the secondary path
        paths_resp = self.client.get('/adminpanel/paths')
        paths = json.loads(paths_resp.data)
        added_path = [p for p in paths if p['path'] == new_path]
        self.assertTrue(len(added_path) > 0, f"Path not found in list: {paths_resp.data}")
        path_id = added_path[0]['id']

        # Verify the path is not primary anymore
        self.assertFalse(added_path[0].get('is_primary', False), "Path should have become secondary")

        # Verify the path exists before deletion
        paths_resp = self.client.get('/adminpanel/paths')
        paths_before = json.loads(paths_resp.data)
        path_exists = any(p['id'] == path_id for p in paths_before)
        self.assertTrue(path_exists, f"Path with ID {path_id} not found before deletion")

        # Delete the path
        resp = self.client.post(f'/adminpanel/paths/delete/{path_id}')
        data = json.loads(resp.data)
        self.assertTrue(data['success'], f"Failed to delete path: {resp.data}")

        # Verify the path is actually deleted
        paths_resp = self.client.get('/adminpanel/paths')
        paths_after = json.loads(paths_resp.data)
        deleted_path = [p for p in paths_after if p['id'] == path_id]
        self.assertEqual(len(deleted_path), 0, f"Path still exists after deletion: {paths_resp.data}")

        # Verify the path is not in the list of paths
        paths_resp = self.client.get('/adminpanel/paths')
        paths = json.loads(paths_resp.data)
        paths_with_same_id = [p for p in paths if p['id'] == path_id]
        self.assertEqual(len(paths_with_same_id), 0, f"Path with same ID still exists: {paths_resp.data}")

        # Verify the path count decreased by 1
        self.assertEqual(len(paths_after), len(paths_before) - 1, f"Path count didn't decrease by 1: before {len(paths_before)}, after {len(paths_after)}")

        # Verify the primary path still exists
        primary_exists = any(p['path'] == primary_path for p in paths_after)
        self.assertTrue(primary_exists, "Primary path was deleted when it shouldn't have been")

        # Verify the primary path is still marked as primary
        primary_paths = [p for p in paths_after if p.get('is_primary')]
        self.assertEqual(len(primary_paths), 1, "There should be exactly one primary path")
        self.assertEqual(primary_paths[0]['path'], primary_path, "The primary path should be the original one")

        # Verify the secondary path was actually deleted
        secondary_exists = any(p['path'] == new_path for p in paths_after)
        self.assertFalse(secondary_exists, "Secondary path was not properly deleted")

        # Verify the path ID is no longer in use
        paths_resp = self.client.get('/adminpanel/paths')
        paths = json.loads(paths_resp.data)
        ids = [p['id'] for p in paths]
        self.assertNotIn(path_id, ids, f"Path ID {path_id} should not be in use after deletion")

    def test_cannot_delete_primary_path(self):
        self._login()
        paths_resp = self.client.get('/adminpanel/paths')
        paths = json.loads(paths_resp.data)
        primary = [p for p in paths if p.get('is_primary')]
        self.assertTrue(primary, "No primary path found to test deletion")

        resp = self.client.post(f'/adminpanel/paths/delete/{primary[0]["id"]}')
        data = json.loads(resp.data)
        self.assertFalse(data['success'], "Primary path deletion should fail")

        # Verify the path still exists
        paths_resp = self.client.get('/adminpanel/paths')
        paths_after = json.loads(paths_resp.data)
        path_still_exists = any(p['id'] == primary[0]['id'] for p in paths_after)
        self.assertTrue(path_still_exists, "Primary path was deleted when it shouldn't have been")


class TestSubscription(IntegrationTestBase):
    """Subscription endpoint returns configs for valid paths."""

    def test_default_subscription(self):
        self._login()
        # Add a config
        self.client.post('/adminpanel/add', data={
            'config_text': 'vmess://eyJhZGQiOiJ0ZXN0LmNvbSIsInBvcnQiOiI0NDMiLCJ2IjoiMiJ9'
        })
        # Fetch subscription on default path
        resp = self.client.get('/sub/freeconfigs')
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
        ]
        for method, url in endpoints:
            if method == 'GET':
                resp = self.client.get(url)
            else:
                resp = self.client.post(url)
            self.assertEqual(resp.status_code, 401,
                             f'{method} {url} should return 401 without login')


if __name__ == '__main__':
    unittest.main()