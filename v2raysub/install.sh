#!/bin/bash

# اسکریپت نصب و راه‌اندازی تمام خودکار سیستم مدیریت سابسکریپشن V2Ray
# نویسنده: Persian V2 Services
# تاریخ: 2026

set -e

# رنگ‌ها برای نمایش بهتر
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}==========================================${NC}"
echo -e "${GREEN}    نصب تمام خودکار مدیریت سابسکریپشن V2Ray${NC}"
echo -e "${GREEN}==========================================${NC}"
echo ""

# بررسی دسترسی root
if [ "$EUID" -ne 0 ]; then 
    echo -e "${RED}❌ لطفاً این اسکریپت را با دسترسی root اجرا کنید (sudo)${NC}"
    exit 1
fi

# متغیر دایرکتوری پروژه
PROJECT_DIR="/home/v2ray-sub"
REPO_SLUG="alighaffari3000/V2Ray-Subscription-Manager"

# ── حالت نصب یک‌خطی (bootstrap) ──────────────────────────────────
# اگر اسکریپت به تنهایی اجرا شده باشد (bash <(curl ...)) و فایل‌های پروژه کنارش
# نباشند، ابتدا سورس کامل مخزن دانلود و سپس نصب از داخل آن ادامه پیدا می‌کند.
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]:-.}" )" 2>/dev/null && pwd || echo /tmp )"
if [ ! -f "$SCRIPT_DIR/app_factory.py" ]; then
    echo -e "${GREEN}⬇️  فایل‌های پروژه یافت نشد؛ در حال دانلود سورس از GitHub...${NC}"
    TMP_DIR=$(mktemp -d)
    curl -fsSL "https://github.com/$REPO_SLUG/archive/refs/heads/master.tar.gz" | tar -xz -C "$TMP_DIR"
    exec bash "$TMP_DIR/V2Ray-Subscription-Manager-master/v2raysub/install.sh"
fi

# دریافت دامنه و پورت تعاملی
read -p "🌐 لطفاً آدرس دامنه خود را وارد کنید (مثال: sub.mydomain.com): " DOMAIN
if [ -z "$DOMAIN" ]; then
    echo -e "${RED}❌ آدرس دامنه نمی‌تواند خالی باشد!${NC}"
    exit 1
fi

read -p "🔌 پورت اجرای وب‌سرور Nginx (پیش‌فرض: 80): " PORT
PORT=${PORT:-80}

read -p "👤 نام کاربری ادمین پنل (پیش‌فرض: admin): " admin_username
admin_username=${admin_username:-admin}

read -sp "🔑 رمز عبور ادمین پنل: " admin_password
echo ""
if [ -z "$admin_password" ]; then
    echo -e "${RED}❌ رمز عبور نمی‌تواند خالی باشد!${NC}"
    exit 1
fi

echo -e "\n${GREEN}[1/8] نصب پکیج‌های پیش‌نیاز سیستم...${NC}"
# build-essential/cmake/pkg-config برای کامپایل V2RayDAR لازم‌اند (rusqlite bundled و aws-lc-rs)
apt update && apt install -y python3 python3-pip python3-venv nginx certbot python3-certbot-nginx \
    build-essential cmake pkg-config curl

echo -e "${GREEN}[2/8] ایجاد دایرکتوری پروژه...${NC}"
mkdir -p $PROJECT_DIR

echo -e "${GREEN}[3/8] کپی فایل‌های پروژه...${NC}"

