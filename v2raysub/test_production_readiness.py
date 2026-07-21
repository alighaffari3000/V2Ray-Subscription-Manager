# -*- coding: utf-8 -*-
"""Production readiness and failure mode validation suite for V2RayDAR automation integration."""

import json
import os
import tempfile
import unittest
import time
import threading
import psutil
from werkzeug.security import generate_password_hash

# Patch env vars before importing database/app
_TEST_USERNAME = 'testadmin'
_TEST_PASSWORD = 'testpassword123'
_TEST_PASSWORD_HASH = generate_password_hash(_TEST_PASSWORD)

os.environ['ADMIN_USERNAME'] = _TEST_USERNAME
os.environ['ADMIN_PASSWORD'] = _TEST_PASSWORD_HASH
os.environ['SECRET_KEY'] = 'test-secret-key-for-production-readiness'

# Override V2RAYDAR_PATH to the mock batch file
current_dir = os.path.dirname(os.path.abspath(__file__))
mock_bat_path = os.path.join(current_dir, 'v2raydar_mock.bat').replace('\\', '/')
os.environ['V2RAYDAR_PATH'] = mock_bat_path

from app_factory import create_app
import utils.constants
from database import get_db, get_setting
from services.automation_service import AutomationService, ConfigImporter, SCAN_LOCK, Runner, terminate_all_subprocesses
from database import set_setting

