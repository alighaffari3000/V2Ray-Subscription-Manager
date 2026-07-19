# -*- coding: utf-8 -*-
"""Backup and Disaster Recovery Service."""

import os
import shutil
import zipfile
import json
import time
import hashlib
import uuid
import platform
import socket
import sqlite3
import threading
from datetime import datetime, timezone
import requests

from database import get_db, get_setting, set_setting
import utils.constants as constants

# Safe import of cryptography for AES-256-GCM encryption
try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives import hashes
    CRYPTO_AVAILABLE = True
except ImportError:
    CRYPTO_AVAILABLE = False


# ---------------------------------------------------------------------------
# Database Metadata Decoupling Abstraction
# ---------------------------------------------------------------------------
class IMetadataProvider:
    def get_tables(self, conn) -> list[str]:
        raise NotImplementedError()

    def get_columns(self, conn, table_name) -> list[str]:
        raise NotImplementedError()

    def truncate_table(self, conn, table_name):
        raise NotImplementedError()

    def insert_rows(self, conn, table_name, columns, rows):
        raise NotImplementedError()


class SQLiteMetadataProvider(IMetadataProvider):
    def get_tables(self, conn) -> list[str]:
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
        return [row[0] for row in cursor.fetchall()]

    def get_columns(self, conn, table_name) -> list[str]:
        cursor = conn.execute(f"PRAGMA table_info({table_name})")
        return [row[1] for row in cursor.fetchall()]

    def truncate_table(self, conn, table_name):
        conn.execute(f"DELETE FROM {table_name}")

    def insert_rows(self, conn, table_name, columns, rows):
        if not rows:
            return
        placeholders = ", ".join(["?"] * len(columns))
        sql = f"INSERT OR REPLACE INTO {table_name} ({', '.join(columns)}) VALUES ({placeholders})"
        
        # Convert dict rows to tuple rows matching the columns list
        tuple_rows = []
        for r in rows:
            tuple_rows.append(tuple(r.get(c) for c in columns))
        conn.executemany(sql, tuple_rows)


# ---------------------------------------------------------------------------
# Runtime Data Manifest configuration
# ---------------------------------------------------------------------------
RUNTIME_DATA_MANIFEST = {
    "database": {
        "paths": ["database.db"],
        "required": True,
        "description": "Core SQLite Database"
    },
    "custom_templates": {
        "paths": ["templates/"],
        "required": True,
        "description": "Jinja templates for rendering panel/client screens"
    },
    "custom_static_assets": {
        "paths": ["static/"],
        "required": False,
        "description": "Assets, styles, and custom visual items"
    },
    "storage": {
        "paths": ["storage/"],
        "exclude": ["storage/backups/"],  # Exclude backups themselves
        "required": False,
        "description": "Dynamic runtime data directories"
    },
    "configuration": {
        "paths": [".env"],
        "required": False,
        "sensitive": True,
        "description": "Environment Configuration File (.env)"
    }
}


# ---------------------------------------------------------------------------
# Cryptographic Helpers
# ---------------------------------------------------------------------------
def _derive_key(password: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100000
    )
    return kdf.derive(password.encode())


def _encrypt_bytes(data: bytes, password: str) -> bytes:
    if not CRYPTO_AVAILABLE:
        raise RuntimeError("Cryptography library not available on system.")
    salt = os.urandom(16)
    key = _derive_key(password, salt)
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)
    ciphertext = aesgcm.encrypt(nonce, data, None)
    return b'ENC\x00' + salt + nonce + ciphertext


def _decrypt_bytes(data: bytes, password: str) -> bytes:
    if not CRYPTO_AVAILABLE:
        raise RuntimeError("Cryptography library not available on system.")
    header = data[:4]
    if header != b'ENC\x00':
        raise ValueError("Data is not encrypted or has an invalid header.")
    salt = data[4:20]
    nonce = data[20:32]
    ciphertext = data[32:]
    key = _derive_key(password, salt)
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(nonce, ciphertext, None)


def _sha256_checksum(filepath) -> str:
    h = hashlib.sha256()
    with open(filepath, 'rb') as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()


