# -*- coding: utf-8 -*-
"""Decomposed and orchestrated scan service running the V2RayDAR executable."""

import subprocess
import time
import json
import os
import threading
import datetime
import shutil
import atexit
import uuid
from database import get_db, get_setting
from utils.config_parser import detect_config_type, get_config_identity
import utils.constants as constants
from utils.process_lock import InterProcessLock

# In-process lock (fast path) + file lock shared between gunicorn workers.
# A threading.Lock alone cannot prevent two worker processes from scanning
# concurrently, which caused duplicate imports and doubled load.
SCAN_LOCK = threading.Lock()
SCAN_FILE_LOCK = InterProcessLock(constants.SCAN_LOCK_FILE)


def is_scan_active():
    """True if a scan is running in this or any other worker process."""
    return SCAN_LOCK.locked() or SCAN_FILE_LOCK.is_locked_elsewhere()

def get_validated_concurrency(key, default):
    """Retrieve and validate concurrency config parameter from settings.
    
    Enforces the bound: 1 <= val <= 128. Returns default if invalid or out of bounds.
    """
    raw = get_setting(key, str(default))
    try:
        val = int(raw)
        if 1 <= val <= 128:
            return val
        else:
            print(f"Validation Warning: setting '{key}' value {val} is out of bounds [1, 128]. Falling back to default: {default}")
            return default
    except (ValueError, TypeError) as e:
        print(f"Validation Error: setting '{key}' value '{raw}' is not a valid integer: {e}. Falling back to default: {default}")
        return default

def locate_v2raydar():
    """Locate the V2RayDAR executable dynamically or via .env settings."""
    env_path = os.getenv('V2RAYDAR_PATH')
    if env_path and os.path.exists(env_path):
        return env_path
    
    # Calculate workspace paths relative to this script
    script_dir = os.path.dirname(os.path.abspath(__file__)) # v2raysub/services
    v2raysub_dir = os.path.dirname(script_dir)             # v2raysub
    workspace_root = os.path.dirname(v2raysub_dir)          # workspace root
    
    candidates = [
        os.path.join(workspace_root, 'V2RayDAR-main', 'target', 'release', 'v2raydar.exe'),
        os.path.join(workspace_root, 'V2RayDAR-main', 'target', 'debug', 'v2raydar.exe'),
        os.path.join(workspace_root, 'V2RayDAR-main', 'target', 'release', 'v2raydar'),
        os.path.join(workspace_root, 'V2RayDAR-main', 'target', 'debug', 'v2raydar'),
        os.path.join(v2raysub_dir, 'V2RayDAR-main', 'target', 'release', 'v2raydar'),
        os.path.join(v2raysub_dir, 'V2RayDAR-main', 'target', 'debug', 'v2raydar'),
        os.path.join(v2raysub_dir, 'v2raydar.exe'),
        os.path.join(v2raysub_dir, 'v2raydar'),
        'v2raydar.exe',
        'v2raydar'
    ]
    
    for path in candidates:
        if os.path.isabs(path) and os.path.exists(path):
            return path
        resolved = shutil.which(path)
        if resolved:
            return resolved
            
    return 'v2raydar' # fallback


_ACTIVE_SUBPROCESSES = []
_SUBPROCESSES_LOCK = threading.Lock()

def terminate_all_subprocesses():
    with _SUBPROCESSES_LOCK:
        for proc in _ACTIVE_SUBPROCESSES:
            try:
                if proc.poll() is None:
                    if os.name == 'nt':
                        # On Windows, kill the process tree forcefully using taskkill to prevent orphaned children keeping pipes open
                        subprocess.run(['taskkill', '/F', '/T', '/PID', str(proc.pid)], capture_output=True)
                    else:
                        proc.terminate()
                        proc.wait(timeout=2)
            except Exception:
                pass
        _ACTIVE_SUBPROCESSES.clear()

@atexit.register
def cleanup_on_exit():
    terminate_all_subprocesses()
    try:
        SCAN_FILE_LOCK.release()
    except Exception:
        pass
    try:
        if SCAN_LOCK.locked():
            SCAN_LOCK.release()
    except Exception:
        pass