class ProductionReadinessTestCase(unittest.TestCase):
    """Production readiness verification test suite."""

    def setUp(self):
        self.db_fd, self.db_path = tempfile.mkstemp(suffix='.db')
        utils.constants.DATABASE = self.db_path
        
        # Instantiate test app (tests bypass background scheduler initialization automatically)
        self.app = create_app(testing=True)
        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()

    def tearDown(self):
        # Force release automation lock if held by any test
        if SCAN_LOCK.locked():
            try:
                SCAN_LOCK.release()
            except Exception:
                pass
        
        terminate_all_subprocesses()
        self.app_context.pop()
        os.close(self.db_fd)
        try:
            os.unlink(self.db_path)
        except Exception:
            pass

    def test_e2e_discovery_and_health_check(self):
        """1. Real E2E Discovery and Health Check run using the mock worker subprocess."""
        # Add auto source
        db = get_db()
        db.execute(
            'INSERT INTO auto_sources (name, url, priority, is_enabled) VALUES (?, ?, ?, 1)',
            ('Main-Source', 'https://example.com/normal-sub-feed', 100)
        )
        db.commit()
        db.close()

        # Run discovery scan
        success, msg = AutomationService.run_scan('discovery')
        self.assertTrue(success)
        self.assertIn("Discovery completed", msg)

        # Verify configs table contains newly imported healthy configs
        db = get_db()
        configs = db.execute('SELECT * FROM configs WHERE status = "active"').fetchall()
        self.assertEqual(len(configs), 1) # only mock-healthy-from-Main-Source (unhealthy vless config is filtered)
        self.assertEqual(configs[0]['config_type'], 'vmess')
        self.assertEqual(configs[0]['mode'], 'auto')
        self.assertEqual(configs[0]['health_status'], 'healthy')
        self.assertEqual(configs[0]['source'], 'Main-Source')
        
        # Verify duplicate detection: running it again shouldn't duplicate active configs
        success2, msg2 = AutomationService.run_scan('discovery')
        self.assertTrue(success2)
        configs_after = db.execute('SELECT * FROM configs WHERE status = "active"').fetchall()
        self.assertEqual(len(configs_after), 1)

        # Verify scan_history logged successes and stats
        scans = db.execute('SELECT * FROM scan_history').fetchall()
        self.assertEqual(len(scans), 2)
        self.assertEqual(scans[0]['scan_type'], 'discovery')
        self.assertEqual(scans[0]['status'], 'success')
        self.assertIsNotNone(scans[0]['job_id'])
        self.assertEqual(scans[0]['total_sources'], 1)
        self.assertEqual(scans[0]['discovered_configs'], 2)
        self.assertEqual(scans[0]['working_configs'], 1)
        self.assertEqual(scans[0]['imported_configs'], 1)
        
        # Verify config_health_history contains the record
        history_rows = db.execute('SELECT * FROM config_health_history').fetchall()
        self.assertTrue(len(history_rows) >= 1)
        self.assertEqual(history_rows[0]['scan_id'], scans[0]['id'])
        self.assertEqual(history_rows[0]['reachable'], 1)
        
        # Verify auto_sources metadata update
        source_row = db.execute('SELECT * FROM auto_sources WHERE name = "Main-Source"').fetchone()
        self.assertIsNotNone(source_row['last_scan'])
        self.assertIsNotNone(source_row['last_success'])
        self.assertEqual(source_row['failure_count'], 0)
        db.close()

        # Run health check scan
        success_hc, msg_hc = AutomationService.run_scan('health_check')
        self.assertTrue(success_hc)
        self.assertIn("Health check completed", msg_hc)
        
        # Verify health check history record is logged for the tested config
        db = get_db()
        hc_history = db.execute('SELECT * FROM config_health_history WHERE scan_id = (SELECT id FROM scan_history WHERE scan_type="health_check")').fetchall()
        self.assertTrue(len(hc_history) >= 1)
        db.close()

    def test_discovery_replaces_worst_when_full(self):
        """When the pool is at capacity, discovery swaps the worst auto-config
        for a meaningfully faster new one and never touches manual configs."""
        def insert_active(uri, ctype, mode, latency):
            db = get_db()
            db.execute(
                '''INSERT INTO configs (
                    config_text, config_type, sort_order, is_enabled, status,
                    source, mode, last_check, last_success, latency,
                    consecutive_failures, health_status
                ) VALUES (?, ?, 0, 1, 'active', 'seed', ?, '2026-01-01 00:00:00',
                          '2026-01-01 00:00:00', ?, 0, 'healthy')''',
                (uri, ctype, mode, latency)
            )
            db.commit()
            db.close()

        # Pool is full (max_active=2): one slow auto config, one manual config.
        set_setting('max_active_configs', '2')
        set_setting('max_new_configs_per_scan', '10')
        set_setting('discovery_replace_when_full', '1')
        set_setting('cleanup_policy', 'disable')
        slow_auto = 'trojan://pass@slow-auto.example:443#slow-auto'
        manual_cfg = 'trojan://pass@manual.example:443#manual'
        insert_active(slow_auto, 'trojan', 'auto', 500)
        insert_active(manual_cfg, 'trojan', 'manual', 900)  # worst latency, but MANUAL

        # A much faster new candidate arrives from discovery.
        fast_new = 'trojan://pass@fast-new.example:443#fast-new'
        results = [{
            'uri': fast_new, 'reachable': True, 'latency_ms': 100,
            'source': 'FeedX', 'validation': 'active_http',
        }]
        added, dup, replaced = ConfigImporter.import_discovered_configs(
            results, '2026-07-21 00:00:00', scan_id=None
        )

        self.assertEqual(added, 0)      # no free capacity → pure addition adds nothing
        self.assertEqual(replaced, 1)   # exactly one swap happened

        db = get_db()
        # The faster config is now active + enabled.
        new_row = db.execute(
            'SELECT is_enabled, status FROM configs WHERE config_text = ?', (fast_new,)
        ).fetchone()
        self.assertIsNotNone(new_row)
        self.assertEqual(new_row['is_enabled'], 1)
        self.assertEqual(new_row['status'], 'active')

        # The worst AUTO config was retired (disabled).
        slow_row = db.execute(
            'SELECT is_enabled FROM configs WHERE config_text = ?', (slow_auto,)
        ).fetchone()
        self.assertEqual(slow_row['is_enabled'], 0)

        # The manual config is untouched even though it had the highest latency.
        manual_row = db.execute(
            'SELECT is_enabled FROM configs WHERE config_text = ?', (manual_cfg,)
        ).fetchone()
        self.assertEqual(manual_row['is_enabled'], 1)

        # Active+enabled count stays at capacity.
        active_cnt = db.execute(
            'SELECT COUNT(*) AS c FROM configs WHERE status="active" AND is_enabled=1'
        ).fetchone()['c']
        self.assertEqual(active_cnt, 2)
        db.close()

    def test_discovery_replacement_respects_margin(self):
        """A new config that is only marginally faster must NOT trigger a swap."""
        db = get_db()
        db.execute(
            '''INSERT INTO configs (
                config_text, config_type, sort_order, is_enabled, status,
                source, mode, last_check, last_success, latency,
                consecutive_failures, health_status
            ) VALUES (?, 'trojan', 0, 1, 'active', 'seed', 'auto',
                      '2026-01-01 00:00:00', '2026-01-01 00:00:00', 200, 0, 'healthy')''',
            ('trojan://pass@incumbent.example:443#incumbent',)
        )
        db.commit()
        db.close()

        set_setting('max_active_configs', '1')
        set_setting('max_new_configs_per_scan', '10')
        set_setting('discovery_replace_when_full', '1')

        # Only 10ms faster — below the 50ms improvement threshold.
        results = [{
            'uri': 'trojan://pass@barely.example:443#barely', 'reachable': True,
            'latency_ms': 190, 'source': 'FeedX', 'validation': 'active_http',
        }]
        added, dup, replaced = ConfigImporter.import_discovered_configs(
            results, '2026-07-21 00:00:00', scan_id=None
        )
        self.assertEqual(replaced, 0)
        db = get_db()
        incumbent = db.execute(
            "SELECT is_enabled FROM configs WHERE config_text LIKE 'trojan://pass@incumbent%'"
        ).fetchone()
        self.assertEqual(incumbent['is_enabled'], 1)
        db.close()

    def test_concurrency_locking(self):
        """2. Verify concurrency thread lock works for overlapping manual scans."""
        # Trigger a long running scan (timeout trigger will cause it to sleep)
        db = get_db()
        db.execute(
            'INSERT INTO auto_sources (name, url, priority, is_enabled) VALUES (?, ?, ?, 1)',
            ('Slow-Source', 'https://example.com/trigger-timeout', 100)
        )
        db.commit()
        db.close()

        # Start the first scan in a thread
        first_scan_thread = threading.Thread(
            target=AutomationService.run_scan,
            args=('discovery',),
            daemon=True
        )
        
        # Make Runner timeout longer for this test to allow overlaps
        first_scan_thread.start()
        time.sleep(1) # wait for lock acquisition and command execution to start
        
        # Verify the lock is active
        self.assertTrue(SCAN_LOCK.locked())
        
        # Attempt second scan trigger concurrently
        success_second, msg_second = AutomationService.run_scan('discovery')
        self.assertFalse(success_second)
        self.assertEqual(msg_second, "Another scan is already in progress.")

    def test_concurrency_bounds_validation(self):
        """3. Process Concurrency Bounds Validation: Verify values outside [1, 128] are fallback-safe."""
        # Add invalid config bounds inside database settings
        db = get_db()
        db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('fetch_concurrency', '-10')")
        db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('probe_concurrency', '500')")
        db.commit()
        db.close()

        # Trigger normal discovery scan
        db = get_db()
        db.execute(
            'INSERT INTO auto_sources (name, url, priority, is_enabled) VALUES (?, ?, ?, 1)',
            ('Bounds-Source', 'https://example.com/normal-bounds', 100)
        )
        db.commit()
        db.close()

        success, msg = AutomationService.run_scan('discovery')
        self.assertTrue(success)
        self.assertIn("Discovery completed", msg)

    def test_failure_modes(self):
        """4. Verify backend failure resilience for invalid path, worker timeout, invalid JSON, unsupported schema, non-zero exits."""
        # A. Invalid V2RAYDAR_PATH
        os.environ['V2RAYDAR_PATH'] = 'f:/Telegram Bots/nonexistent-v2raydar.exe'
        
        # Insert a mock config to prevent health check skip
        db = get_db()
        db.execute("INSERT OR REPLACE INTO configs (config_text, config_type, mode, health_status, status) VALUES ('ss://some-config', 'shadowsocks', 'manual', 'healthy', 'active')")
        db.commit()
        db.close()
        
        success, msg = AutomationService.run_scan('health_check')
        if success:
            print("WARNING: health check succeeded unexpectedly with invalid V2RAYDAR_PATH")
        else:
            print("CORRECT: health check failed as expected with invalid V2RAYDAR_PATH. Msg:", msg)
        self.assertFalse(success)
        self.assertIn("Worker process failed", msg)
        self.assertFalse(SCAN_LOCK.locked()) # Verify lock was released!
        
        # Reset batch path
        os.environ['V2RAYDAR_PATH'] = mock_bat_path

        # B. Worker Timeout
        db = get_db()
        db.execute(
            'INSERT INTO auto_sources (name, url, priority, is_enabled) VALUES (?, ?, ?, 1)',
            ('Timeout-Source', 'https://example.com/trigger-timeout', 100)
        )
        db.commit()
        db.close()
        
        # Run subprocess with extremely short timeout to force timeout on 10s sleep
        # Mock run_subprocess default timeout parameter or invoke Runner directly
        ret, stdout, stderr, dur = Runner.run_subprocess([mock_bat_path, "worker", "discovery"], "trigger-timeout", timeout=1)
        self.assertEqual(ret, -1)
        self.assertIn("Timeout expired", stderr)

        # C. Invalid JSON Output
        db = get_db()
        db.execute('DELETE FROM auto_sources')
        db.execute(
            'INSERT INTO auto_sources (name, url, priority, is_enabled) VALUES (?, ?, ?, 1)',
            ('Invalid-Json-Source', 'https://example.com/trigger-invalid-json', 100)
        )
        db.commit()
        db.close()
        
        success_json, msg_json = AutomationService.run_scan('discovery')
        self.assertFalse(success_json)
        self.assertIn("Parser error", msg_json)
        self.assertFalse(SCAN_LOCK.locked()) # Lock released

        # D. Unsupported schema_version
        db = get_db()
        db.execute('DELETE FROM auto_sources')
        db.execute(
            'INSERT INTO auto_sources (name, url, priority, is_enabled) VALUES (?, ?, ?, 1)',
            ('Schema-Source', 'https://example.com/trigger-unsupported-schema', 100)
        )
        db.commit()
        db.close()
        
        success_schema, msg_schema = AutomationService.run_scan('discovery')
        self.assertFalse(success_schema)
        self.assertIn("Parser error", msg_schema)
        self.assertFalse(SCAN_LOCK.locked())

        # E. Non-zero worker exit code
        db = get_db()
        db.execute('DELETE FROM auto_sources')
        db.execute(
            'INSERT INTO auto_sources (name, url, priority, is_enabled) VALUES (?, ?, ?, 1)',
            ('Exit-Source', 'https://example.com/trigger-nonzero-exit', 100)
        )
        db.commit()
        db.close()
        
        success_exit, msg_exit = AutomationService.run_scan('discovery')
        self.assertFalse(success_exit)
        self.assertIn("Worker process failed", msg_exit)
        self.assertFalse(SCAN_LOCK.locked())

        # F. Worker Crash
        db = get_db()
        db.execute('DELETE FROM auto_sources')
        db.execute(
            'INSERT INTO auto_sources (name, url, priority, is_enabled) VALUES (?, ?, ?, 1)',
            ('Crash-Source', 'https://example.com/trigger-crash', 100)
        )
        db.commit()
        db.close()
        
        success_crash, msg_crash = AutomationService.run_scan('discovery')
        self.assertFalse(success_crash)
        self.assertIn("Worker process failed", msg_crash)
        self.assertFalse(SCAN_LOCK.locked())

    def test_large_payload_benchmark(self):
        """5. Benchmark discovery using 2,000 configurations."""
        db = get_db()
        db.execute(
            'INSERT INTO auto_sources (name, url, priority, is_enabled) VALUES (?, ?, ?, 1)',
            ('Benchmark-Source', 'https://example.com/trigger-benchmark', 100)
        )
        db.commit()
        db.close()

        # Measure memory and duration
        process = psutil.Process(os.getpid())
        mem_before = process.memory_info().rss
        start_time = time.monotonic()

        success, msg = AutomationService.run_scan('discovery')
        
        duration = time.monotonic() - start_time
        mem_after = process.memory_info().rss
        mem_growth_mb = (mem_after - mem_before) / (1024 * 1024)

        # Assertions
        if not success:
            print("BENCHMARK SCAN FAILED. Msg:", msg)
        self.assertTrue(success)
        self.assertIn("Discovery completed", msg)
        self.assertFalse(SCAN_LOCK.locked()) # Lock released
        
        # Verify duplicate detection limits
        db = get_db()
        configs = db.execute('SELECT * FROM configs WHERE status = "active"').fetchall()
        self.assertEqual(len(configs), 10) # max_new_configs_per_scan setting default is 10!
        db.close()

        # Check acceptable limits (e.g. duration <= 10s, memory growth <= 50MB)
        self.assertLessEqual(duration, 10.0)
        self.assertLessEqual(mem_growth_mb, 50.0)

    def test_process_cancellation(self):
        """6. Validate subprocess termination and lock cleanup during application shutdown."""
        db = get_db()
        db.execute(
            'INSERT INTO auto_sources (name, url, priority, is_enabled) VALUES (?, ?, ?, 1)',
            ('Cancel-Source', 'https://example.com/trigger-timeout', 100)
        )
        db.commit()
        db.close()

        scan_outcome = []
        def run_wrapper():
            res = AutomationService.run_scan('discovery')
            scan_outcome.append(res)

        # Trigger slow-running scan in background
        scan_thread = threading.Thread(
            target=run_wrapper,
            daemon=True
        )
        scan_thread.start()
        time.sleep(1) # wait for subprocess launch
        
        # Verify lock and subprocess active
        if not SCAN_LOCK.locked():
            print("CANCELLATION SCAN THREAD EXITED PREMATURELY. Outcome:", scan_outcome)
        self.assertTrue(SCAN_LOCK.locked())
        
        # Call graceful cancel_scan
        AutomationService.cancel_scan()
        
        # Wait for thread execution to exit and naturally release the lock
        time.sleep(2)
        
        self.assertFalse(SCAN_LOCK.locked())
            
        # Verify subsequent scan can run cleanly without lock collision
        db = get_db()
        db.execute('DELETE FROM auto_sources')
        db.execute(
            'INSERT INTO auto_sources (name, url, priority, is_enabled) VALUES (?, ?, ?, 1)',
            ('Fresh-Source', 'https://example.com/normal-sub-feed', 100)
        )
        db.commit()
        db.close()
        
        success, msg = AutomationService.run_scan('discovery')
        self.assertTrue(success)
        self.assertIn("Discovery completed", msg)

    def test_api_cancellation_endpoint(self):
        """7. Verify Flask cancel endpoint cancels scan and naturally releases lock."""
        # Log in to Flask test client
        with self.client.session_transaction() as sess:
            sess['logged_in'] = True

        db = get_db()
        db.execute(
            'INSERT INTO auto_sources (name, url, priority, is_enabled) VALUES (?, ?, ?, 1)',
            ('Cancel-Source-Api', 'https://example.com/trigger-timeout', 100)
        )
        db.commit()
        db.close()

        threading.Thread(
            target=AutomationService.run_scan,
            args=('discovery',),
            daemon=True
        ).start()
        time.sleep(1)

        self.assertTrue(SCAN_LOCK.locked())

        # Post to cancel route
        resp = self.client.post('/adminpanel/automation/cancel')
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertTrue(data['success'])
        self.assertIn("درخواست لغو اسکن با موفقیت ارسال شد", data['message'])

        # Wait for thread to exit
        time.sleep(2)
        self.assertFalse(SCAN_LOCK.locked())

        # Verify scan history lists last run as cancelled
        db = get_db()
        scan = db.execute('SELECT * FROM scan_history ORDER BY id DESC LIMIT 1').fetchone()
        self.assertEqual(scan['status'], 'cancelled')
        db.close()


if __name__ == '__main__':
    unittest.main()
