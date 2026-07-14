# -*- coding: utf-8 -*-
"""Statistics, chart data, and log management."""

import os
from datetime import datetime, timedelta

from database import get_db
from utils.user_agent import parse_user_agent
from utils.constants import DAYS_MAP, CLIENTS
import utils.constants as constants
from utils.misc import get_file_size_formatted


def log_subscription_access(ip, ua, status, request_path=''):
    """Insert a subscription access log entry."""
    db = get_db()
    try:
        db.execute(
            'INSERT INTO subscription_logs (ip_address, user_agent, status, request_path) VALUES (?, ?, ?, ?)',
            (ip, ua, status, request_path)
        )
        db.commit()
    except Exception as e:
        print(f"Error logging subscription access: {e}")
    finally:
        db.close()


def get_stats():
    """Return a dict of dashboard statistics."""
    db = get_db()

    total_configs = db.execute('SELECT COUNT(*) as count FROM configs WHERE status != "deleted"').fetchone()['count']
    active_configs = db.execute('SELECT COUNT(*) as count FROM configs WHERE status = "active" AND is_enabled = 1').fetchone()['count']
    disabled_configs = db.execute('SELECT COUNT(*) as count FROM configs WHERE status = "active" AND is_enabled = 0').fetchone()['count']

    vmess = db.execute('SELECT COUNT(*) as count FROM configs WHERE status = "active" AND is_enabled = 1 AND config_type = "vmess"').fetchone()['count']
    vless = db.execute('SELECT COUNT(*) as count FROM configs WHERE status = "active" AND is_enabled = 1 AND config_type = "vless"').fetchone()['count']
    trojan = db.execute('SELECT COUNT(*) as count FROM configs WHERE status = "active" AND is_enabled = 1 AND config_type = "trojan"').fetchone()['count']
    hysteria2 = db.execute('SELECT COUNT(*) as count FROM configs WHERE status = "active" AND is_enabled = 1 AND config_type = "hysteria2"').fetchone()['count']

    today_downloads = db.execute("SELECT COUNT(*) as count FROM subscription_logs WHERE status = 'SUCCESS' AND date(accessed_at, 'localtime') = date('now', 'localtime')").fetchone()['count']
    today_unique = db.execute("SELECT COUNT(DISTINCT ip_address) as count FROM subscription_logs WHERE status = 'SUCCESS' AND date(accessed_at, 'localtime') = date('now', 'localtime')").fetchone()['count']

    db_size = get_file_size_formatted(constants.DATABASE)

    total_logs = db.execute('SELECT COUNT(*) as count FROM subscription_logs').fetchone()['count']

    most_requested_row = db.execute("SELECT request_path, COUNT(*) as count FROM subscription_logs WHERE status = 'SUCCESS' AND request_path IS NOT NULL AND request_path != '' GROUP BY request_path ORDER BY count DESC LIMIT 1").fetchone()
    most_requested_path = most_requested_row['request_path'] if most_requested_row else "ندارد"

    primary_row = db.execute('SELECT path FROM subscription_paths WHERE is_primary = 1').fetchone()
    primary_path = primary_row['path'] if primary_row else "نامشخص"

    additional_enabled = db.execute('SELECT COUNT(*) as count FROM subscription_paths WHERE is_primary = 0 AND is_enabled = 1').fetchone()['count']
    paths_disabled = db.execute('SELECT COUNT(*) as count FROM subscription_paths WHERE is_enabled = 0').fetchone()['count']

    client_rows = db.execute('''
        SELECT 
            CASE 
                WHEN user_agent LIKE '%v2rayng%' THEN 'v2rayNG'
                WHEN user_agent LIKE '%nekobox%' THEN 'Nekobox'
                WHEN user_agent LIKE '%clash%' THEN 'Clash'
                WHEN user_agent LIKE '%shadowrocket%' THEN 'Shadowrocket'
                WHEN user_agent LIKE '%sing-box%' THEN 'Sing-box'
                ELSE 'Other'
            END as client,
            COUNT(*) as count
        FROM subscription_logs
        GROUP BY client
    ''').fetchall()

    client_counts = {c: 0 for c in CLIENTS}
    for r in client_rows:
        if r['client'] in client_counts:
            client_counts[r['client']] = r['count']

    db.close()

    return {
        'total': total_configs,
        'total_configs': total_configs,
        'active_configs': active_configs,
        'disabled_configs': disabled_configs,
        'vmess': vmess,
        'vless': vless,
        'trojan': trojan,
        'hysteria2': hysteria2,
        'today_downloads': today_downloads,
        'today_unique': today_unique,
        'db_size': db_size,
        'total_logs': total_logs,
        'most_requested_path': most_requested_path,
        'primary_path': primary_path,
        'additional_enabled': additional_enabled,
        'paths_disabled': paths_disabled,
        'client_stats': client_counts
    }