def _watch_for_cancel(proc):
    """Poll the shared cancel flag so a cancel issued from another worker
    process (the flag file) also kills a scan running in this process."""
    while proc.poll() is None:
        if is_cancel_requested():
            terminate_all_subprocesses()
            return
        time.sleep(1)


class Runner:
    """Invokes V2RayDAR subprocess synchronously exchanging JSON via standard streams."""
    
    @staticmethod
    def run_subprocess(command_args, input_json, timeout=600):
        start_time = time.monotonic()
        try:
            proc = subprocess.Popen(
                command_args,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            with _SUBPROCESSES_LOCK:
                _ACTIVE_SUBPROCESSES.append(proc)

            threading.Thread(target=_watch_for_cancel, args=(proc,), daemon=True).start()

            try:
                stdout, stderr = proc.communicate(input=input_json, timeout=timeout)
                ret_code = proc.returncode
            except subprocess.TimeoutExpired as e:
                proc.kill()
                stdout, stderr = proc.communicate()
                duration_ms = int((time.monotonic() - start_time) * 1000)
                return -1, "", f"Timeout expired after {timeout}s: {e}", duration_ms
            finally:
                with _SUBPROCESSES_LOCK:
                    if proc in _ACTIVE_SUBPROCESSES:
                        _ACTIVE_SUBPROCESSES.remove(proc)
            
            duration_ms = int((time.monotonic() - start_time) * 1000)
            return ret_code, stdout, stderr, duration_ms
        except Exception as e:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            return -1, "", f"Execution failed: {str(e)}", duration_ms


class ResultParser:
    """Parses JSON stdout and verifies version compatibility rules."""
    
    @staticmethod
    def parse(stdout_str):
        try:
            data = json.loads(stdout_str)
        except Exception as e:
            raise ValueError(f"Failed to parse stdout JSON: {e}")
        
        schema_version = data.get("schema_version")
        if schema_version != 1:
            raise ValueError(f"Unsupported schema version: expected 1, got {schema_version}")
        
        if not data.get("success"):
            error_msg = data.get("error", "Unknown worker error")
            raise ValueError(f"Worker reported failure: {error_msg}")
            
        return data


class ConfigImporter:
    """Deduplicates healthy configs and controls imports under capacity limits."""
    
    @staticmethod
    def import_discovered_configs(results, scan_time_str, scan_id=None):
        db = get_db()
        try:
            # 1. Load active configs to build identity set
            existing_rows = db.execute('SELECT config_text, config_type FROM configs WHERE status="active"').fetchall()
            existing_identities = set()
            for row in existing_rows:
                identity = get_config_identity(row['config_text'], row['config_type'])
                existing_identities.add(identity)
                
            # 2. Get capacity settings
            max_active = int(get_setting('max_active_configs', '100'))
            max_new = int(get_setting('max_new_configs_per_scan', '10'))
            
            # Count current active/enabled configs
            current_active_row = db.execute(
                'SELECT COUNT(*) as count FROM configs WHERE status="active" AND is_enabled=1'
            ).fetchone()
            current_active_count = current_active_row['count'] if current_active_row else 0
            
            available_capacity = max(0, max_active - current_active_count)
            limit = min(max_new, available_capacity)
            
            # Filter healthy candidates
            healthy_configs = []
            for r in results:
                if r.get('reachable') and r.get('validation') == 'Success' and r.get('latency_ms') is not None:
                    healthy_configs.append(r)
            
            # Sort by latency to import the lowest ping configs first
            healthy_configs.sort(key=lambda x: x.get('latency_ms', 999999))
            
            added_count = 0
            duplicate_count = 0
            for item in healthy_configs:
                uri = item['uri']
                protocol = detect_config_type(uri)
                if not protocol:
                    continue
                
                identity = get_config_identity(uri, protocol)
                if identity in existing_identities:
                    duplicate_count += 1
                    continue
                    
                if added_count >= limit:
                    break
                    
                max_sort_row = db.execute('SELECT MAX(sort_order) as max_val FROM configs WHERE status="active"').fetchone()
                max_sort = max_sort_row['max_val'] if max_sort_row else 0
                next_order = (max_sort if max_sort is not None else 0) + 1
                
                source_name = item.get('source', 'auto')
                
                cursor = db.execute(
                    '''INSERT INTO configs (
                        config_text, config_type, sort_order, is_enabled, status,
                        source, mode, last_check, last_success, latency, consecutive_failures, health_status
                    ) VALUES (?, ?, ?, 1, 'active', ?, 'auto', ?, ?, ?, 0, 'healthy')''',
                    (uri, protocol, next_order, source_name, scan_time_str, scan_time_str, int(item['latency_ms']))
                )
                config_id = cursor.lastrowid
                
                if scan_id is not None:
                    db.execute(
                        '''INSERT INTO config_health_history (
                            config_id, scan_id, reachable, latency, validation, error_message
                        ) VALUES (?, ?, 1, ?, 'Success', NULL)''',
                        (config_id, scan_id, int(item['latency_ms']))
                    )
                
                existing_identities.add(identity)
                added_count += 1
                
            db.commit()
            return added_count, duplicate_count
        except Exception as e:
            print(f"Error in ConfigImporter: {e}")
            db.rollback()
            return 0, 0
        finally:
            db.close()


class HealthManager:
    """Updates latency and handles cleanup logic (disable or delete) on failures."""
    
    @staticmethod
    def process_health_results(results, scan_time_str, scan_id=None):
        db = get_db()
        try:
            failure_threshold = int(get_setting('failure_threshold', '2'))
            cleanup_policy = get_setting('cleanup_policy', 'disable').lower()
            
            disabled_count = 0
            deleted_count = 0
            
            for item in results:
                uri = item['uri']
                reachable = item.get('reachable', False)
                validation = item.get('validation', '')
                latency = item.get('latency_ms')
                
                config_row = db.execute(
                    'SELECT id, consecutive_failures FROM configs WHERE config_text = ? AND status = "active"',
                    (uri,)
                ).fetchone()
                
                if not config_row:
                    continue
                    
                cfg_id = config_row['id']
                current_failures = config_row['consecutive_failures'] or 0
                
                if reachable and validation == 'Success' and latency is not None:
                    db.execute(
                        '''UPDATE configs SET 
                            last_check = ?, 
                            last_success = ?, 
                            latency = ?, 
                            consecutive_failures = 0, 
                            health_status = 'healthy' 
                        WHERE id = ?''',
                        (scan_time_str, scan_time_str, int(latency), cfg_id)
                    )
                else:
                    new_failures = current_failures + 1
                    is_enabled = 1
                    status = 'active'
                    health_status = 'healthy' if new_failures < failure_threshold else 'unhealthy'
                    
                    if new_failures >= failure_threshold:
                        if cleanup_policy == 'disable':
                            is_enabled = 0
                            disabled_count += 1
                        elif cleanup_policy == 'delete':
                            status = 'deleted'
                            deleted_count += 1
                            
                    db.execute(
                        '''UPDATE configs SET 
                            last_check = ?, 
                            consecutive_failures = ?, 
                            health_status = ?,
                            is_enabled = ?,
                            status = ?
                        WHERE id = ?''',
                        (scan_time_str, new_failures, health_status, is_enabled, status, cfg_id)
                    )
                
                if scan_id is not None:
                    db.execute(
                        '''INSERT INTO config_health_history (
                            config_id, scan_id, reachable, latency, validation, error_message
                        ) VALUES (?, ?, ?, ?, ?, ?)''',
                        (
                            cfg_id, scan_id,
                            1 if reachable else 0,
                            int(latency) if latency is not None else None,
                            validation,
                            item.get('error')
                        )
                    )
            
            # Retention policy: keep only last 30 days
            db.execute("DELETE FROM config_health_history WHERE checked_at < datetime('now', '-30 days')")
            
            db.commit()
            return disabled_count, deleted_count
        except Exception as e:
            print(f"Error in HealthManager: {e}")
            db.rollback()
            return 0, 0
        finally:
            db.close()


class MetricsRecorder:
    """Records logs and metrics in auto_sources and scan_history tables."""
    
    @staticmethod
    def record_scan_history(scan_type, started_at_str, duration_ms, stats_dict, status, error_msg=None, worker_version=None, job_id=None):
        db = get_db()
        try:
            finished_at_str = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
            total_sources = stats_dict.get('total_sources', 0)
            successful_sources = stats_dict.get('successful_sources', 0)
            failed_sources = stats_dict.get('failed_sources', 0)
            discovered_configs = stats_dict.get('discovered', 0)
            working_configs = stats_dict.get('working_configs', 0)
            imported_configs = stats_dict.get('added', 0)
            disabled_configs = stats_dict.get('disabled', 0)
            deleted_configs = stats_dict.get('deleted', 0)
            duplicate_configs = stats_dict.get('duplicate_configs', 0)
            
            cursor = db.execute(
                '''INSERT INTO scan_history (
                    scan_type, started_at, finished_at, duration_ms,
                    discovered_count, added_count, disabled_count, deleted_count,
                    status, error_message, worker_version, engine_version,
                    job_id, total_sources, successful_sources, failed_sources,
                    discovered_configs, working_configs, imported_configs,
                    disabled_configs, deleted_configs, duplicate_configs, scan_duration_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (
                    scan_type, started_at_str, finished_at_str, duration_ms,
                    discovered_configs, imported_configs, disabled_configs, deleted_configs,
                    status, error_msg, worker_version, "V2RayDAR Engine",
                    job_id, total_sources, successful_sources, failed_sources,
                    discovered_configs, working_configs, imported_configs,
                    disabled_configs, deleted_configs, duplicate_configs, duration_ms
                )
            )
            inserted_id = cursor.lastrowid
            db.commit()
            return inserted_id
        except Exception as e:
            print(f"Error in MetricsRecorder.record_scan_history: {e}")
            db.rollback()
            return None
        finally:
            db.close()

    @staticmethod
    def update_scan_history(scan_id, duration_ms, stats_dict, status, error_msg=None, worker_version=None):
        if scan_id is None:
            return
        db = get_db()
        try:
            finished_at_str = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
            total_sources = stats_dict.get('total_sources', 0)
            successful_sources = stats_dict.get('successful_sources', 0)
            failed_sources = stats_dict.get('failed_sources', 0)
            discovered_configs = stats_dict.get('discovered', 0)
            working_configs = stats_dict.get('working_configs', 0)
            imported_configs = stats_dict.get('added', 0)
            disabled_configs = stats_dict.get('disabled', 0)
            deleted_configs = stats_dict.get('deleted', 0)
            duplicate_configs = stats_dict.get('duplicate_configs', 0)
            
            db.execute(
                '''UPDATE scan_history SET 
                    finished_at = ?, duration_ms = ?,
                    discovered_count = ?, added_count = ?, disabled_count = ?, deleted_count = ?,
                    status = ?, error_message = ?, worker_version = ?,
                    total_sources = ?, successful_sources = ?, failed_sources = ?,
                    discovered_configs = ?, working_configs = ?, imported_configs = ?,
                    disabled_configs = ?, deleted_configs = ?, duplicate_configs = ?, scan_duration_ms = ?
                WHERE id = ?''',
                (
                    finished_at_str, duration_ms,
                    discovered_configs, imported_configs, disabled_configs, deleted_configs,
                    status, error_msg, worker_version,
                    total_sources, successful_sources, failed_sources,
                    discovered_configs, working_configs, imported_configs,
                    disabled_configs, deleted_configs, duplicate_configs, duration_ms,
                    scan_id
                )
            )
            db.commit()
        except Exception as e:
            print(f"Error in MetricsRecorder.update_scan_history: {e}")
            db.rollback()
        finally:
            db.close()

    @staticmethod
    def update_source_metadata(source_name, scan_time_str, success, error_msg=None):
        db = get_db()
        try:
            row = db.execute('SELECT id, failure_count FROM auto_sources WHERE name = ?', (source_name,)).fetchone()
            if not row:
                row = db.execute('SELECT id, failure_count FROM auto_sources WHERE url = ?', (source_name,)).fetchone()
                
            if row:
                source_id = row['id']
                current_fail = row['failure_count'] or 0
                
                if success:
                    db.execute(
                        '''UPDATE auto_sources SET 
                            last_scan = ?, last_success = ?, last_error = NULL, failure_count = 0 
                        WHERE id = ?''',
                        (scan_time_str, scan_time_str, source_id)
                    )
                else:
                    db.execute(
                        '''UPDATE auto_sources SET 
                            last_scan = ?, last_error = ?, failure_count = ? 
                        WHERE id = ?''',
                        (scan_time_str, error_msg, current_fail + 1, source_id)
                    )
                db.commit()
        except Exception as e:
            print(f"Error in MetricsRecorder.update_source_metadata: {e}")
            db.rollback()
        finally:
            db.close()


_CANCEL_REQUESTED = False
_CANCEL_LOCK = threading.Lock()

def set_cancel_requested(val):
    """Set the cancel flag both in-memory and as a flag file, so a cancel
    request served by one gunicorn worker reaches the worker running the scan."""
    global _CANCEL_REQUESTED
    with _CANCEL_LOCK:
        _CANCEL_REQUESTED = val
    try:
        if val:
            with open(constants.SCAN_CANCEL_FLAG, 'w') as f:
                f.write('1')
        elif os.path.exists(constants.SCAN_CANCEL_FLAG):
            os.remove(constants.SCAN_CANCEL_FLAG)
    except OSError:
        pass

def is_cancel_requested():
    with _CANCEL_LOCK:
        if _CANCEL_REQUESTED:
            return True
    return os.path.exists(constants.SCAN_CANCEL_FLAG)


class AutomationService:
    """Orchestrates standard input/output scans with subprocess execution lock."""
    
    @staticmethod
    def cancel_scan():
        set_cancel_requested(True)
        terminate_all_subprocesses()

    @staticmethod
    def run_scan(mode):
        if not SCAN_LOCK.acquire(blocking=False):
            print("Scan skipped: another automation run is already active.")
            return False, "Another scan is already in progress."
        if not SCAN_FILE_LOCK.acquire(blocking=False):
            SCAN_LOCK.release()
            print("Scan skipped: another automation run is active in a different worker process.")
            return False, "Another scan is already in progress."

        started_at_str = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        job_id = uuid.uuid4().hex
        set_cancel_requested(False)
        
        print(f"[{job_id}] Automation Scan started. Mode: {mode}")
        
        # Record running state in database and get scan_id
        scan_id = MetricsRecorder.record_scan_history(
            scan_type=mode,
            started_at_str=started_at_str,
            duration_ms=0,
            stats_dict={},
            status='running',
            job_id=job_id
        )
        
        try:
            v2raydar_path = locate_v2raydar()
            
            if mode == 'discovery':
                # Check current active count
                max_active = int(get_setting('max_active_configs', '100'))
                db = get_db()
                active_count = db.execute(
                    'SELECT COUNT(*) as count FROM configs WHERE status="active" AND is_enabled=1'
                ).fetchone()['count']
                db.close()
                
                if active_count >= max_active:
                    msg = f"Discovery skipped: active configs capacity full ({active_count}/{max_active})"
                    print(f"[{job_id}] {msg}")
                    # Update status
                    MetricsRecorder.update_scan_history(scan_id, 0, {}, 'skipped', error_msg=msg)
                    return True, msg
                    
                # Fetch sources
                db = get_db()
                source_rows = db.execute(
                    'SELECT name, url, priority FROM auto_sources WHERE is_enabled=1'
                ).fetchall()
                db.close()
                
                if not source_rows:
                    msg = "Discovery skipped: no enabled sources in database."
                    print(f"[{job_id}] {msg}")
                    MetricsRecorder.update_scan_history(scan_id, 0, {}, 'skipped', error_msg=msg)
                    return True, msg
                    
                sources_list = []
                for s in source_rows:
                    sources_list.append({
                        "name": s['name'],
                        "url": s['url'],
                        "priority": s['priority']
                    })
                    
                input_data = {
                    "schema_version": 1,
                    "mode": "discovery",
                    "job_id": job_id,
                    "sources": sources_list
                }
                input_json = json.dumps(input_data)
                
                fetch_c = get_validated_concurrency('fetch_concurrency', 4)
                probe_c = get_validated_concurrency('probe_concurrency', 10)
                probe_pc = get_validated_concurrency('probe_process_concurrency', 2)
                
                cmd = [
                    v2raydar_path, "worker", "discovery",
                    "--fetch-concurrency", str(fetch_c),
                    "--probe-concurrency", str(probe_c),
                    "--probe-process-concurrency", str(probe_pc)
                ]
                ret_code, stdout, stderr, duration_ms = Runner.run_subprocess(cmd, input_json)
                
                if ret_code != 0:
                    status = 'cancelled' if is_cancel_requested() else 'failed'
                    err_desc = "Scan cancelled by user." if is_cancel_requested() else f"V2RayDAR exit code {ret_code}. Stderr: {stderr}"
                    print(f"[{job_id}] Worker failed or cancelled. Status: {status}. Error: {err_desc}")
                    
                    MetricsRecorder.update_scan_history(
                        scan_id=scan_id,
                        duration_ms=duration_ms,
                        stats_dict={},
                        status=status,
                        error_msg=err_desc
                    )
                    for s in sources_list:
                        MetricsRecorder.update_source_metadata(s['name'], started_at_str, False, stderr)
                    return False, f"Worker process failed: {stderr}"
                
                try:
                    parsed_output = ResultParser.parse(stdout)
                except Exception as e:
                    status = 'cancelled' if is_cancel_requested() else 'failed'
                    err_desc = f"Output parsing error: {e}"
                    print(f"[{job_id}] Parsing failed. Error: {err_desc}")
                    MetricsRecorder.update_scan_history(
                        scan_id=scan_id,
                        duration_ms=duration_ms,
                        stats_dict={},
                        status=status,
                        error_msg=err_desc
                    )
                    return False, f"Parser error: {e}"
                
                worker_version = parsed_output.get("worker_version")
                results = parsed_output.get("results", [])
                
                added_count, duplicate_count = ConfigImporter.import_discovered_configs(results, started_at_str, scan_id=scan_id)
                
                # Deduce per-source operational success
                successful_sources = set()
                failed_sources = {}
                working_configs = 0
                failed_probes = 0
                for r in results:
                    src = r.get('source')
                    if not src:
                        continue
                    if r.get('reachable') and r.get('validation') == 'Success':
                        successful_sources.add(src)
                        working_configs += 1
                    else:
                        failed_probes += 1
                        if src not in failed_sources:
                            failed_sources[src] = r.get('error') or r.get('validation') or "Failed to test"
                            
                for s in sources_list:
                    name = s['name']
                    if name in successful_sources:
                        MetricsRecorder.update_source_metadata(name, started_at_str, True)
                    else:
                        err = failed_sources.get(name, "No config from this source was successfully validated")
                        MetricsRecorder.update_source_metadata(name, started_at_str, False, err)
                        
                stats = {
                    "total_sources": len(sources_list),
                    "successful_sources": len(successful_sources),
                    "failed_sources": len(sources_list) - len(successful_sources),
                    "discovered": len(results),
                    "working_configs": working_configs,
                    "added": added_count,
                    "disabled": 0,
                    "deleted": 0,
                    "duplicate_configs": duplicate_count,
                    "failures_count": failed_probes
                }
                
                status = 'cancelled' if is_cancel_requested() else 'success'
                MetricsRecorder.update_scan_history(
                    scan_id=scan_id,
                    duration_ms=duration_ms,
                    stats_dict=stats,
                    status=status,
                    worker_version=worker_version
                )
                print(f"[{job_id}] Discovery completed successfully. Added: {added_count}")
                return True, f"Discovery completed. Discovered: {len(results)}, Added: {added_count}."
                
            elif mode == 'health_check':
                # Fetch configs
                db = get_db()
                config_rows = db.execute(
                    'SELECT id, config_text, config_type FROM configs WHERE status="active" AND is_enabled=1'
                ).fetchall()
                db.close()
                
                if not config_rows:
                    msg = "Health check skipped: no active configs in database."
                    print(f"[{job_id}] {msg}")
                    MetricsRecorder.update_scan_history(scan_id, 0, {}, 'skipped', error_msg=msg)
                    return True, msg
                    
                configs_list = []
                for c in config_rows:
                    configs_list.append({
                        "uri": c['config_text'],
                        "protocol": c['config_type']
                    })
                    
                input_data = {
                    "schema_version": 1,
                    "mode": "health_check",
                    "job_id": job_id,
                    "configs": configs_list
                }
                input_json = json.dumps(input_data)
                
                probe_c = get_validated_concurrency('probe_concurrency', 10)
                probe_pc = get_validated_concurrency('probe_process_concurrency', 2)
                
                cmd = [
                    v2raydar_path, "worker", "health",
                    "--probe-concurrency", str(probe_c),
                    "--probe-process-concurrency", str(probe_pc)
                ]
                ret_code, stdout, stderr, duration_ms = Runner.run_subprocess(cmd, input_json)
                
                if ret_code != 0:
                    status = 'cancelled' if is_cancel_requested() else 'failed'
                    err_desc = "Scan cancelled by user." if is_cancel_requested() else f"V2RayDAR exit code {ret_code}. Stderr: {stderr}"
                    print(f"[{job_id}] Worker failed or cancelled. Status: {status}. Error: {err_desc}")
                    
                    MetricsRecorder.update_scan_history(
                        scan_id=scan_id,
                        duration_ms=duration_ms,
                        stats_dict={},
                        status=status,
                        error_msg=err_desc
                    )
                    return False, f"Worker process failed: {stderr}"
                
                try:
                    parsed_output = ResultParser.parse(stdout)
                except Exception as e:
                    status = 'cancelled' if is_cancel_requested() else 'failed'
                    err_desc = f"Output parsing error: {e}"
                    print(f"[{job_id}] Parsing failed. Error: {err_desc}")
                    MetricsRecorder.update_scan_history(
                        scan_id=scan_id,
                        duration_ms=duration_ms,
                        stats_dict={},
                        status=status,
                        error_msg=err_desc
                    )
                    return False, f"Parser error: {e}"
                
                worker_version = parsed_output.get("worker_version")
                results = parsed_output.get("results", [])
                
                disabled_cnt, deleted_cnt = HealthManager.process_health_results(results, started_at_str, scan_id=scan_id)
                
                working_configs = len([r for r in results if r.get('reachable') and r.get('validation') == 'Success'])
                failed_probes = len(results) - working_configs
                
                stats = {
                    "total_sources": 0,
                    "successful_sources": 0,
                    "failed_sources": 0,
                    "discovered": len(results), # total tested
                    "working_configs": working_configs,
                    "added": 0,
                    "disabled": disabled_cnt,
                    "deleted": deleted_cnt,
                    "duplicate_configs": 0,
                    "failures_count": failed_probes
                }
                
                status = 'cancelled' if is_cancel_requested() else 'success'
                MetricsRecorder.update_scan_history(
                    scan_id=scan_id,
                    duration_ms=duration_ms,
                    stats_dict=stats,
                    status=status,
                    worker_version=worker_version
                )
                print(f"[{job_id}] Health check scan completed successfully. Tested: {len(results)}")
                return True, f"Health check completed. Tested: {len(results)}, Disabled: {disabled_cnt}, Deleted: {deleted_cnt}."
            else:
                return False, f"Unknown scan mode: {mode}"
                
        except Exception as e:
            status = 'cancelled' if is_cancel_requested() else 'failed'
            err_desc = f"Exception: {str(e)}"
            print(f"[{job_id}] Exception during Automation Scan: {e}")
            MetricsRecorder.update_scan_history(
                scan_id=scan_id,
                duration_ms=0,
                stats_dict={},
                status=status,
                error_msg=err_desc
            )
            return False, f"Exception: {e}"
        finally:
            SCAN_FILE_LOCK.release()
            try:
                SCAN_LOCK.release()
            except RuntimeError:
                pass
