#!/bin/bash

# Fully automated installer for the V2Ray Subscription Manager.
# Messages are English-only: Persian text renders unreliably in most terminals
# (bidi reordering, missing fonts) and made installer output hard to read.

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}==========================================${NC}"
echo -e "${GREEN}    V2Ray Subscription Manager - Installer${NC}"
echo -e "${GREEN}==========================================${NC}"
echo ""

# Require root
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}[X] Please run this script as root (sudo).${NC}"
    exit 1
fi

PROJECT_DIR="/home/v2ray-sub"
REPO_SLUG="alighaffari3000/V2Ray-Subscription-Manager"

# Every network call is bounded: without these, a stalled connection (common
# where GitHub's CDN is throttled) hangs the installer forever instead of
# failing over to the next strategy.
CONNECT_TIMEOUT=15
# Short calls (source tarball, scripts) get a hard ceiling.
DOWNLOAD_MAX_TIME=300
# The 18 MB binary can crawl at a few KB/s over GitHub's CDN from some regions,
# so a hard ceiling would guarantee failure. Instead abort only on a *true*
# stall: under 1 KB/s for 60s straight. A slow-but-moving download keeps going.
STALL_SPEED_BYTES=1024
STALL_SECONDS=60

# True only if some process is already listening on TCP port $1. Used for the
# interactive port prompt so a taken port produces a re-prompt, not a crash
# three steps later when nginx fails to bind.
port_in_use() {
    ss -tln 2>/dev/null | awk '{print $4}' | grep -qE "[:.]$1\$"
}

# Download $1 to $2, resuming across retries and tolerating slow-but-alive
# links. Tries the direct GitHub URL first, then mirrors that proxy GitHub and
# are often reachable where the CDN is throttled. Prints which one won.
download_with_mirrors() {
    local url="$1" out="$2" src
    # $url is always a github.com path; the mirrors below just prefix it.
    for src in \
        "$url" \
        "https://ghfast.top/$url" \
        "https://gh-proxy.com/$url" \
        "https://ghproxy.net/$url"; do
        echo -e "${GREEN}[*] Trying: ${src}${NC}"
        # -C - resumes a partial file so retries don't restart from 0%.
        if curl -fL -C - --connect-timeout "$CONNECT_TIMEOUT" \
            --speed-limit "$STALL_SPEED_BYTES" --speed-time "$STALL_SECONDS" \
            --retry 3 --retry-delay 3 --progress-bar -o "$out" "$src"; then
            return 0
        fi
        echo -e "${YELLOW}[!] That source failed; trying the next.${NC}"
    done
    return 1
}

# ── One-line bootstrap ───────────────────────────────────────────
# When run standalone via `bash <(curl ...)` the project files aren't on disk,
# so fetch the source tarball first and re-exec from inside it.
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]:-.}" )" 2>/dev/null && pwd || echo /tmp )"
if [ ! -f "$SCRIPT_DIR/app_factory.py" ]; then
    echo -e "${GREEN}[*] Project files not found. Downloading source from GitHub...${NC}"
    TMP_DIR=$(mktemp -d)
    if ! curl -fsSL --connect-timeout "$CONNECT_TIMEOUT" --max-time "$DOWNLOAD_MAX_TIME" --retry 2 \
        "https://github.com/$REPO_SLUG/archive/refs/heads/master.tar.gz" | tar -xz -C "$TMP_DIR"; then
        echo -e "${RED}[X] Failed to download the project source from GitHub.${NC}"
        echo -e "${RED}    Check the server's connectivity to github.com and try again.${NC}"
        exit 1
    fi
    exec bash "$TMP_DIR/V2Ray-Subscription-Manager-master/v2raysub/install.sh"
fi

# ── Update vs. fresh install ─────────────────────────────────────
# Re-running this same one-line command should update an existing install
# (new code, dependencies, and engine binary) rather than re-ask for a domain,
# port, certificate, and admin password every time and risk overwriting a
# working .env/nginx/SSL setup. Detect that case from the artifacts only a
# completed install leaves behind.
EXISTING_INSTALL=0
if [ -f "$PROJECT_DIR/.env" ] && [ -f /etc/systemd/system/v2ray-sub.service ]; then
    EXISTING_INSTALL=1
