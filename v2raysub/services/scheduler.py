# -*- coding: utf-8 -*-
"""Monotonic background scheduler for running discovery and health check scans."""

import time
import threading
from database import get_setting
from services.automation_service import AutomationService


def scheduler_worker(app):
    """Background worker executing the timing loop."""
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
                
                # Check if it's time for Auto Discovery
                if now - last_discovery >= scan_interval:
                    last_discovery = now
                    print(f"Triggering Auto Discovery from scheduler. Interval configured: {scan_interval}s")
                    threading.Thread(
                        target=AutomationService.run_scan,
                        args=('discovery',),
                        daemon=True
                    ).start()
                
                # Check if it's time for Health Check
                if now - last_health >= health_interval:
                    last_health = now
                    print(f"Triggering Health Check from scheduler. Interval configured: {health_interval}s")
                    threading.Thread(
                        target=AutomationService.run_scan,
                        args=('health_check',),
                        daemon=True
                    ).start()
                    
        except Exception as e:
            print(f"Error in background scheduler loop: {e}")
            
        time.sleep(10)


def start_scheduler(app):
    """Start the background scheduler thread."""
    t = threading.Thread(target=scheduler_worker, args=(app,), daemon=True)
    t.start()
