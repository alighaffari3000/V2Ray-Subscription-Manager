# V2Ray Subscription Manager (v3) 🚀

A lightweight, high-performance, and secure Flask application to manage V2Ray/Xray subscription links. Fully self-contained and designed to simplify client distribution.

سیستم مدیریت سابسکریپشن V2Ray نسخه ۳ - یک برنامه فریم‌ورک Flask سبک، کارآمد و امن برای مدیریت و شخصی‌سازی لینک‌های سابسکریپشن پروتکل‌های VMess, VLESS, Trojan, Hysteria2 و Shadowsocks.

---

## 🌟 Key Features / ویژگی‌های کلیدی

### 1. User Management / مدیریت کاربران
* **Per-user subscription links**: Create a user with a name, a subscription duration (in days), and a unique link (`/sub/<random-or-custom-path>`). Every link belongs to a user — there is no shared/public link.
* **Activation on first use**: The countdown to expiry starts the moment the client first fetches the link, not when the admin creates it.
* **Unlimited plans**: Set duration to `0` for a subscription with no expiry, and max devices to `0` for no device cap.
* **Fair pause/resume**: Pausing a user freezes their remaining time; resuming restores it exactly, crediting back the paused duration.
* **Graceful expiry**: Once a subscription expires (or is paused/disabled), the client receives a single placeholder config named "Subscription expired" instead of the real list — no broken connection, just a clear signal.
* **Per-user usage history**: View every access (timestamp, IP, User-Agent, status) and the distinct devices/clients that have connected with a given user's link.
* **لینک اشتراک اختصاصی برای هر کاربر**: ساخت کاربر با نام، مدت اشتراک (روز) و لینک یکتا؛ دیگر لینک عمومی/مشترک وجود ندارد — هر لینک متعلق به یک کاربر است.
* **فعال‌سازی در اولین استفاده**: شمارش انقضا از لحظه‌ی اولین دریافت لینک توسط کلاینت آغاز می‌شود، نه از لحظه‌ی ساخت کاربر.
* **اشتراک نامحدود**: مقدار `۰` برای مدت اشتراک یعنی بدون انقضا، و `۰` برای حداکثر دستگاه یعنی بدون محدودیت.
* **توقف و ازسرگیری منصفانه**: با توقف اشتراک، زمان باقی‌مانده منجمد می‌شود و با ازسرگیری، دقیقاً همان مدت به تاریخ انقضا اضافه می‌شود.
* **پایان اشتراک بدون قطعی**: پس از انقضا (یا توقف/غیرفعال‌سازی)، به‌جای کانفیگ‌های واقعی، یک کانفیگ نمایشی با نام «اشتراک شما به پایان رسیده است» ارسال می‌شود.
* **تاریخچه‌ی مصرف هر کاربر**: مشاهده‌ی کامل دسترسی‌ها (زمان، IP، User-Agent، وضعیت) و دستگاه‌های متمایزی که با لینک هر کاربر متصل شده‌اند.

### 2. Smart Remark Formatting / فرمت‌دهی هوشمند نام کانفیگ‌ها
* **Index Numbering**: Subscription output names are dynamically re-indexed in-memory (e.g. `1`, `2`, `3`) to look clean.
* **Flag Preservation**: Country flags (e.g., `🇩🇪`, `🇺🇸`) present in the original configuration names are automatically preserved in the subscription remarks (e.g., `🇩🇪 1`, `🇺🇸 2`).
* **Pure In-Memory Processing**: Dynamic formatting runs completely in-memory. **No database writes** are made, keeping your original database names clean and unaltered.
* **حفظ پرچم کشورها**: تبدیل پویای نام کانفیگ‌ها به شماره اندیس در خروجی سابسکریپشن به همراه استخراج و حفظ خودکار اموجی پرچم کشورها (به عنوان مثال `🇩🇪 1` یا `🇺🇸 2`) بدون تغییر دیتابیس اصلی.