fi

if [ "$EXISTING_INSTALL" = "1" ]; then
    echo -e "${GREEN}[*] Existing installation found at $PROJECT_DIR — updating in place.${NC}"
    echo -e "${GREEN}    Domain, port, SSL certificate, admin login, and the database are all kept as-is.${NC}"
else
    # ── Interactive settings (fresh install only) ──────────────────
    read -p "Domain name (e.g. sub.mydomain.com): " DOMAIN
    if [ -z "$DOMAIN" ]; then
        echo -e "${RED}[X] Domain cannot be empty.${NC}"
        exit 1
    fi

    while true; do
        read -p "Nginx port [443]: " PORT
        PORT=${PORT:-443}
        if ! [[ "$PORT" =~ ^[0-9]+$ ]] || [ "$PORT" -lt 1 ] || [ "$PORT" -gt 65535 ]; then
            echo -e "${RED}[X] Enter a valid port number (1-65535).${NC}"
            continue
        fi
        if port_in_use "$PORT"; then
            echo -e "${YELLOW}[!] Port $PORT is already in use. Pick a different port.${NC}"
            continue
        fi
        break
    done

    echo ""
    echo "HTTPS needs a certificate. Options:"
    echo "  1) I already have one (provide the certificate and key file paths)"
    echo "  2) Get a free one automatically (Let's Encrypt via Certbot)"
    echo "  3) Skip for now (use plain HTTP)"
    read -p "Choose [1/2/3] (default 2): " SSL_CHOICE
    SSL_CHOICE=${SSL_CHOICE:-2}

    SSL_MODE="none"
    CERT_PATH=""
    KEY_PATH=""
    case "$SSL_CHOICE" in
        1)
            while true; do
                read -p "Path to the certificate file (fullchain .pem/.crt): " CERT_PATH
                read -p "Path to the private key file (.pem/.key): " KEY_PATH
                if [ -f "$CERT_PATH" ] && [ -f "$KEY_PATH" ]; then
                    SSL_MODE="existing"
                    break
                fi
                echo -e "${RED}[X] One or both files don't exist. Try again.${NC}"
            done
            ;;
        2)
            SSL_MODE="auto"
            echo -e "${YELLOW}    Note: automatic issuance needs port 80 reachable from the internet${NC}"
            echo -e "${YELLOW}    (briefly, for verification) regardless of the panel port above.${NC}"
            ;;
        *)
            SSL_MODE="none"
            ;;
    esac

    read -p "Admin username [admin]: " admin_username
    admin_username=${admin_username:-admin}

    read -sp "Admin password: " admin_password
    echo ""
    if [ -z "$admin_password" ]; then
        echo -e "${RED}[X] Password cannot be empty.${NC}"
        exit 1
    fi
fi

echo -e "\n${GREEN}[1/8] Installing system packages...${NC}"
# build-essential/cmake/pkg-config are only needed if we have to compile
# V2RayDAR from source (rusqlite bundled + aws-lc-rs).
apt update && apt install -y python3 python3-pip python3-venv nginx certbot python3-certbot-nginx \
    build-essential cmake pkg-config curl

echo -e "${GREEN}[2/8] Creating project directory...${NC}"
mkdir -p $PROJECT_DIR

echo -e "${GREEN}[3/8] Copying project files...${NC}"
if [ "$SCRIPT_DIR" != "$PROJECT_DIR" ]; then
    cp -r "$SCRIPT_DIR/app.py" "$SCRIPT_DIR/app_factory.py" "$SCRIPT_DIR/config.py" \
          "$SCRIPT_DIR/database.py" "$SCRIPT_DIR/extensions.py" "$SCRIPT_DIR/requirements.txt" \
          "$SCRIPT_DIR/templates" "$SCRIPT_DIR/routes" "$SCRIPT_DIR/services" \
          "$SCRIPT_DIR/utils" "$PROJECT_DIR/"
    # V2RayDAR sources, used only as a fallback if the prebuilt binary is unusable
    if [ -d "$SCRIPT_DIR/../V2RayDAR-main" ]; then
        cp -r "$SCRIPT_DIR/../V2RayDAR-main" "$PROJECT_DIR/"
    elif [ -d "$SCRIPT_DIR/V2RayDAR-main" ]; then
        cp -r "$SCRIPT_DIR/V2RayDAR-main" "$PROJECT_DIR/"
    fi
