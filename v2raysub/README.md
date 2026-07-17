# V2Ray Subscription Manager (v3) 🚀

A lightweight, high-performance, and secure Flask application to manage V2Ray/Xray subscription links. Fully self-contained and designed to simplify client distribution.

سیستم مدیریت سابسکریپشن V2Ray نسخه ۳ - یک برنامه فریم‌ورک Flask سبک، کارآمد و امن برای مدیریت و شخصی‌سازی لینک‌های سابسکریپشن پروتکل‌های VMess, VLESS, Trojan, Hysteria2 و Shadowsocks.

---

## 🌟 Key Features / ویژگی‌های کلیدی

### 1. Dynamic Paths / مدیریت مسیرهای پویا
* **Custom Paths**: Change your subscription path dynamically from the admin panel (e.g. from `/sub/freeconfigs` to `/sub/custompath123`).
* **Auxiliary Paths**: Create, enable, disable, or delete additional subscription paths. Disabling a path immediately returns a `404 Not Found` response to clients.
* **Random Paths**: Generate cryptographically secure, unique 16-character alphanumeric paths with one click.
* **تغییر پویای آدرس**: امکان مدیریت، فعال/غیرفعال کردن یا حذف مسیرهای سابسکریپشن و تغییر آدرس اصلی به صورت آنی بدون نیاز به تغییر یا راه‌اندازی مجدد کد.

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
  * `DISABLED_PATH` (Requests to disabled paths - 404)
  * `NOT_FOUND` (Requests to non-existent paths - 404)
  * `RATE_LIMIT` (Requests blocked by rate limiting - 429)
* **ثبت لاگ‌های دسترسی**: دسته‌بندی و ذخیره جزئیات دقیق بازدیدها شامل زمان، آدرس IP، آدرس مسیر درخواستی، برنامه کلاینت و وضعیت موفقیت یا خطا.

### 5. Premium UI/UX / رابط کاربری حرفه‌ای
* Responsive design optimized for desktop and mobile.
* Sleek dark mode / light mode toggle.
* Floating Toast notifications for smooth status messages.
* **رابط کاربری واکنش‌گرا**: دارای تم‌های تاریک و روشن، انیمیشن‌های روان و اعلان‌های پویای Toast بهینه‌سازی شده برای موبایل و دسکتاپ.

---

## 🛠️ Automated Installation / نصب خودکار (لینوکس)

Just run the automated script with root privileges to install and configure everything (Python Virtual Environment, dependencies, Nginx configuration, Systemd daemon, and free SSL Certbot):

اسکریپت تعاملی زیر تمام مراحل نصب شامل وب‌سرور Nginx، سرویس سیستم‌دی، دریافت دامنه، پورت، ایجاد متغیرهای امنیتی پنل و نصب خودکار گواهی SSL را به صورت تمام خودکار انجام می‌دهد:

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
│   ├── client.py         # Dynamic Subscription client routes / خروجی سابسکریپشن
│   ├── admin_pages.py    # Admin page templates rendering / رندر صفحات مدیریت
│   └── admin_api.py      # Admin panel JSON API endpoints / ای‌پی‌آی‌های پنل مدیریت
│
├── services/             # Core business logic (Telegram Bot ready) / سرویس‌های محاسباتی هسته
│   ├── subscription_service.py # Subscription resolution logic / پردازش نهایی ساب
│   ├── path_service.py   # Sub paths CRUD operations / مدیریت پویای آدرس‌ها
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

---

## 🔒 Security Notes / نکات امنیتی
* Database configuration and environment settings are kept inside `.env` and `database.db`, both of which are securely ignored in git.
* Remember to change the default admin credentials inside `.env` immediately upon installation.
* اطلاعات ورود در فایل محلی `.env` و اطلاعات پایگاه داده در `database.db` ذخیره می‌شوند که برای حفظ امنیت در گیت کامیت نمی‌شوند. لطفاً پس از نصب اول، اطلاعات ورود پیش‌فرض را تغییر دهید.