### 3. Detailed Stats Dashboard / داشبورد آمار جامع و کلاینت‌ها
* **Overall Metrics**: View total configurations, active vs disabled configs, today's total downloads, and today's unique visitors.
* **Protocol Breakdown**: Monitor counts of VMess, VLESS, Trojan, and Hysteria2 nodes.
* **System Specs**: Displays SQLite database disk size, total download logs, and the most requested path.
* **Client Breakdown**: Aggregates client applications using User-Agent headers (`v2rayNG`, `Nekobox`, `Clash`, `Shadowrocket`, `Sing-box`, `Other`) with interactive visual progress bars.
* **آمار بازدید و کلاینت‌ها**: گزارش وضعیت پایگاه داده، پردرخواست‌ترین مسیرها، آمار کاربران یکتا و تفکیک نرم‌افزارهای کلاینت استفاده شده توسط کاربران.

### 4. Advanced Request Logging / ثبت پیشرفته تاریخچه دسترسی
* Category logs:
  * `SUCCESS` (Successful downloads - 200 OK)
  * `EXPIRED` (Requests from an expired user subscription — served the placeholder config)
  * `USER_PAUSED` (Requests from a paused user — served the placeholder config)
  * `USER_DISABLED` (Requests from a disabled user - 404)
  * `NOT_FOUND` (Requests to a link that isn't any user's - 404)
  * `RATE_LIMIT` (Requests blocked by rate limiting - 429)