def get_usage_stats(range_val='24h'):
    """Return usage statistics for a given time range.

    The frontend expects:
      {
        "today_unique": int,
        "today_total": int,
        "labels": list,       # time-bucket labels (hourly or daily)
        "data": list,         # total counts per bucket
        "unique_data": list   # unique-IP counts per bucket
      }
    Additional fields are included for extended consumers.
    """
    db = get_db()

    range_map = {
        '1h': timedelta(hours=1),
        '6h': timedelta(hours=6),
        '12h': timedelta(hours=12),
        '24h': timedelta(hours=24),
        '7d': timedelta(days=7),
        '30d': timedelta(days=30),
        '90d': timedelta(days=90),
    }

    delta = range_map.get(range_val, timedelta(hours=24))
    since = (datetime.now() - delta).strftime('%Y-%m-%d %H:%M:%S')

    # Aggregate totals
    total = db.execute(
        "SELECT COUNT(*) as count FROM subscription_logs WHERE status = 'SUCCESS' AND datetime(accessed_at, 'localtime') >= ?", (since,)
    ).fetchone()['count']

    unique_ips = db.execute(
        "SELECT COUNT(DISTINCT ip_address) as count FROM subscription_logs WHERE status = 'SUCCESS' AND datetime(accessed_at, 'localtime') >= ?", (since,)
    ).fetchone()['count']

    # Build time-bucketed arrays
    use_hourly = range_val in ('1h', '6h', '12h', '24h')

    if use_hourly:
        # Hourly buckets for the last N hours
        hours = int(delta.total_seconds() // 3600)
        labels = []
        data_arr = []
        unique_arr = []
        for i in range(hours):
            bucket_start = datetime.now() - timedelta(hours=hours - i)
            bucket_end = datetime.now() - timedelta(hours=hours - i - 1)
            label = bucket_start.strftime('%H:%M')
            s = bucket_start.strftime('%Y-%m-%d %H:%M:%S')
            e = bucket_end.strftime('%Y-%m-%d %H:%M:%S')
            cnt = db.execute(
                "SELECT COUNT(*) as count FROM subscription_logs WHERE status = 'SUCCESS' AND datetime(accessed_at, 'localtime') >= ? AND datetime(accessed_at, 'localtime') < ?",
                (s, e)
            ).fetchone()['count']
            ucnt = db.execute(
                "SELECT COUNT(DISTINCT ip_address) as count FROM subscription_logs WHERE status = 'SUCCESS' AND datetime(accessed_at, 'localtime') >= ? AND datetime(accessed_at, 'localtime') < ?",
                (s, e)
            ).fetchone()['count']
            labels.append(label)
            data_arr.append(cnt)
            unique_arr.append(ucnt)
    else:
        # Daily buckets
        days = int(delta.days)
        labels = []
        data_arr = []
        unique_arr = []
        start_date = datetime.today().date() - timedelta(days=days - 1)
        for i in range(days):
            d = (start_date + timedelta(days=i)).strftime('%Y-%m-%d')
            cnt = db.execute(
                "SELECT COUNT(*) as count FROM subscription_logs WHERE status = 'SUCCESS' AND date(accessed_at, 'localtime') = ?",
                (d,)
            ).fetchone()['count']
            ucnt = db.execute(
                "SELECT COUNT(DISTINCT ip_address) as count FROM subscription_logs WHERE status = 'SUCCESS' AND date(accessed_at, 'localtime') = ?",
                (d,)
            ).fetchone()['count']
            labels.append(d)
            data_arr.append(cnt)
            unique_arr.append(ucnt)

    # Client breakdown
    client_rows = db.execute('''
        SELECT 
            CASE 
                WHEN user_agent LIKE '%v2rayng%' THEN 'v2rayNG'
                WHEN user_agent LIKE '%nekobox%' THEN 'Nekobox'
                WHEN user_agent LIKE '%clash%' THEN 'Clash'
                WHEN user_agent LIKE '%shadowrocket%' THEN 'Shadowrocket'
                WHEN user_agent LIKE '%sing-box%' THEN 'Sing-box'
                ELSE 'Other'
            END as client,
            COUNT(*) as count
        FROM subscription_logs
        WHERE status = 'SUCCESS' AND datetime(accessed_at, 'localtime') >= ?
        GROUP BY client
    ''', (since,)).fetchall()
    client_counts = {c: 0 for c in CLIENTS}
    for r in client_rows:
        if r['client'] in client_counts:
            client_counts[r['client']] = r['count']

    # Top paths
    top_paths = db.execute(
        "SELECT request_path, COUNT(*) as count FROM subscription_logs "
        "WHERE status = 'SUCCESS' AND datetime(accessed_at, 'localtime') >= ? AND request_path IS NOT NULL AND request_path != '' "
        "GROUP BY request_path ORDER BY count DESC LIMIT 10", (since,)
    ).fetchall()

    db.close()

    return {
        # Frontend-expected fields
        'today_unique': unique_ips,
        'today_total': total,
        'labels': labels,
        'data': data_arr,
        'unique_data': unique_arr,
        # Extended fields for other consumers
        'range': range_val,
        'total_requests': total,
        'successful_downloads': total,
        'unique_ips': unique_ips,
        'top_paths': [{'path': r['request_path'], 'count': r['count']} for r in top_paths],
        'client_stats': client_counts
    }


def get_chart_data(daily_range='30d', client_range='30d'):
    """Return chart data dicts: hourly, daily trend, client stats, protocol dist.

    The frontend expects:
      - daily.labels, daily.downloads
      - clients.labels = date labels (time-series)
      - clients.<clientName> = array of counts per date (same length as labels)
    """
    db = get_db()

    # 1. Hourly today
    hourly_data = {f"{h:02d}": 0 for h in range(24)}
    hourly_rows = db.execute('''
        SELECT strftime('%H', accessed_at, 'localtime') as hour, COUNT(*) as count 
        FROM subscription_logs 
        WHERE status = 'SUCCESS' AND date(accessed_at, 'localtime') = date('now', 'localtime')
        GROUP BY hour
    ''').fetchall()
    for row in hourly_rows:
        h = row['hour']
        if h in hourly_data:
            hourly_data[h] = row['count']
    hourly_result = {'labels': list(hourly_data.keys()), 'data': list(hourly_data.values())}

    # 2. Daily trend – frontend expects "downloads" key
    daily_days = DAYS_MAP.get(daily_range, 30)
    start_date = datetime.today().date() - timedelta(days=daily_days - 1)
    daily_data = {(start_date + timedelta(days=i)).strftime('%Y-%m-%d'): 0 for i in range(daily_days)}

    daily_rows = db.execute('''
        SELECT date(accessed_at, 'localtime') as log_date, COUNT(*) as count 
        FROM subscription_logs 
        WHERE status = 'SUCCESS' AND date(accessed_at, 'localtime') >= ?
        GROUP BY log_date ORDER BY log_date
    ''', (start_date.strftime('%Y-%m-%d'),)).fetchall()
    for row in daily_rows:
        d = row['log_date']
        if d in daily_data:
            daily_data[d] = row['count']
    daily_result = {
        'labels': list(daily_data.keys()),
        'downloads': list(daily_data.values()),
        'data': list(daily_data.values())
    }

    # 3. Client stats – time-series arrays per client, grouped by date
    client_days = DAYS_MAP.get(client_range, 30)
    client_start = datetime.today().date() - timedelta(days=client_days - 1)
    client_date_labels = [(client_start + timedelta(days=i)).strftime('%Y-%m-%d') for i in range(client_days)]

    # Initialize per-client per-date counters
    client_daily = {c: {d: 0 for d in client_date_labels} for c in CLIENTS}

    client_rows = db.execute('''
        SELECT 
            date(accessed_at, 'localtime') as log_date,
            CASE 
                WHEN user_agent LIKE '%v2rayng%' THEN 'v2rayNG'
                WHEN user_agent LIKE '%nekobox%' THEN 'Nekobox'
                WHEN user_agent LIKE '%clash%' THEN 'Clash'
                WHEN user_agent LIKE '%shadowrocket%' THEN 'Shadowrocket'
                WHEN user_agent LIKE '%sing-box%' THEN 'Sing-box'
                ELSE 'Other'
            END as client,
            COUNT(*) as count
        FROM subscription_logs 
        WHERE status = 'SUCCESS' AND date(accessed_at, 'localtime') >= ?
        GROUP BY log_date, client
    ''', (client_start.strftime('%Y-%m-%d'),)).fetchall()
    
    for row in client_rows:
        d = row['log_date']
        client = row['client']
        if client in client_daily and d in client_daily[client]:
            client_daily[client][d] = row['count']

    client_result = {'labels': client_date_labels}
    for c in CLIENTS:
        client_result[c] = [client_daily[c][d] for d in client_date_labels]
    # Also include aggregate data arrays for backward compatibility
    client_result['data'] = [sum(client_daily[c].get(d, 0) for c in CLIENTS) for d in client_date_labels]

    # 4. Protocol distribution
    protocol_rows = db.execute('''
        SELECT config_type, COUNT(*) as count 
        FROM configs 
        WHERE status = 'active' AND is_enabled = 1 
        GROUP BY config_type
    ''').fetchall()
    protocol_result = {
        'labels': [row['config_type'] for row in protocol_rows],
        'data': [row['count'] for row in protocol_rows]
    }

    db.close()

    return {
        'hourly': hourly_result,
        'daily': daily_result,
        'clients': client_result,
        'protocols': protocol_result
    }


def get_logs(page=1, per_page=50, search='', status_filter=''):
    """Return paginated subscription logs. Returns (logs_list, total_count, total_pages)."""
    db = get_db()
    offset = (page - 1) * per_page

    where_clauses = []
    params = []

    if search:
        where_clauses.append('(ip_address LIKE ? OR user_agent LIKE ? OR request_path LIKE ?)')
        search_term = f'%{search}%'
        params.extend([search_term, search_term, search_term])

    if status_filter:
        where_clauses.append('status = ?')
        params.append(status_filter)

    where_sql = ' AND '.join(where_clauses) if where_clauses else '1=1'

    total = db.execute(f'SELECT COUNT(*) as count FROM subscription_logs WHERE {where_sql}', params).fetchone()['count']
    total_pages = max(1, (total + per_page - 1) // per_page)

    rows = db.execute(
        f'SELECT * FROM subscription_logs WHERE {where_sql} ORDER BY accessed_at DESC LIMIT ? OFFSET ?',
        params + [per_page, offset]
    ).fetchall()
    db.close()

    return [dict(r) for r in rows], total, total_pages


def clear_logs():
    """Delete all subscription logs. Returns (success, message)."""
    db = get_db()
    try:
        db.execute('DELETE FROM subscription_logs')
        db.commit()
        return True, 'تمام لاگ‌ها با موفقیت پاک شدند.'
    except Exception as e:
        print(f"Error clearing logs: {e}")
        return False, 'خطا در پاک کردن لاگ‌ها'
    finally:
        db.close()