fi

cd $PROJECT_DIR

echo -e "${GREEN}[4/8] Creating Python virtualenv and installing dependencies...${NC}"
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

echo -e "${GREEN}[4.5/8] Setting up the V2RayDAR scan engine and Sing-box...${NC}"

# ── Preferred: download the prebuilt binary (built by GitHub Actions) ──
# Compiling on a small VPS is slow and can OOM, so only fall back to it.
V2RAYDAR_READY=0
if [ "$(uname -m)" = "x86_64" ]; then
    echo -e "${GREEN}[*] Downloading prebuilt V2RayDAR binary (~18 MB)...${NC}"
    if download_with_mirrors \
        "https://github.com/$REPO_SLUG/releases/download/v2raydar-latest/v2raydar-linux-amd64" \
        /tmp/v2raydar.download; then
        chmod +x /tmp/v2raydar.download
        # Verify it actually runs here (glibc compatibility) before trusting it
        if /tmp/v2raydar.download --version >/dev/null 2>&1; then
            mv /tmp/v2raydar.download /usr/local/bin/v2raydar
            V2RAYDAR_READY=1
            echo -e "${GREEN}[OK] Prebuilt engine installed: $(/usr/local/bin/v2raydar --version 2>/dev/null | head -1)${NC}"
        else
            echo -e "${YELLOW}[!] Downloaded binary won't run here (likely an older glibc). Building from source instead.${NC}"
            rm -f /tmp/v2raydar.download
        fi
    else
        echo -e "${YELLOW}[!] Download failed or timed out. Building from source instead.${NC}"
        rm -f /tmp/v2raydar.download
    fi
fi

# ── Fallback: compile from source ──
if [ "$V2RAYDAR_READY" = "1" ]; then
    :
elif [ -d "$PROJECT_DIR/V2RayDAR-main" ]; then
    echo -e "${YELLOW}[!] Falling back to a source build. This takes several minutes and${NC}"
    echo -e "${YELLOW}    needs ~2 GB of RAM; add swap first if this server has less.${NC}"

    # V2RayDAR uses edition 2024, which needs Rust >= 1.85. The distro cargo
    # (1.75 on Ubuntu 24.04) is too old, so install rustup in that case.
    NEED_RUST=1
    if command -v cargo &> /dev/null; then
        CARGO_MINOR=$(cargo --version 2>/dev/null | awk '{print $2}' | cut -d. -f2)
        if [ "${CARGO_MINOR:-0}" -ge 85 ]; then
            NEED_RUST=0
        else
            echo -e "${YELLOW}[!] Installed cargo is too old ($(cargo --version)). Installing Rust via rustup...${NC}"
        fi
    fi
    if [ "$NEED_RUST" = "1" ]; then
        echo -e "${YELLOW}[*] Installing Rust via rustup...${NC}"
        curl --proto '=https' --tlsv1.2 -sSf --connect-timeout "$CONNECT_TIMEOUT" https://sh.rustup.rs | sh -s -- -y
        source "$HOME/.cargo/env"
    fi

    echo -e "${GREEN}[*] Compiling the V2RayDAR engine...${NC}"
    cd "$PROJECT_DIR/V2RayDAR-main"
    cargo build --release
    cp target/release/v2raydar /usr/local/bin/v2raydar
    cd $PROJECT_DIR

    if command -v v2raydar &> /dev/null; then
        echo -e "${GREEN}[OK] Engine built: $(v2raydar --version 2>/dev/null | head -1)${NC}"
    fi