* Every log entry (global, in the Logs tab, and per-user in a user's history) records the timestamp, IP, requested path, User-Agent, and status.
* **ثبت لاگ‌های دسترسی**: دسته‌بندی و ذخیره جزئیات دقیق بازدیدها شامل زمان، آدرس IP، مسیر درخواستی، برنامه کلاینت و وضعیت (موفق، منقضی، متوقف، غیرفعال، یافت‌نشده)، هم به‌صورت سراسری در تب لاگ‌ها و هم به‌تفکیک هر کاربر در تاریخچه‌ی اختصاصی او.

### 5. Premium UI/UX / رابط کاربری حرفه‌ای
* Sidebar-driven admin panel (Dashboard, Users, Configs, Auto Scan, Settings, Logs) instead of one long scrolling page.
* Modern dark-first design system with a light mode toggle, Vazirmatn Persian webfont, and a persisted theme preference.
* Responsive design optimized for desktop and mobile.
* Floating Toast notifications for smooth status messages.
* **پنل مدیریت مبتنی بر سایدبار**: دسترسی سریع به تب‌های داشبورد، کاربران، کانفیگ‌ها، اسکن خودکار، تنظیمات و لاگ‌ها بدون اسکرول طولانی.
* **سیستم طراحی تیره به‌عنوان پیش‌فرض**: با امکان تغییر به تم روشن، فونت فارسی Vazirmatn و انیمیشن‌های روان بهینه‌سازی‌شده برای موبایل و دسکتاپ.

---

## 🛠️ Automated Installation / نصب خودکار (لینوکس)

One line on a fresh VPS installs and configures everything (Python venv, dependencies, the V2RayDAR scan engine — prebuilt binary when available, compiled from source otherwise — Nginx, systemd daemon, and free SSL via Certbot):

نصب یک‌خطی روی سرور تازه — تمام مراحل شامل محیط مجازی پایتون، پیش‌نیازها، موتور اسکن V2RayDAR (باینری آماده و در صورت نیاز کامپایل از سورس)، وب‌سرور Nginx، سرویس systemd و گواهی SSL رایگان به صورت خودکار انجام می‌شود:

```bash
bash <(curl -Ls https://raw.githubusercontent.com/alighaffari3000/V2Ray-Subscription-Manager/master/v2raysub/install.sh)
```

Or from a local clone / یا از داخل کلون محلی مخزن:

```bash
sudo bash install.sh
```

---

## 🏗️ Manual Installation / نصب دستی

If you want to configure it step-by-step:

### 1. Clone & Setup Directory
Copy files to `/home/v2ray-sub`.

### 2. Python Virtual Environment
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. Setup configuration
Create a `.env` file in the root directory:
```env
ADMIN_USERNAME=your_username
ADMIN_PASSWORD=your_hashed_password
SECRET_KEY=generate_random_hex
```

**Important:** `ADMIN_PASSWORD` must be a Werkzeug password hash, not a plain-text password.
Generate it with:
```bash
python3 -c "from werkzeug.security import generate_password_hash; print(generate_password_hash(input('Password: ')))"
```

Then paste the output (e.g. `scrypt:32768:8:1$...`) as the value of `ADMIN_PASSWORD`.

> **Migrating from plain-text passwords:** If you already have a running installation with
> a plain-text `ADMIN_PASSWORD`, re-run `sudo bash install.sh` or manually replace the value
> with a hash generated using the command above, then restart the service.

### 4. Setup systemd service
Copy `v2ray-sub.service` to `/etc/systemd/system/v2ray-sub.service`:
```bash
sudo cp v2ray-sub.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable v2ray-sub
sudo systemctl start v2ray-sub
```

### 5. Setup Nginx Reverse Proxy
Copy `v2ray-sub` to `/etc/nginx/sites-available/`:
```bash
sudo cp v2ray-sub /etc/nginx/sites-available/v2ray-sub
sudo ln -s /etc/nginx/sites-available/v2ray-sub /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

---

## 📂 Project Structure / ساختار فایل‌ها

```text
├── app.py                # WSGI entry bootstrapper / فایل راه‌انداز پروژه
├── app_factory.py        # Flask App factory setup / فایل ساخت و پیکربندی برنامه فلاسک
├── config.py             # Global Config loader / مدیریت و بارگذاری تنظیمات از .env
├── database.py           # SQLite connection & schema helpers / ارتباط با دیتابیس لایت
├── extensions.py         # Shared Flask extensions (rate limiter) / اکستنشن‌های مشترک فلاسک
├── install.sh            # Fully Automated Bash Installer / اسکریپت نصب خودکار سرور لینوکس
├── requirements.txt      # Python Dependencies / پیش‌نیازهای پروژه
├── v2ray-sub             # Nginx Server block Config / کانفیگ وب‌سرور Nginx
├── v2ray-sub.service     # Systemd Service configuration / کانفیگ سرویس لینوکس
│
├── routes/               # Web Route Blueprints / فایل‌های روت و طرح‌واره‌های وب
│   ├── client.py         # Per-user subscription serving (/sub/<path>) / خروجی سابسکریپشن هر کاربر
│   ├── admin_pages.py    # Admin page templates rendering / رندر صفحات مدیریت
│   └── admin_api.py      # Admin panel JSON API endpoints / ای‌پی‌آی‌های پنل مدیریت
│
├── services/             # Core business logic (Telegram Bot ready) / سرویس‌های محاسباتی هسته
│   ├── user_service.py   # User CRUD, activation, pause/resume, expiry, history / منطق کامل مدیریت کاربران
│   ├── subscription_service.py # Subscription resolution + expired-placeholder config / پردازش نهایی ساب
│   ├── path_service.py   # Legacy shared-path helpers (see note below) / باقیمانده‌ی مسیر عمومی حذف‌شده
│   ├── config_service.py # Configs CRUD operations / مدیریت و تغییر نام کانفیگ‌ها
│   └── statistics_service.py   # Chart telemetry & logs gathering / آمار و تاریخچه‌ها
│
├── utils/                # Pure side-effect-free helpers / ابزارهای کمکی محاسباتی
│   ├── constants.py      # Shared system constants / ثوابت عمومی سیستم
│   ├── config_parser.py  # VMess/VLESS decoders & flag retainers / استخراج‌کننده‌ها و پردازشگرها
│   ├── user_agent.py     # User-Agent client classification / دسته‌بندی برنامه‌ها
│   ├── process_lock.py   # Inter-process file lock (gunicorn workers) / قفل فایلی بین‌پروسه‌ای
│   └── misc.py           # Size and proxy URL helpers / ابزارهای کمکی اندازه و پروکسی
│
├── templates/            # HTML templates / قالب‌های فرانت‌اند
│   ├── admin.html        # Upgraded Admin Panel UI / پنل مدیریت پیشرفته
│   └── login.html        # Login View / صفحه ورود پنل
└── .gitignore            # Git ignored patterns / لیست فایل‌های نادیده گرفته شده در گیت
```

> **Note:** `path_service.py` (shared/public subscription paths) predates the per-user model above.
> The public-link concept has been retired — on startup, `database.py` migrates any leftover
> shared path into a deletable user and drops the old row — but `admin_api.py`/`admin_pages.py`
> still import a few of its functions, so the file remains for now pending a cleanup pass.
>
> `path_service.py` (مدیریت مسیرهای عمومی/مشترک) بازمانده‌ی مدل قدیمی قبل از مدیریت کاربران است.
> مفهوم لینک عمومی حذف شده — هنگام بالا آمدن برنامه، `database.py` هر مسیر مشترک باقی‌مانده را به یک
> کاربر قابل‌حذف مهاجرت می‌دهد — اما چون `admin_api.py`/`admin_pages.py` هنوز چند تابع از آن را
> ایمپورت می‌کنند، فایل فعلاً باقی مانده تا پاک‌سازی بعدی.

---

## 🔒 Security Notes / نکات امنیتی
* Database configuration and environment settings are kept inside `.env` and `database.db`, both of which are securely ignored in git.
* Remember to change the default admin credentials inside `.env` immediately upon installation.
* اطلاعات ورود در فایل محلی `.env` و اطلاعات پایگاه داده در `database.db` ذخیره می‌شوند که برای حفظ امنیت در گیت کامیت نمی‌شوند. لطفاً پس از نصب اول، اطلاعات ورود پیش‌فرض را تغییر دهید.

---

## 💾 Backup & Disaster Recovery / پشتیبان‌گیری و بازیابی اطلاعات (DR)

The application features a production-grade Backup and Disaster Recovery system that ensures your critical user data, subscription paths, configuration items, and health scan histories are safe and recoverable.

سیستم پیشرفته‌ی پشتیبان‌گیری و بازیابی فاجعه (DR) امکان حفاظت کامل از کاربران، تنظیمات، تاریخچه بازدید و کانفیگ‌های فعال را برای ادمین‌ها فراهم می‌کند.

### 1. Backup Profiles / انواع نسخه‌های پشتیبان
- **Standard Backup (استاندارد):** Packs all database tables and core template assets. **Excludes host credentials/secrets (`.env`)**. Suitable for migrating panel data from one server to another. Requires no passwords or encryption.
- **Full Disaster Recovery Backup (کامل):** Packages all tables and host secrets (`.env`). Supports optional **AES-256-GCM** encryption. Designed strictly to restore state on the same machine.

### 2. Auto-Scheduled Backups & Message Delivery / پشتیبان‌گیری خودکار و ارسال به پیام‌رسان
- Backups can be scheduled to run periodically: **Every 6 hours, 12 hours, Daily, Weekly, or Monthly**.
- Automatic cleanup limits local storage (e.g. keeping only the last 30 backups) via a retention policy.
- Automated deliveries automatically upload the encrypted/unencrypted ZIP archive to a **Telegram** or **Bale** bot chat using custom Bot API servers (e.g. `https://tapi.bale.ai` for Bale).
- If network connection fails, delivery triggers **3 retries with exponential backoff** (1m, 5m, 15m) to ensure delivery.

### 3. Safe Restore with Emergency Rollback / بازیابی امن و برگشت در صورت خطا
- **Verification Pre-flight:** Uploaded archives are validated in-memory first (checking ZIP structure, manifest configurations, compatible versions, and SHA256 integrity checksums).
- **Emergency Safeguard:** The system automatically generates a local emergency restore point right before executing any restore.
- **Transactional Rollback:** Database entries are overwritten inside a transaction. If any database or file operation fails mid-restore, the database is rolled back and local files are automatically reverted back to the emergency backup.
- **Service Reload:** Once restored successfully, scheduler threads are gracefully rebooted to apply configuration changes without downtime.
- **Safe `.env` Overwrite:** Full DR restores exclude the `.env` file by default to prevent broken database credentials. Administrators must explicitly toggle configuration overwrite and confirm.