# کپی فایل‌ها از مسیر فعلی به مسیر پروژه (در صورت متفاوت بودن)
if [ "$SCRIPT_DIR" != "$PROJECT_DIR" ]; then
    # کپی فایل‌های وب‌پنل
    cp -r "$SCRIPT_DIR/app.py" "$SCRIPT_DIR/app_factory.py" "$SCRIPT_DIR/config.py" \
          "$SCRIPT_DIR/database.py" "$SCRIPT_DIR/extensions.py" "$SCRIPT_DIR/requirements.txt" \
          "$SCRIPT_DIR/templates" "$SCRIPT_DIR/routes" "$SCRIPT_DIR/services" \
          "$SCRIPT_DIR/utils" "$PROJECT_DIR/"
    # کپی فایل‌های موتور اسکن V2RayDAR داخل مسیر پروژه
    if [ -d "$SCRIPT_DIR/../V2RayDAR-main" ]; then
        cp -r "$SCRIPT_DIR/../V2RayDAR-main" "$PROJECT_DIR/"
    elif [ -d "$SCRIPT_DIR/V2RayDAR-main" ]; then
        cp -r "$SCRIPT_DIR/V2RayDAR-main" "$PROJECT_DIR/"
    fi
fi

cd $PROJECT_DIR

echo -e "${GREEN}[4/8] ایجاد محیط مجازی Python و نصب پیش‌نیازها...${NC}"
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

echo -e "${GREEN}[4.5/8] آماده‌سازی موتور اسکن V2RayDAR و نصب Sing-box...${NC}"

# ── اول: تلاش برای دانلود باینری از پیش‌ساخته از GitHub Releases ──
# (ساخته‌شده توسط GitHub Actions؛ سرورهای ضعیف نیازی به کامپایل Rust ندارند)
V2RAYDAR_READY=0
if [ "$(uname -m)" = "x86_64" ]; then
    echo -e "${GREEN}⬇️  در حال دانلود باینری از پیش‌ساخته V2RayDAR...${NC}"
    if curl -fsSL --retry 2 -o /tmp/v2raydar.download \
        "https://github.com/$REPO_SLUG/releases/download/v2raydar-latest/v2raydar-linux-amd64"; then
        chmod +x /tmp/v2raydar.download
        # صحت اجرا روی همین سیستم (سازگاری glibc) قبل از پذیرفتن باینری
        if /tmp/v2raydar.download --version >/dev/null 2>&1; then
            mv /tmp/v2raydar.download /usr/local/bin/v2raydar
            V2RAYDAR_READY=1
            echo -e "${GREEN}✅ باینری از پیش‌ساخته نصب شد: $(/usr/local/bin/v2raydar --version 2>/dev/null | head -1)${NC}"
        else
            echo -e "${YELLOW}⚠️ باینری دانلودشده روی این سیستم اجرا نشد (احتمالاً glibc قدیمی). کامپایل از سورس انجام می‌شود.${NC}"
            rm -f /tmp/v2raydar.download
        fi
    else
        echo -e "${YELLOW}⚠️ دانلود باینری ناموفق بود. کامپایل از سورس انجام می‌شود.${NC}"
    fi
fi

# ── دوم: کامپایل از سورس فقط اگر باینری آماده در دسترس نبود ──
if [ "$V2RAYDAR_READY" = "1" ]; then
    :
elif [ -d "$PROJECT_DIR/V2RayDAR-main" ]; then
    # V2RayDAR از edition 2024 استفاده می‌کند → حداقل Rust 1.85 لازم است.
    # cargo قدیمی distro (مثلاً 1.75 در Ubuntu 24.04) کافی نیست؛ در آن صورت rustup نصب می‌شود.
    NEED_RUST=1
    if command -v cargo &> /dev/null; then
        CARGO_MINOR=$(cargo --version 2>/dev/null | awk '{print $2}' | cut -d. -f2)
        if [ "${CARGO_MINOR:-0}" -ge 85 ]; then
            NEED_RUST=0
        else
            echo -e "${YELLOW}نسخه cargo موجود قدیمی است ($(cargo --version)). نصب Rust جدید با rustup...${NC}"
        fi
    fi
    if [ "$NEED_RUST" = "1" ]; then
        echo -e "${YELLOW}در حال نصب Rust از طریق rustup...${NC}"
        curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
        source "$HOME/.cargo/env"
    fi

    echo -e "${GREEN}در حال کامپایل موتور V2RayDAR (ممکن است چند دقیقه طول بکشد)...${NC}"
    cd "$PROJECT_DIR/V2RayDAR-main"
    cargo build --release
    cp target/release/v2raydar /usr/local/bin/v2raydar
    cd $PROJECT_DIR

    # تست اجرای باینری موتور
    if command -v v2raydar &> /dev/null; then
        echo -e "${GREEN}🔎 تست اجرای موتور اسکن V2RayDAR با موفقیت انجام شد:${NC}"
        v2raydar --version || v2raydar worker --help || true
    fi