else
    echo -e "${RED}[!] V2RayDAR sources not found and no prebuilt binary available.${NC}"
    echo -e "${RED}    Automatic scanning will not work until an engine is installed.${NC}"
fi

# Sing-box is only needed for probing; a failure here must not abort the install.
if ! command -v sing-box &> /dev/null; then
    echo -e "${GREEN}[*] Installing the Sing-box core...${NC}"
    if ! bash -c "$(curl -fsSL --connect-timeout "$CONNECT_TIMEOUT" --max-time "$DOWNLOAD_MAX_TIME" https://sing-box.app/install.sh)"; then
        echo -e "${YELLOW}[!] Sing-box installation failed. The panel still works; install it later${NC}"
        echo -e "${YELLOW}    to enable config health probing. Continuing.${NC}"
    fi
fi

# V2RayDAR only auto-detects sing-box *beside its own executable* on Linux — it
# does not search PATH — so a sing-box in /usr/bin is invisible to it. The panel
# (locate_v2raydar) prefers the in-project build over /usr/local/bin, so put a
# sing-box symlink next to every v2raydar we may have placed.
#
# Always drop any symlink we may have created here on a prior run first, then
# locate the real binary by searching only standard system directories —
# never /usr/local/bin, which is where *we* place our own symlink. On a re-run,
# `command -v sing-box` would otherwise resolve to our own (possibly broken)
# symlink there, since /usr/local/bin precedes /usr/bin in PATH; symlinking
# that onto itself makes /usr/local/bin/sing-box point to itself — an infinite
# loop that breaks every scan with "not found". Searching only the real system
# paths is idempotent no matter how many times this script runs.
rm -f /usr/local/bin/sing-box \
    "$PROJECT_DIR/V2RayDAR-main/target/release/sing-box" \
    "$PROJECT_DIR/V2RayDAR-main/target/debug/sing-box" 2>/dev/null
SING_BOX_BIN=""
for dir in /usr/bin /usr/sbin /bin /sbin /usr/local/sbin; do
    if [ -x "$dir/sing-box" ]; then
        SING_BOX_BIN="$dir/sing-box"
        break
    fi
done
if [ -n "$SING_BOX_BIN" ]; then
    for engine_dir in \
        /usr/local/bin \
        "$PROJECT_DIR/V2RayDAR-main/target/release" \
        "$PROJECT_DIR/V2RayDAR-main/target/debug"; do
        # Only bother where a v2raydar actually sits (or /usr/local/bin, the
        # prebuilt destination), and never symlink a file onto itself.
        if [ -x "$engine_dir/v2raydar" ] || [ "$engine_dir" = "/usr/local/bin" ]; then
            if [ "$SING_BOX_BIN" != "$engine_dir/sing-box" ]; then
                ln -sf "$SING_BOX_BIN" "$engine_dir/sing-box"
            fi
        fi
    done
fi

if [ "$EXISTING_INSTALL" = "0" ]; then
    echo -e "${GREEN}[5/8] Writing .env...${NC}"
    SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")

    # Hash the admin password with Werkzeug so check_password_hash works at login.
    # Passed via an environment variable (not string interpolation) so characters
    # like ' or $ cannot break the command or inject code.
    HASHED_PASSWORD=$(ADMIN_PW="$admin_password" python3 -c "import os; from werkzeug.security import generate_password_hash; print(generate_password_hash(os.environ['ADMIN_PW']))")

    cat > .env << EOF
ADMIN_USERNAME=$admin_username
ADMIN_PASSWORD=$HASHED_PASSWORD
SECRET_KEY=$SECRET_KEY
EOF
    chmod 600 .env
else
    echo -e "${GREEN}[5/8] Keeping existing .env (admin login and secret key unchanged).${NC}"
fi

echo -e "${GREEN}[6/8] Initializing the database...${NC}"
python3 -c "from app_factory import create_app; create_app()"