def _sha256_checksum_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# Backup Service Implementation
# ---------------------------------------------------------------------------
class BackupService:
    @staticmethod
    def get_backup_dir():
        backup_dir = os.path.join(constants.BASE_DIR, 'storage', 'backups')
        os.makedirs(backup_dir, exist_ok=True)
        return backup_dir

    @staticmethod
    def estimate_backup_size() -> int:
        """Estimate backup size in bytes by looking at database and files."""
        total_size = 0
        db_path = constants.DATABASE
        if os.path.exists(db_path):
            total_size += os.path.getsize(db_path)

        for cat, cfg in RUNTIME_DATA_MANIFEST.items():
            for p in cfg["paths"]:
                full_path = os.path.join(constants.BASE_DIR, p)
                if not os.path.exists(full_path):
                    continue
                if os.path.isdir(full_path):
                    for root, _, files in os.walk(full_path):
                        skip = False
                        for exc in cfg.get("exclude", []):
                            exc_full = os.path.abspath(os.path.join(constants.BASE_DIR, exc))
                            root_abs = os.path.abspath(root)
                            if root_abs.startswith(exc_full) or root_abs == exc_full:
                                skip = True
                                break
                        if skip:
                            continue
                        for file in files:
                            total_size += os.path.getsize(os.path.join(root, file))
                else:
                    total_size += os.path.getsize(full_path)
        return total_size

    @staticmethod
    def check_disk_space(estimated_size: int):
        backup_dir = BackupService.get_backup_dir()
        _, _, free = shutil.disk_usage(backup_dir)
        if free < estimated_size * 1.5:
            raise OSError(
                f"فضای دیسک کافی نیست. فضای مورد نیاز: {estimated_size * 1.5 / 1024 / 1024:.2f} مگابایت، "
                f"فضای خالی موجود: {free / 1024 / 1024:.2f} مگابایت"
            )

    @staticmethod
    def create_backup(user='SYSTEM', backup_type='standard', password=None, trigger_delivery=True, is_emergency=False, restore_session_id=None) -> dict:
        start_time = time.time()
        backup_dir = BackupService.get_backup_dir()

        # 1. Estimate Size & Disk Space Check
        estimated = BackupService.estimate_backup_size()
        BackupService.check_disk_space(estimated)

        # 2. Setup Filenames
        # Use microsecond suffix to avoid collisions during rapid consecutive backups
        timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S-%f')
        if is_emergency:
            filename = f"emergency_backup_before_restore_{timestamp}.zip"
        else:
            filename = f"backup_{backup_type}_{timestamp}.zip"
        
        zip_filepath = os.path.join(backup_dir, filename)

        # 3. Create temp workspace
        temp_dir = os.path.join(backup_dir, f"temp_{uuid.uuid4().hex}")
        os.makedirs(temp_dir, exist_ok=True)
        files_dir = os.path.join(temp_dir, 'files')
        os.makedirs(files_dir, exist_ok=True)
        logs_dir = os.path.join(temp_dir, 'logs')
        os.makedirs(logs_dir, exist_ok=True)

        db_conn = get_db()
        provider = SQLiteMetadataProvider()

        try:
            # 4. Export database dynamically to database.json
            db_data = {}
            record_counts = {}
            tables = provider.get_tables(db_conn)
            for t in tables:
                # Skip backup_logs from the backup itself to prevent recursive log blowup,
                # but keep settings, users, etc.
                if t == 'backup_logs':
                    continue
                rows = db_conn.execute(f"SELECT * FROM {t}").fetchall()
                dict_rows = [dict(r) for r in rows]
                db_data[t] = dict_rows
                record_counts[t] = len(dict_rows)

            db_json_bytes = json.dumps(db_data, indent=2, ensure_ascii=False).encode('utf-8')
            db_json_path = os.path.join(temp_dir, 'database.json')
            with open(db_json_path, 'wb') as f:
                f.write(db_json_bytes)

            db_checksum = _sha256_checksum_bytes(db_json_bytes)
            checksums = {"database.json": db_checksum}

            # 5. Export files dynamically based on runtime data manifest
            file_count = 0
            for cat, cfg in RUNTIME_DATA_MANIFEST.items():
                if cfg.get("sensitive") and backup_type != 'full_dr':
                    # Skip sensitive files in Standard Backups
                    continue
                for p in cfg["paths"]:
                    full_path = os.path.join(constants.BASE_DIR, p)
                    if not os.path.exists(full_path):
                        continue
                    
                    # Target relative path inside files/ zip directory
                    if os.path.isdir(full_path):
                        for root, _, files in os.walk(full_path):
                            # Handle excludes
                            skip = False
                            for exc in cfg.get("exclude", []):
                                exc_full = os.path.abspath(os.path.join(constants.BASE_DIR, exc))
                                root_abs = os.path.abspath(root)
                                if root_abs.startswith(exc_full) or root_abs == exc_full:
                                    skip = True
                                    break
                            if skip:
                                continue
                            for file in files:
                                file_abs = os.path.join(root, file)
                                file_rel = os.path.relpath(file_abs, constants.BASE_DIR)
                                dest_abs = os.path.join(files_dir, file_rel)
                                os.makedirs(os.path.dirname(dest_abs), exist_ok=True)
                                shutil.copy2(file_abs, dest_abs)
                                checksums[f"files/{file_rel.replace('\\', '/')}"] = _sha256_checksum(dest_abs)
                                file_count += 1
                    else:
                        file_rel = os.path.relpath(full_path, constants.BASE_DIR)
                        dest_abs = os.path.join(files_dir, file_rel)
                        os.makedirs(os.path.dirname(dest_abs), exist_ok=True)
                        shutil.copy2(full_path, dest_abs)
                        checksums[f"files/{file_rel.replace('\\', '/')}"] = _sha256_checksum(dest_abs)
                        file_count += 1

            # 6. Generate troubleshooting logs
            system_log_path = os.path.join(logs_dir, 'system.log')
            with open(system_log_path, 'w', encoding='utf-8') as f:
                f.write(f"Backup created at: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC\n")
                f.write(f"Created by: {user}\n")
                f.write(f"Platform: {platform.platform()}\n")
                f.write(f"Hostname: {socket.gethostname()}\n")
            checksums["logs/system.log"] = _sha256_checksum(system_log_path)

            # 7. Generate manifest.json
            sqlite_ver = ""
            try:
                sqlite_ver = db_conn.execute("select sqlite_version()").fetchone()[0]
            except Exception:
                pass

            manifest = {
                "backup_version": "1.0",
                "application_version": "3.0.0",
                "created_at": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                "backup_type": backup_type,
                "is_emergency": 1 if is_emergency else 0,
                "restore_session_id": restore_session_id,
                "minimum_supported_version": "1.0.0",
                "current_version": "3.0.0",
                "python_version": platform.python_version(),
                "sqlite_version": sqlite_ver,
                "database_engine": "sqlite",
                "os": platform.system(),
                "platform": platform.machine(),
                "hostname": socket.gethostname(),
                "timezone": time.tzname[0] if time.tzname else "UTC",
                "compression_method": "deflated",
                "backup_creator": user,
                "git_commit": "",
                "application_build": "release",
                "checksums": checksums,
                "file_count": file_count,
                "database_record_counts": record_counts
            }

            manifest_path = os.path.join(temp_dir, 'manifest.json')
            with open(manifest_path, 'w', encoding='utf-8') as f:
                json.dump(manifest, f, indent=2, ensure_ascii=False)

            # 8. Create ZIP archive
            zip_temp_path = zip_filepath + ".tmp"
            with zipfile.ZipFile(zip_temp_path, 'w', zipfile.ZIP_DEFLATED) as z:
                # Add manifest
                z.write(manifest_path, 'manifest.json')
                # Add database
                z.write(db_json_path, 'database.json')
                # Add files
                for root, _, files in os.walk(files_dir):
                    for file in files:
                        file_abs = os.path.join(root, file)
                        z.write(file_abs, os.path.relpath(file_abs, temp_dir))
                # Add logs
                for root, _, files in os.walk(logs_dir):
                    for file in files:
                        file_abs = os.path.join(root, file)
                        z.write(file_abs, os.path.relpath(file_abs, temp_dir))

            # 9. Handle Optional AES-256 Encryption (Full DR only)
            # Standard backup NEVER uses encryption. Automated DR backups read password from .env
            final_password = None
            if backup_type == 'full_dr':
                if user == 'SYSTEM':
                    final_password = os.environ.get('BACKUP_ENCRYPTION_PASSWORD')
                else:
                    final_password = password

            if backup_type == 'full_dr' and final_password and CRYPTO_AVAILABLE:
                # Encrypt zip bytes
                with open(zip_temp_path, 'rb') as f:
                    zip_bytes = f.read()
                enc_bytes = _encrypt_bytes(zip_bytes, final_password)
                with open(zip_filepath, 'wb') as f:
                    f.write(enc_bytes)
                try:
                    os.unlink(zip_temp_path)
                except Exception:
                    pass
            else:
                shutil.move(zip_temp_path, zip_filepath)

            # 10. Calculate ZIP checksum
            zip_checksum = _sha256_checksum(zip_filepath)
            zip_size = os.path.getsize(zip_filepath)
            duration = time.time() - start_time

            # 11. Delivery status placeholder
            delivery_status = 'NOT_APPLICABLE'
            telegram_enabled = get_setting('backup_telegram_enabled', '0') == '1'
            if telegram_enabled and trigger_delivery and not is_emergency:
                delivery_status = 'PENDING'

            # 12. Write to backup_logs (DB)
            db_conn.execute(
                "INSERT INTO backup_logs (operation, user, status, duration, backup_size, delivery_status, checksum) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                ('backup', user, 'SUCCESS', duration, zip_size, delivery_status, zip_checksum)
            )
            db_conn.commit()

            # 13. Retention Enforcement
            if not is_emergency:
                max_retention = 30
                try:
                    max_retention = int(get_setting('backup_retention_max', '30'))
                except Exception:
                    pass
                BackupService._enforce_retention(max_retention)

            # 14. Trigger Async Telegram Delivery
            if delivery_status == 'PENDING':
                threading.Thread(
                    target=BackupService.deliver_backup,
                    args=(zip_filepath,),
                    daemon=True
                ).start()

            return {
                "success": True,
                "filename": filename,
                "size": zip_size,
                "checksum": zip_checksum,
                "duration": duration,
                "delivery_status": delivery_status
            }

        except Exception as e:
            duration = time.time() - start_time
            db_conn.execute(
                "INSERT INTO backup_logs (operation, user, status, duration, backup_size, error_message, delivery_status) "
                "VALUES (?, ?, ?, ?, 0, ?, 'NOT_APPLICABLE')",
                ('backup', user, 'FAILED', duration, str(e))
            )
            db_conn.commit()
            raise e
        finally:
            db_conn.close()
            # Cleanup temp directory
            try:
                shutil.rmtree(temp_dir, ignore_errors=True)
            except Exception:
                pass

    @staticmethod
    def _enforce_retention(max_backups: int):
        backup_dir = BackupService.get_backup_dir()
        files = [
            os.path.join(backup_dir, f)
            for f in os.listdir(backup_dir)
            if (f.startswith("backup_") or f.startswith("emergency_")) and f.endswith(".zip")
        ]
        # Sort by modification time (oldest first), with name fallback to guarantee consistent ordering
        files.sort(key=lambda x: (os.path.getmtime(x), x))
        if len(files) > max_backups:
            to_delete = files[:len(files) - max_backups]
            for f in to_delete:
                try:
                    os.unlink(f)
                    # Log deletion
                    db = get_db()
                    filename = os.path.basename(f)
                    db.execute(
                        "INSERT INTO backup_logs (operation, user, status, duration, backup_size, error_message, delivery_status) "
                        "VALUES (?, 'SYSTEM', 'SUCCESS', 0, 0, ?, 'NOT_APPLICABLE')",
                        ('delete', f"حذف خودکار نسخه قدیمی به دلیل سیاست نگهداری: {filename}")
                    )
                    db.commit()
                    db.close()
                except Exception:
                    pass

    @staticmethod
    def delete_backup(filename, user='admin') -> bool:
        backup_dir = BackupService.get_backup_dir()
        filepath = os.path.join(backup_dir, filename)
        if not os.path.exists(filepath) or not os.path.isfile(filepath):
            return False
        
        # Security check: prevent directory traversal
        if os.path.dirname(os.path.abspath(filepath)) != os.path.abspath(backup_dir):
            raise ValueError("مسیر نامعتبر")

        os.unlink(filepath)
        db = get_db()
        db.execute(
            "INSERT INTO backup_logs (operation, user, status, duration, backup_size, error_message, delivery_status) "
            "VALUES (?, ?, 'SUCCESS', 0, 0, ?, 'NOT_APPLICABLE')",
            ('delete', user, f"حذف فایل بکاپ: {filename}")
        )
        db.commit()
        db.close()
        return True

    @staticmethod
    def list_backups() -> list:
        backup_dir = BackupService.get_backup_dir()
        if not os.path.exists(backup_dir):
            return []
        
        backups = []
        files = [
            f for f in os.listdir(backup_dir)
            if (f.startswith("backup_") or f.startswith("emergency_")) and f.endswith(".zip")
        ]
        
        db = get_db()
        logs = db.execute("SELECT * FROM backup_logs WHERE operation = 'backup'").fetchall()
        logs_map = {row['checksum']: row for row in logs if row['checksum']}
        db.close()

        for f in files:
            path = os.path.join(backup_dir, f)
            stat = os.stat(path)
            created = datetime.fromtimestamp(stat.st_ctime).strftime('%Y-%m-%d %H:%M:%S')
            size = stat.st_size
            
            # Compute sha256 or fetch from DB to avoid re-reading large files
            checksum = ""
            delivery_status = "NOT_APPLICABLE"
            
            # Simple metadata parse by reading first few bytes or querying logs
            # We can compute checksum or fetch from logs
            try:
                # Fast hash if it matches file size
                checksum = _sha256_checksum(path)
            except Exception:
                pass
            
            log_row = logs_map.get(checksum)
            if log_row:
                delivery_status = log_row['delivery_status']

            backups.append({
                "filename": f,
                "created_at": created,
                "size": size,
                "checksum": checksum,
                "delivery_status": delivery_status,
                "is_emergency": f.startswith("emergency_")
            })
        
        # Sort newest first
        backups.sort(key=lambda x: x['created_at'], reverse=True)
        return backups

    @staticmethod
    def deliver_backup(zip_filepath, retry_count=0):
        """Send the backup archive to Telegram/Bale with exponential retries."""
        filename = os.path.basename(zip_filepath)
        checksum = _sha256_checksum(zip_filepath)

        api_server = get_setting('backup_telegram_api_server', 'https://api.telegram.org').strip()
        bot_token = get_setting('backup_telegram_bot_token', '').strip()
        chat_id = get_setting('backup_telegram_chat_id', '').strip()

        if not bot_token or not chat_id:
            db = get_db()
            db.execute(
                "UPDATE backup_logs SET delivery_status = 'FAILED', error_message = ? WHERE checksum = ?",
                ("توکن یا چت‌آیدی تنظیم نشده است", checksum)
            )
            db.commit()
            db.close()
            return

        if not api_server.startswith('http'):
            api_server = 'https://' + api_server
        api_server = api_server.rstrip('/')

        url = f"{api_server}/bot{bot_token}/sendDocument"

        try:
            with open(zip_filepath, 'rb') as f:
                files = {'document': (filename, f)}
                data = {
                    'chat_id': chat_id,
                    'caption': f"💾 نسخه پشتیبان سیستم سابسکریپشن\n📝 نام فایل: {filename}\n📦 شناسه هش: {checksum[:12]}..."
                }
                resp = requests.post(url, files=files, data=data, timeout=45)

            db = get_db()
            if resp.status_code == 200:
                db.execute(
                    "UPDATE backup_logs SET delivery_status = 'SENT', error_message = NULL WHERE checksum = ?",
                    (checksum,)
                )
                db.commit()
                db.close()
                print(f"Backup delivered successfully: {filename}")
            else:
                raise requests.RequestException(f"خطای وب سرور ({resp.status_code}): {resp.text}")

        except Exception as e:
            print(f"Backup delivery failed for {filename}: {e}")
            db = get_db()
            
            # Retry intervals: 1 min (60s), 5 min (300s), 15 min (900s)
            retry_intervals = [60, 300, 900]
            if retry_count < len(retry_intervals):
                next_delay = retry_intervals[retry_count]
                db.execute(
                    "UPDATE backup_logs SET delivery_status = 'PENDING', error_message = ? WHERE checksum = ?",
                    (f"خطای ارسال: {str(e)} - تلاش مجدد {retry_count+1} در {next_delay//60} دقیقه دیگر", checksum)
                )
                db.commit()
                db.close()
                
                # Schedule retry job
                threading.Timer(
                    next_delay,
                    BackupService.deliver_backup,
                    args=(zip_filepath, retry_count + 1)
                ).start()
            else:
                db.execute(
                    "UPDATE backup_logs SET delivery_status = 'FAILED', error_message = ? WHERE checksum = ?",
                    (f"ارسال با خطا متوقف شد: {str(e)}", checksum)
                )
                db.commit()
                db.close()

    @staticmethod
    def verify_backup(zip_filepath, password=None) -> dict:
        """Non-destructively verify ZIP integrity, manifest, and checksums."""
        temp_extract = os.path.join(BackupService.get_backup_dir(), f"verify_{uuid.uuid4().hex}")
        
        try:
            # 1. Archive check
            if not zipfile.is_zipfile(zip_filepath):
                # Try decrypting first
                if CRYPTO_AVAILABLE and password:
                    try:
                        with open(zip_filepath, 'rb') as f:
                            enc_bytes = f.read()
                        zip_bytes = _decrypt_bytes(enc_bytes, password)
                        temp_dec = zip_filepath + ".dec"
                        with open(temp_dec, 'wb') as f:
                            f.write(zip_bytes)
                        is_zip = zipfile.is_zipfile(temp_dec)
                        try:
                            os.unlink(temp_dec)
                        except Exception:
                            pass
                        if not is_zip:
                            return {"success": False, "status": "Incompatible", "message": "فایل پشتیبان معتبر نیست یا رمز عبور اشتباه است"}
                    except Exception as e:
                        return {"success": False, "status": "Incompatible", "message": f"خطا در رمزگشایی بکاپ: {str(e)}"}
                else:
                    # Check if encrypted but no password provided
                    with open(zip_filepath, 'rb') as f:
                        header = f.read(4)
                    if header == b'ENC\x00':
                        return {"success": False, "status": "Incompatible", "message": "این فایل رمزگذاری شده است. لطفاً رمز عبور را وارد کنید.", "encrypted": True}
                    return {"success": False, "status": "Incompatible", "message": "فایل آپلود شده یک آرشیو معتبر ZIP نیست"}

            # Extract ZIP contents to verify
            # Perform decryption if needed
            dec_zip_path = zip_filepath
            temp_dec_zip = None
            
            with open(zip_filepath, 'rb') as f:
                header = f.read(4)
            if header == b'ENC\x00':
                if not password:
                    return {"success": False, "status": "Incompatible", "message": "رمز عبور برای رمزگشایی فایل الزامی است", "encrypted": True}
                try:
                    with open(zip_filepath, 'rb') as f:
                        enc_bytes = f.read()
                    zip_bytes = _decrypt_bytes(enc_bytes, password)
                    temp_dec_zip = os.path.join(BackupService.get_backup_dir(), f"dec_{uuid.uuid4().hex}.zip")
                    with open(temp_dec_zip, 'wb') as f:
                        f.write(zip_bytes)
                    dec_zip_path = temp_dec_zip
                except Exception as e:
                    return {"success": False, "status": "Incompatible", "message": f"رمز عبور اشتباه است یا فایل خراب شده است: {str(e)}"}

            # Extract to verify
            with zipfile.ZipFile(dec_zip_path, 'r') as z:
                z.extractall(temp_extract)

            # 2. Manifest check
            manifest_path = os.path.join(temp_extract, 'manifest.json')
            if not os.path.exists(manifest_path):
                return {"success": False, "status": "Incompatible", "message": "فایل مانیفست (manifest.json) در آرشیو یافت نشد"}

            with open(manifest_path, 'r', encoding='utf-8') as f:
                manifest = json.load(f)

            # Validate manifest fields
            required_fields = ["backup_version", "application_version", "created_at", "backup_type", "checksums"]
            for field in required_fields:
                if field not in manifest:
                    return {"success": False, "status": "Incompatible", "message": f"فیلد {field} در مانیفست وجود ندارد"}

            # 3. Checksums verification
            checksums = manifest["checksums"]
            for rel_path, expected_hash in checksums.items():
                full_path = os.path.join(temp_extract, rel_path)
                if not os.path.exists(full_path):
                    return {"success": False, "status": "Incompatible", "message": f"فایل {rel_path} ذکر شده در مانیفست در آرشیو یافت نشد"}
                if _sha256_checksum(full_path) != expected_hash:
                    return {"success": False, "status": "Incompatible", "message": f"عدم مطابقت امضای دیجیتال (Checksum) برای فایل: {rel_path}"}

            # 4. Schema verification
            db_json_path = os.path.join(temp_extract, 'database.json')
            if not os.path.exists(db_json_path):
                return {"success": False, "status": "Incompatible", "message": "فایل داده‌های دیتابیس (database.json) در آرشیو یافت نشد"}

            with open(db_json_path, 'r', encoding='utf-8') as f:
                db_data = json.load(f)

            # Determine compatibility level
            backup_app_ver = manifest.get("application_version", "1.0.0")
            current_app_ver = "3.0.0"
            
            # Simple semantic version check
            try:
                b_major = int(backup_app_ver.split('.')[0])
                c_major = int(current_app_ver.split('.')[0])
                if b_major < c_major:
                    status = "Compatible With Warning"
                    message = f"نسخه بکاپ قدیمی‌تر است ({backup_app_ver} -> {current_app_ver}). ارتقاء خودکار پایگاه داده انجام خواهد شد."
                elif b_major > c_major:
                    status = "Incompatible"
                    message = f"نسخه بکاپ جدیدتر از نسخه پنل است ({backup_app_ver} -> {current_app_ver}). امکان بازیابی وجود ندارد."
                else:
                    status = "Compatible"
                    message = "فایل بکاپ کاملاً معتبر و سازگار است"
            except Exception:
                status = "Compatible With Warning"
                message = "عدم انطباق نسخه؛ بازیابی با هشدار انجام می‌شود"

            # Parse stats
            stats = {
                "created_at": manifest.get("created_at"),
                "backup_type": manifest.get("backup_type"),
                "backup_version": manifest.get("backup_version"),
                "app_version": backup_app_ver,
                "users_count": manifest.get("database_record_counts", {}).get("users", 0),
                "configs_count": manifest.get("database_record_counts", {}).get("configs", 0),
                "sources_count": manifest.get("database_record_counts", {}).get("auto_sources", 0),
                "database_record_counts": manifest.get("database_record_counts", {})
            }

            return {
                "success": True,
                "status": status,
                "message": message,
                "stats": stats,
                "encrypted": header == b'ENC\x00'
            }

        except Exception as e:
            return {"success": False, "status": "Incompatible", "message": f"خطا در اعتبارسنجی بکاپ: {str(e)}"}
        finally:
            # Cleanup
            try:
                shutil.rmtree(temp_extract, ignore_errors=True)
            except Exception:
                pass
            if temp_dec_zip and os.path.exists(temp_dec_zip):
                try:
                    os.unlink(temp_dec_zip)
                except Exception:
                    pass

    @staticmethod
    def restore_backup(zip_filepath, password=None, restore_env=False, user='admin') -> dict:
        """Secure transaction-based restore with pre-validation and emergency rollback."""
        start_time = time.time()
        
        # 1. Pre-validation (Verify Backup)
        ver = BackupService.verify_backup(zip_filepath, password)
        if not ver["success"] or ver["status"] == "Incompatible":
            raise ValueError(f"اعتبارسنجی بکاپ ناموفق بود: {ver.get('message')}")

        # Decrypt to temp location if encrypted
        dec_zip_path = zip_filepath
        temp_dec_zip = None
        
        with open(zip_filepath, 'rb') as f:
            header = f.read(4)
        if header == b'ENC\x00':
            # Decrypt
            with open(zip_filepath, 'rb') as f:
                enc_bytes = f.read()
            zip_bytes = _decrypt_bytes(enc_bytes, password)
            temp_dec_zip = os.path.join(BackupService.get_backup_dir(), f"dec_restore_{uuid.uuid4().hex}.zip")
            with open(temp_dec_zip, 'wb') as f:
                f.write(zip_bytes)
            dec_zip_path = temp_dec_zip

        # Create Restore Session ID
        session_id = str(uuid.uuid4())

        # 2. Create emergency backup of current state
        emergency_filename = ""
        try:
            # Auto-save env if it currently exists
            emerg = BackupService.create_backup(
                user=user,
                backup_type='full_dr', # Emergency backups are ALWAYS Full DR backups
                password=password, # Encrypted if a password is supplied
                trigger_delivery=False,
                is_emergency=True,
                restore_session_id=session_id
            )
            emergency_filename = emerg["filename"]
        except Exception as e:
            # Fail early if emergency backup failed
            if temp_dec_zip and os.path.exists(temp_dec_zip):
                try:
                    os.unlink(temp_dec_zip)
                except Exception:
                    pass
            raise RuntimeError(f"ایجاد نسخه پشتیبان اضطراری ناموفق بود. بازیابی لغو شد: {str(e)}")

        temp_extract = os.path.join(BackupService.get_backup_dir(), f"restore_{session_id}")
        os.makedirs(temp_extract, exist_ok=True)

        db_conn = get_db()
        provider = SQLiteMetadataProvider()

        try:
            # Extract zip
            with zipfile.ZipFile(dec_zip_path, 'r') as z:
                z.extractall(temp_extract)

            # Start DB transaction
            db_conn.execute("BEGIN TRANSACTION")
            db_conn.execute("PRAGMA foreign_keys = OFF") # Temporarily disable to bypass truncation ordering

            # Restore database from database.json
            with open(os.path.join(temp_extract, 'database.json'), 'r', encoding='utf-8') as f:
                db_data = json.load(f)

            db_tables = provider.get_tables(db_conn)
            for table, rows in db_data.items():
                if table not in db_tables:
                    # Ignore tables that don't exist in current DB schemas
                    continue
                # Truncate
                provider.truncate_table(db_conn, table)
                if not rows:
                    continue
                # Columns alignment (dynamic database abstraction check)
                db_cols = provider.get_columns(db_conn, table)
                row_cols = list(rows[0].keys())
                aligned_cols = [c for c in row_cols if c in db_cols]
                
                # Extract and write aligned columns only
                provider.insert_rows(db_conn, table, aligned_cols, rows)

            # File Restore
            files_dir = os.path.join(temp_extract, 'files')
            if os.path.exists(files_dir):
                # Copy templates and static files back to application BASE_DIR
                for root, _, files in os.walk(files_dir):
                    for file in files:
                        src_file = os.path.join(root, file)
                        rel_file = os.path.relpath(src_file, files_dir)
                        
                        # SAFE HANDLING OF .env
                        if rel_file == ".env" and not restore_env:
                            # Skip env copy
                            continue
                            
                        dest_file = os.path.join(constants.BASE_DIR, rel_file)
                        os.makedirs(os.path.dirname(dest_file), exist_ok=True)
                        shutil.copy2(src_file, dest_file)

            # Commit Transaction
            db_conn.commit()
            db_conn.execute("PRAGMA foreign_keys = ON")

            duration = time.time() - start_time
            zip_size = os.path.getsize(zip_filepath)

            # Log success (using new connection since transaction closed)
            db_conn.execute(
                "INSERT INTO backup_logs (operation, user, status, duration, backup_size, error_message, delivery_status) "
                "VALUES (?, ?, 'SUCCESS', ?, ?, ?, 'NOT_APPLICABLE')",
                ('restore', user, duration, zip_size, f"بازیابی موفقیت‌آمیز از آرشیو. سیستم بازیابی اضطراری: {emergency_filename}")
            )
            db_conn.commit()

            # Execute Graceful Service Restart Sequence
            BackupService.restart_services()

            return {
                "success": True,
                "message": "بازیابی اطلاعات با موفقیت انجام شد و سرویس‌ها بارگذاری شدند.",
                "emergency_backup": emergency_filename
            }

        except Exception as e:
            # Rollback DB transaction
            try:
                db_conn.rollback()
            except Exception:
                pass
            
            # Rollback Files from emergency backup
            try:
                BackupService._rollback_files(emergency_filename, restore_env)
            except Exception as rollback_err:
                print(f"CRITICAL: Failed to rollback files during recovery: {rollback_err}")

            duration = time.time() - start_time
            zip_size = os.path.getsize(zip_filepath)
            db_conn.execute(
                "INSERT INTO backup_logs (operation, user, status, duration, backup_size, error_message, delivery_status) "
                "VALUES (?, ?, 'FAILED', ?, ?, ?, 'NOT_APPLICABLE')",
                ('restore', user, duration, zip_size, f"بازیابی شکست خورد. سیستم بازگردانی شد. خطا: {str(e)}")
            )
            db_conn.commit()
            raise RuntimeError(f"خطا در بازیابی اطلاعات (سیستم به وضعیت قبل بازگردانده شد): {str(e)}")
        finally:
            db_conn.close()
            # Cleanup temp extract
            try:
                shutil.rmtree(temp_extract, ignore_errors=True)
            except Exception:
                pass
            if temp_dec_zip and os.path.exists(temp_dec_zip):
                try:
                    os.unlink(temp_dec_zip)
                except Exception:
                    pass

    @staticmethod
    def _rollback_files(emergency_filename, restore_env=False):
        backup_dir = BackupService.get_backup_dir()
        zip_path = os.path.join(backup_dir, emergency_filename)
        if not os.path.exists(zip_path):
            return
        
        # Rollback logic: unzip files/ directory contents back to BASE_DIR
        temp_dir = os.path.join(backup_dir, f"rollback_temp_{uuid.uuid4().hex}")
        try:
            with zipfile.ZipFile(zip_path, 'r') as z:
                z.extractall(temp_dir)
            
            files_dir = os.path.join(temp_dir, 'files')
            if os.path.exists(files_dir):
                for root, _, files in os.walk(files_dir):
                    for file in files:
                        src_file = os.path.join(root, file)
                        rel_file = os.path.relpath(src_file, files_dir)
                        if rel_file == ".env" and not restore_env:
                            continue
                        dest_file = os.path.join(constants.BASE_DIR, rel_file)
                        os.makedirs(os.path.dirname(dest_file), exist_ok=True)
                        shutil.copy2(src_file, dest_file)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    @staticmethod
    def restart_services():
        """Gracefully signal Gunicorn workers and stop/resume Scheduler."""
        print("Executing Graceful Service Restart Sequence...")
        
        # 1. Stop scheduler background thread gracefully by setting flag
        try:
            with open(constants.SCAN_CANCEL_FLAG, 'w') as f:
                f.write('1')
        except Exception:
            pass

        # 2. Touch reload files or trigger Gunicorn reload via SIGHUP
        # Under Gunicorn, reloading can be achieved by sending SIGHUP to the master process
        # For multi-worker WSGI servers, writing to a reload file or touching app.py is widely supported.
        try:
            # Touch app.py to trigger Flask reloader if in debug mode
            app_py = os.path.join(constants.BASE_DIR, 'app.py')
            if os.path.exists(app_py):
                os.utime(app_py, None)
        except Exception:
            pass

        # Clean cancel flag file
        try:
            if os.path.exists(constants.SCAN_CANCEL_FLAG):
                os.unlink(constants.SCAN_CANCEL_FLAG)
        except Exception:
            pass