else
    echo -e "${RED}⚠️ پوشه V2RayDAR-main یافت نشد. از باینری‌های عمومی استفاده خواهد شد.${NC}"
fi

# نصب Sing-box — شکست این مرحله نباید کل نصب را متوقف کند
# (وب‌پنل بدون sing-box هم کار می‌کند؛ فقط پروب سلامت کانفیگ‌ها به آن نیاز دارد)
if ! command -v sing-box &> /dev/null; then
    echo -e "${GREEN}در حال نصب هسته Sing-box...${NC}"
    if ! bash -c "$(curl -fsSL https://sing-box.app/install.sh)"; then
        echo -e "${RED}⚠️ نصب Sing-box ناموفق بود. بعداً به صورت دستی نصبش کنید؛ نصب ادامه می‌یابد.${NC}"
    fi
fi

echo -e "${GREEN}[5/8] ساخت فایل .env...${NC}"
SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")

# Hash the admin password using Werkzeug so check_password_hash works at login.
# The password is passed via an environment variable (NOT string interpolation)
# so special characters like ' or $ cannot break or inject into the command.
HASHED_PASSWORD=$(ADMIN_PW="$admin_password" python3 -c "import os; from werkzeug.security import generate_password_hash; print(generate_password_hash(os.environ['ADMIN_PW']))")

cat > .env << EOF
ADMIN_USERNAME=$admin_username
ADMIN_PASSWORD=$HASHED_PASSWORD
SECRET_KEY=$SECRET_KEY
EOF
chmod 600 .env

echo -e "${GREEN}[6/8] راه‌اندازی پایگاه داده...${NC}"
python3 -c "from app_factory import create_app; create_app()"

echo -e "${GREEN}[7/8] پیکربندی و راه‌اندازی Nginx برای دامنه $DOMAIN...${NC}"
cat > /etc/nginx/sites-available/v2ray-sub << EOF
server {
    listen $PORT;
    server_name $DOMAIN;

    access_log /var/log/nginx/v2ray-sub-access.log;
    error_log  /var/log/nginx/v2ray-sub-error.log;

    client_max_body_size 10M;

    # Gzip Compression
    gzip on;
    gzip_types text/plain text/css application/json application/javascript text/xml application/xml application/xml+rss text/javascript;

    # Security Headers
    add_header X-Frame-Options "SAMEORIGIN";
    add_header X-XSS-Protection "1; mode=block";
    add_header X-Content-Type-Options "nosniff";
    add_header Referrer-Policy "no-referrer-when-downgrade";

    location / {
        proxy_pass http://127.0.0.1:5000;

        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;

        # پروژه WebSocket ندارد؛ ارسال بی‌قید و شرط هدر Connection: upgrade
        # keep-alive را خراب می‌کرد. HTTP/1.1 برای keep-alive نگه داشته شده است.
        proxy_http_version 1.1;
        proxy_set_header Connection "";

        proxy_connect_timeout 60s;
        proxy_send_timeout    60s;
        proxy_read_timeout    60s;
    }
}
EOF

ln -sf /etc/nginx/sites-available/v2ray-sub /etc/nginx/sites-enabled/
# غیرفعال کردن سایت پیش‌فرض در صورت استفاده از پورت 80 برای جلوگیری از تداخل
if [ -f /etc/nginx/sites-enabled/default ] && [ "$PORT" = "80" ]; then
    rm -f /etc/nginx/sites-enabled/default
fi

nginx -t
systemctl restart nginx

echo -e "${GREEN}[8/8] راه‌اندازی سرویس daemon (systemd) پروژه...${NC}"
cat > /etc/systemd/system/v2ray-sub.service << EOF
[Unit]
Description=V2Ray Subscription Manager
After=network.target