if [ "$EXISTING_INSTALL" = "0" ]; then
    echo -e "${GREEN}[7/8] Configuring Nginx and SSL for $DOMAIN...${NC}"

    if [ "$SSL_MODE" = "auto" ]; then
        echo -e "${GREEN}[*] Requesting a free certificate from Let's Encrypt...${NC}"
        # Standalone binds port 80 itself, so anything already on it (nginx's
        # just-installed default vhost included) must step aside first. The
        # pre/post hooks are saved into the renewal config so the twice-daily
        # `certbot renew` timer also frees port 80 for the brief renewal window.
        systemctl stop nginx 2>/dev/null || true
        if certbot certonly --standalone -d "$DOMAIN" --non-interactive --agree-tos \
            --email "webmaster@$DOMAIN" \
            --pre-hook "systemctl stop nginx" --post-hook "systemctl start nginx"; then
            CERT_PATH="/etc/letsencrypt/live/$DOMAIN/fullchain.pem"
            KEY_PATH="/etc/letsencrypt/live/$DOMAIN/privkey.pem"
            echo -e "${GREEN}[OK] Certificate obtained.${NC}"
        else
            echo -e "${YELLOW}[!] Certificate request failed (often: port 80 isn't reachable from the${NC}"
            echo -e "${YELLOW}    internet, or $DOMAIN's DNS doesn't point here yet). Continuing over${NC}"
            echo -e "${YELLOW}    plain HTTP; retry later with 'certbot certonly --standalone -d $DOMAIN'.${NC}"
            SSL_MODE="none"
        fi
    fi

    if [ "$SSL_MODE" = "existing" ] || [ "$SSL_MODE" = "auto" ]; then
        SSL_LISTEN="listen $PORT ssl;
    ssl_certificate     $CERT_PATH;
    ssl_certificate_key $KEY_PATH;"
        # The cookie must never cross an unencrypted connection now that one exists.
        echo "SESSION_COOKIE_SECURE=1" >> "$PROJECT_DIR/.env"
    else
        SSL_LISTEN="listen $PORT;"
    fi

    cat > /etc/nginx/sites-available/v2ray-sub << EOF
server {
    $SSL_LISTEN
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

        # No WebSocket endpoints here; sending "Connection: upgrade"
        # unconditionally broke upstream keep-alive. HTTP/1.1 is kept for it.
        proxy_http_version 1.1;
        proxy_set_header Connection "";

        proxy_connect_timeout 60s;
        proxy_send_timeout    60s;
        proxy_read_timeout    60s;
    }
}
EOF

    ln -sf /etc/nginx/sites-available/v2ray-sub /etc/nginx/sites-enabled/
    # Always drop nginx's stock default site: it listens on 80 no matter which
    # port we picked, and if anything else already holds 80 it makes the whole
    # nginx process fail to start (bind() ... Address already in use), taking our
    # site down with it.
    rm -f /etc/nginx/sites-enabled/default

    nginx -t
    systemctl restart nginx
else
    echo -e "${GREEN}[7/8] Nginx/SSL already configured — leaving as-is.${NC}"
    # Re-derive these purely for the closing banner; nothing here is written.
    # sed, not grep -P: PCRE needs a UTF-8 locale that a stripped-down VPS
    # image may not have, and this only needs to work, not be clever.
    NGINX_CONF="/etc/nginx/sites-available/v2ray-sub"
    DOMAIN="$(sed -n 's/^[[:space:]]*server_name[[:space:]]\+\([^;]*\);.*/\1/p' "$NGINX_CONF" 2>/dev/null | head -1 | xargs)"
    PORT="$(sed -n 's/^[[:space:]]*listen[[:space:]]\+\([0-9]\+\).*/\1/p' "$NGINX_CONF" 2>/dev/null | head -1)"
    if grep -q 'ssl_certificate ' "$NGINX_CONF" 2>/dev/null; then
        SSL_MODE="existing"
    else
        SSL_MODE="none"
    fi
fi

echo -e "${GREEN}[8/8] Installing the systemd service...${NC}"

