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
apt update && apt install -y python3 python3-pip python3-venv nginx certbot python3-certbot-nginx

echo -e "${GREEN}[2/8] ایجاد دایرکتوری پروژه...${NC}"
mkdir -p $PROJECT_DIR

echo -e "${GREEN}[3/8] کپی فایل‌های پروژه...${NC}"

# کپی فایل‌ها از مسیر فعلی به مسیر پروژه (در صورت متفاوت بودن)
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
if [ "$SCRIPT_DIR" != "$PROJECT_DIR" ]; then
    cp -r "$SCRIPT_DIR/app.py" "$SCRIPT_DIR/app_factory.py" "$SCRIPT_DIR/config.py" \
          "$SCRIPT_DIR/database.py" "$SCRIPT_DIR/requirements.txt" \
          "$SCRIPT_DIR/templates" "$SCRIPT_DIR/routes" "$SCRIPT_DIR/services" \
          "$SCRIPT_DIR/utils" "$PROJECT_DIR/"
fi

cd $PROJECT_DIR

echo -e "${GREEN}[4/8] ایجاد محیط مجازی Python و نصب پیش‌نیازها...${NC}"
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

echo -e "${GREEN}[5/8] ساخت فایل .env...${NC}"
SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")

# Hash the admin password using Werkzeug so check_password_hash works at login
HASHED_PASSWORD=$(python3 -c "from werkzeug.security import generate_password_hash; print(generate_password_hash('$admin_password'))")

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

    location / {
        proxy_pass http://127.0.0.1:5000;

        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;

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
chmod 600 $PROJECT_DIR/.env
chmod 644 $PROJECT_DIR/database.db

systemctl daemon-reload
systemctl enable v2ray-sub
systemctl restart v2ray-sub

echo ""
echo -e "${GREEN}==========================================${NC}"
echo -e "${GREEN}🏆 نصب و راه‌اندازی سیستم با موفقیت به پایان رسید!${NC}"
echo -e "${GREEN}==========================================${NC}"
echo ""

# ثبت گواهی SSL در صورت درخواست کاربر
read -p "🔒 آیا می‌خواهید گواهی امنیتی SSL (HTTPS) را با Certbot نصب کنید؟ (y/n): " setup_ssl
if [ "$setup_ssl" = "y" ]; then
    echo -e "${GREEN}در حال اجرای Certbot جهت نصب SSL...${NC}"
    certbot --nginx -d $DOMAIN --non-interactive --agree-tos --email webmaster@$DOMAIN || echo -e "${RED}⚠️ صدور گواهی با خطا مواجه شد. لطفا بعدا به صورت دستی اقدام کنید.${NC}"
fi

echo ""
echo -e "${GREEN}اطلاعات دسترسی به پنل مدیریت:${NC}"
echo -e "  URL:       ${YELLOW}http://$DOMAIN/adminpanel${NC} (یا https در صورت نصب SSL)"
echo -e "  Username:  ${YELLOW}$admin_username${NC}"
echo -e "  Password:  ${YELLOW}[همان رمزی که انتخاب کردید]${NC}"
echo ""
echo -e "${GREEN}لینک سابسکریپشن فعال:${NC}"
echo -e "  Subscription URL: ${YELLOW}http://$DOMAIN/sub/freeconfigs${NC}"
echo ""
echo "=========================================="