[Service]
User=www-data
WorkingDirectory=$PROJECT_DIR
ExecStart=$PROJECT_DIR/venv/bin/gunicorn --workers 3 --bind 127.0.0.1:5000 app:app
Restart=always

[Install]
WantedBy=multi-user.target
EOF

# تنظیم پرمیشن‌ها برای مالک www-data جهت مدیریت دیتابیس
chown -R www-data:www-data $PROJECT_DIR
chmod -R 755 $PROJECT_DIR
if [ -f "$PROJECT_DIR/.env" ]; then
    chmod 600 "$PROJECT_DIR/.env"
fi
if [ -f "$PROJECT_DIR/database.db" ]; then
    chmod 644 "$PROJECT_DIR/database.db"
fi

systemctl daemon-reload
systemctl enable v2ray-sub
systemctl restart v2ray-sub

# بررسی وضعیت اجرای سرویس
sleep 2
if systemctl is-active v2ray-sub > /dev/null; then
    echo -e "${GREEN}✅ سرویس v2ray-sub با موفقیت راه‌اندازی شد و در حال اجرا است.${NC}"
else
    echo -e "${RED}❌ خطای بحرانی: سرویس v2ray-sub با خطا مواجه شد و بالا نیامد! لاگ‌های زیر را بررسی کنید:${NC}"
    journalctl -u v2ray-sub -n 20 --no-pager
    exit 1
fi

echo ""
echo -e "${GREEN}==========================================${NC}"
echo -e "${GREEN}🏆 نصب و راه‌اندازی سیستم با موفقیت به پایان رسید!${NC}"
echo -e "${GREEN}==========================================${NC}"
echo ""

# ثبت گواهی SSL در صورت درخواست کاربر
# Certbot برای اعتبارسنجی دامنه به پورت ۸۰ نیاز دارد؛ اگر پنل روی پورت دیگری باشد
# صدور گواهی شکست می‌خورد، پس از قبل به کاربر اطلاع می‌دهیم.
if [ "$PORT" != "80" ]; then
    echo -e "${YELLOW}⚠️ وب‌سرور روی پورت $PORT تنظیم شده است. Certbot برای صدور گواهی به پورت ۸۰ نیاز دارد،"
    echo -e "   بنابراین نصب خودکار SSL در این حالت پشتیبانی نمی‌شود و از آن صرف‌نظر می‌شود.${NC}"
    setup_ssl="n"
else
    read -p "🔒 آیا می‌خواهید گواهی امنیتی SSL (HTTPS) را با Certbot نصب کنید؟ (y/n): " setup_ssl
fi
if [ "$setup_ssl" = "y" ]; then
    echo -e "${GREEN}در حال اجرای Certbot جهت نصب SSL...${NC}"
    if certbot --nginx -d $DOMAIN --non-interactive --agree-tos --email webmaster@$DOMAIN; then
        # با فعال شدن HTTPS، کوکی سشن فقط روی اتصال امن ارسال شود
        echo "SESSION_COOKIE_SECURE=1" >> "$PROJECT_DIR/.env"
        systemctl restart v2ray-sub
    else
        echo -e "${RED}⚠️ صدور گواهی با خطا مواجه شد. لطفا بعدا به صورت دستی اقدام کنید.${NC}"
    fi
fi

echo ""
echo -e "${GREEN}اطلاعات دسترسی به پنل مدیریت:${NC}"
echo -e "  URL:       ${YELLOW}http://$DOMAIN/adminpanel${NC} (یا https در صورت نصب SSL)"
echo -e "  Username:  ${YELLOW}$admin_username${NC}"
echo -e "  Password:  ${YELLOW}[همان رمزی که انتخاب کردید]${NC}"
echo ""
echo -e "${GREEN}لینک سابسکریپشن فعال:${NC}"
echo -e "  Subscription URL: ${YELLOW}http://$DOMAIN/sub/freeconfigs${NC}"
echo "=========================================="