# gunicorn will silently fail to bind if port 5000 is already held by an
# unrelated process (e.g. a prior manual install run outside this script, or
# a different app) — the service then crash-loops with no obvious cause.
# Fail loudly here instead of leaving that to be debugged later.
PORT_5000_PID="$(ss -tlnp 2>/dev/null | awk '/:5000 /{print}' | grep -oP 'pid=\K[0-9]+' | head -1)"
if [ -n "$PORT_5000_PID" ]; then
    OWNER_CMD="$(ps -p "$PORT_5000_PID" -o comm= 2>/dev/null || echo unknown)"
    if [ "$OWNER_CMD" != "gunicorn" ]; then
        echo -e "${RED}[X] Port 5000 is already in use by another process (PID $PORT_5000_PID, $OWNER_CMD).${NC}"
        echo -e "${RED}    This is likely a separate, older install. Stop it first, e.g.:${NC}"
        echo -e "${RED}    systemctl stop <its-service>   OR   kill $PORT_5000_PID${NC}"
        exit 1
    fi
fi

cat > /etc/systemd/system/v2ray-sub.service << EOF
[Unit]
Description=V2Ray Subscription Manager
After=network.target

[Service]
User=www-data
WorkingDirectory=$PROJECT_DIR
# www-data's home is /var/www, which it can't write to; gunicorn 26's control
# server tries to create \$HOME/.gunicorn there and errors. Point HOME at the
# project dir (owned by www-data) so it can.
Environment=HOME=$PROJECT_DIR
# Python block-buffers stdout when it's a pipe (systemd), so the app's print()
# scan logs never reach journald promptly. Force unbuffered so `journalctl -f`
# shows scan progress live.
Environment=PYTHONUNBUFFERED=1
ExecStart=$PROJECT_DIR/venv/bin/gunicorn --workers 3 --bind 127.0.0.1:5000 app:app
Restart=always

[Install]
WantedBy=multi-user.target
EOF

# www-data must own the project so it can write the database and lock files
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

sleep 2
if systemctl is-active v2ray-sub > /dev/null; then
    echo -e "${GREEN}[OK] Service v2ray-sub is running.${NC}"
else
    echo -e "${RED}[X] Service v2ray-sub failed to start. Recent logs:${NC}"
    journalctl -u v2ray-sub -n 20 --no-pager
    exit 1
fi

echo ""
echo -e "${GREEN}==========================================${NC}"
if [ "$EXISTING_INSTALL" = "1" ]; then
    echo -e "${GREEN} Update complete.${NC}"
else
    echo -e "${GREEN} Installation complete.${NC}"
fi
echo -e "${GREEN}==========================================${NC}"
echo ""

# SSL was already set up (or skipped) back in step 7, before the .env and
# nginx vhost were written, so the service started with the right config the
# first time — no second restart needed here.
if [ "$SSL_MODE" != "none" ]; then
    SCHEME="https"
else
    SCHEME="http"
fi

if [ -z "$DOMAIN" ]; then
    echo -e "${YELLOW}[!] Could not determine the panel's domain automatically.${NC}"
    echo -e "${YELLOW}    Check /etc/nginx/sites-available/v2ray-sub for the current URL.${NC}"
else
    if { [ "$SCHEME" = "http" ] && [ "$PORT" = "80" ]; } || { [ "$SCHEME" = "https" ] && [ "$PORT" = "443" ]; }; then
        BASE_URL="$SCHEME://$DOMAIN"
    else
        BASE_URL="$SCHEME://$DOMAIN:$PORT"
    fi

    echo ""
    echo -e "${GREEN}Admin panel:${NC}"
    echo -e "  URL:       ${YELLOW}$BASE_URL/adminpanel${NC}"
    if [ "$EXISTING_INSTALL" = "1" ]; then
        echo -e "  Login:     ${YELLOW}unchanged${NC}"
    else
        echo -e "  Username:  ${YELLOW}$admin_username${NC}"
        echo -e "  Password:  ${YELLOW}[the password you chose]${NC}"
    fi
    echo ""
    echo -e "${GREEN}Subscription link:${NC}"
    echo -e "  ${YELLOW}$BASE_URL/sub/freeconfigs${NC}"
fi
echo "=========================================="
