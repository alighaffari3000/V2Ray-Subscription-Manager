# -*- coding: utf-8 -*-
"""Monotonic background scheduler for running discovery and health check scans."""

import time
import threading
from database import get_setting
from services.automation_service import AutomationService, is_scan_active
import utils.constants as constants
from utils.process_lock import InterProcessLock


def scheduler_worker(app):
    """Background worker executing the timing loop."""
    # فقط یک پروسه در کل سیستم باید scheduler را اجرا کند (گونیکورن چند worker
    # می‌سازد). قفل فایلی تا زنده بودن پروسه نگه داشته می‌شود؛ اگر worker مالک
    # بمیرد، سیستم‌عامل قفل را آزاد می‌کند و یکی از workerهای دیگر آن را می‌گیرد.
    lock = InterProcessLock(constants.SCHEDULER_LOCK_FILE)
    while not lock.acquire(blocking=False):
        time.sleep(30)

    print("Background automation scheduler thread started.")

    # Track timings using Python's monotonic clock
    last_discovery = time.monotonic()
    last_health = time.monotonic()
    
    # Initial sleep to allow the WSGI/Flask server to start serving requests
    time.sleep(10)
    
    while True:
        try:
            with app.app_context():
                try:
                    scan_interval = float(get_setting('scan_interval', '300'))
                except (ValueError, TypeError):
                    scan_interval = 300.0
                    
                try:
                    health_interval = float(get_setting('health_check_interval', '600'))
                except (ValueError, TypeError):
                    health_interval = 600.0
                
                now = time.monotonic()
                discovery_due = (now - last_discovery) >= scan_interval
                health_due = (now - last_health) >= health_interval

                # Discovery and health share one scan lock and can't run at once.
                # With health_interval a multiple of scan_interval they come due on
                # the same tick, and discovery (started first) used to win the lock
                # every time — starving health forever, so dead configs were never
                # pruned and capacity never freed. Two rules fix that:
                #   1. Never burn a due-timer while a scan is already running; let
                #      the due scan fire as soon as the lock frees. No lost turns,
                #      no per-tick "already active" log spam.
                #   2. When both are due, prefer health — it's rarer and frees the
                #      capacity discovery needs; discovery runs next interval.
                if (discovery_due or health_due) and not is_scan_active():
                    if health_due:
                        last_health = now
                        if discovery_due:
                            # Consume discovery's turn too, so it doesn't spin
                            # retrying against the lock the health scan now holds.
                            last_discovery = now
                        print(f"Triggering Health Check from scheduler. Interval configured: {health_interval}s")
                        threading.Thread(
                            target=AutomationService.run_scan,
                            args=('health_check',),
                            daemon=True
                        ).start()
                        # Piggyback device-slot retention on the health tick.
                        try:
                            from services.user_service import cleanup_stale_devices
                            cleanup_stale_devices()
                        except Exception as e_dev:
                            print(f"Error cleaning up stale devices: {e_dev}")

                        # Piggyback subscription-log retention on the health tick too.
                        try:
                            from services.statistics_service import prune_old_subscription_logs
                            deleted = prune_old_subscription_logs()
                            if deleted:
                                print(f"Pruned {deleted} old subscription log rows.")
                        except Exception as e_log:
                            print(f"Error pruning old subscription logs: {e_log}")
                    elif discovery_due:
                        last_discovery = now
                        print(f"Triggering Auto Discovery from scheduler. Interval configured: {scan_interval}s")
                        threading.Thread(
                            target=AutomationService.run_scan,
                            args=('discovery',),
                            daemon=True
                        ).start()

                # Check if it's time for Scheduled Backup
                try:
                    backup_enabled = get_setting('backup_scheduled_enabled', '0') == '1'
                    if backup_enabled:
                        interval = get_setting('backup_interval', 'daily')
                        last_backup_str = get_setting('last_backup_time', '')
                        
                        interval_seconds = 86400
                        if interval == '6h':
                            interval_seconds = 6 * 3600
                        elif interval == '12h':
                            interval_seconds = 12 * 3600
                        elif interval == 'daily':
                            interval_seconds = 24 * 3600
                        elif interval == 'weekly':
                            interval_seconds = 7 * 24 * 3600
                        elif interval == 'monthly':
                            interval_seconds = 30 * 24 * 3600
                            
                        should_backup = False
                        from datetime import datetime
                        if not last_backup_str:
                            should_backup = True
                        else:
                            try:
                                last_backup_dt = datetime.strptime(last_backup_str, '%Y-%m-%d %H:%M:%S')
                                now_dt = datetime.utcnow()
                                if (now_dt - last_backup_dt).total_seconds() >= interval_seconds:
                                    should_backup = True
                            except Exception:
                                should_backup = True
                                
                        if should_backup:
                            print(f"Triggering Scheduled Backup from scheduler. Interval: {interval}")
                            from services.backup_service import BackupService
                            from database import set_setting
                            set_setting('last_backup_time', datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'))
                            
                            sched_type = get_setting('backup_scheduled_type', 'standard')
                            import os
                            
                            def run_bg_backup():
                                try:
                                    BackupService.create_backup(user='SYSTEM', backup_type=sched_type, trigger_delivery=True)
                                except Exception as e_bk:
                                    print(f"Failed scheduled background backup: {e_bk}")
                                    
                            threading.Thread(target=run_bg_backup, daemon=True).start()
                except Exception as e_bk_chk:
                    print(f"Error checking scheduled backup: {e_bk_chk}")
                    
        except Exception as e:
            print(f"Error in background scheduler loop: {e}")
            
        time.sleep(10)


def start_scheduler(app):
    """Start the background scheduler thread."""
    t = threading.Thread(target=scheduler_worker, args=(app,), daemon=True)
    t.start()
