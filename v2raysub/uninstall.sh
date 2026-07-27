#!/bin/bash

# Uninstaller for the V2Ray Subscription Manager — removes everything
# install.sh puts on a server, and nothing else.
#
# Messages are English-only, same reason as the installer: Persian renders
# unreliably in most terminals (bidi reordering, missing fonts).
#
# Deliberately NOT `set -e`. An uninstall that aborts halfway is worse than one
# that reports a failed step and keeps going: the operator is left with a
# half-removed install and no idea which half. Every step tolerates failure and
# the summary at the end says what actually happened.

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Same reason as the installer: systemd tools auto-invoke a pager, and a pager
# waits on the terminal forever.
export SYSTEMD_PAGER=''
export PAGER=cat

PROJECT_DIR="/home/v2ray-sub"
SERVICE="v2ray-sub"

ASSUME_YES=0
KEEP_DATA=1        # save the database + .env before deleting, unless --purge
DELETE_CERT=0

usage() {
    cat <<'EOF'
Usage: uninstall.sh [options]

  --yes           Don't ask for confirmation (for scripted removal).
  --purge         Delete the database too, with no backup copy kept.
  --delete-cert   Also delete the Let's Encrypt certificate for this domain.
                  Off by default: re-issuing counts against Let's Encrypt's
                  rate limits, and the certificate is useful if you reinstall.
  -h, --help      Show this help.

Shared packages (nginx, redis, certbot, python3) are never removed — other
services on this server may depend on them.
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
        --yes|-y)      ASSUME_YES=1 ;;
        --purge)       KEEP_DATA=0 ;;
        --delete-cert) DELETE_CERT=1 ;;
        -h|--help)     usage; exit 0 ;;
        *) echo -e "${RED}[X] Unknown option: $1${NC}"; usage; exit 1 ;;
    esac
    shift
done

echo -e "${GREEN}==========================================${NC}"
echo -e "${GREEN}  V2Ray Subscription Manager - Uninstaller${NC}"
echo -e "${GREEN}==========================================${NC}"
echo ""

# Require root
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}[X] Please run this script as root (sudo).${NC}"
    exit 1
fi

# ── Work out what's actually here ────────────────────────────────
# Read the domain out of the nginx vhost before removing it — it's the only
# place the installed domain is recorded, and --delete-cert needs it.
NGINX_VHOST="/etc/nginx/sites-available/$SERVICE"
DOMAIN=""
if [ -f "$NGINX_VHOST" ]; then
    DOMAIN="$(awk '/server_name/ {print $2; exit}' "$NGINX_VHOST" | tr -d ';')"
fi

FOUND=0
[ -d "$PROJECT_DIR" ] && FOUND=1
[ -f "/etc/systemd/system/$SERVICE.service" ] && FOUND=1
[ -f "$NGINX_VHOST" ] && FOUND=1

if [ "$FOUND" = "0" ]; then
    echo -e "${YELLOW}[!] Nothing to remove: no $PROJECT_DIR, no systemd unit, no nginx vhost.${NC}"
    echo -e "${YELLOW}    This server doesn't look like it has the panel installed.${NC}"
    exit 0
fi

echo -e "${YELLOW}This will remove:${NC}"
echo "  - systemd service           $SERVICE"
echo "  - project directory         $PROJECT_DIR  (code, venv, database, backups)"
echo "  - nginx vhost               $NGINX_VHOST${DOMAIN:+  (domain: $DOMAIN)}"
echo "  - nginx rate-limit zone     /etc/nginx/conf.d/$SERVICE-ratelimit.conf"
echo "  - nginx logs                /var/log/nginx/$SERVICE-*.log"
echo "  - journald cap              /etc/systemd/journald.conf.d/$SERVICE.conf"
echo "  - scan engine               /usr/local/bin/v2raydar (+ our sing-box symlink)"
if [ "$DELETE_CERT" = "1" ] && [ -n "$DOMAIN" ]; then
    echo -e "  - ${RED}SSL certificate           /etc/letsencrypt/live/$DOMAIN${NC}"
fi
echo ""
if [ "$KEEP_DATA" = "1" ]; then
    echo -e "${GREEN}The database and .env will be copied to /root/ first (pass --purge to skip).${NC}"
else
    echo -e "${RED}--purge given: the database will be destroyed with no copy kept.${NC}"
fi
echo -e "${GREEN}Shared packages (nginx, redis, certbot, python3) are kept.${NC}"
echo ""

if [ "$ASSUME_YES" != "1" ]; then
    read -p "Type 'yes' to continue: " CONFIRM
    if [ "$CONFIRM" != "yes" ]; then
        echo -e "${YELLOW}[!] Aborted. Nothing was changed.${NC}"
        exit 1
    fi
fi

# ── 1. Back up the irreplaceable bits ────────────────────────────
# Only the database and .env: everything else (code, venv, engine binary) comes
# straight back from a reinstall, and the storage/ backup archives can be many
# hundreds of MB — copying them to /root could fill the disk during an
# uninstall, which is a nasty way to lose a server.
BACKUP_FILE=""
if [ "$KEEP_DATA" = "1" ] && [ -d "$PROJECT_DIR" ]; then
    echo -e "\n${GREEN}[1/8] Saving the database and .env...${NC}"
    BACKUP_ITEMS=()
    [ -f "$PROJECT_DIR/database.db" ] && BACKUP_ITEMS+=("database.db")
    [ -f "$PROJECT_DIR/.env" ] && BACKUP_ITEMS+=(".env")

    if [ ${#BACKUP_ITEMS[@]} -eq 0 ]; then
        # A half-finished install has the directory but no data yet. Nothing to
        # lose, so don't make the operator pass --purge just to get past this.
        echo -e "${YELLOW}[!] No database or .env found — nothing to save.${NC}"
        BACKUP_FILE=""
    else
        STAMP="$(date +%Y%m%d-%H%M%S)"
        BACKUP_FILE="/root/v2ray-sub-data-$STAMP.tar.gz"
        if tar czf "$BACKUP_FILE" -C "$PROJECT_DIR" "${BACKUP_ITEMS[@]}" 2>/dev/null \
            && [ -s "$BACKUP_FILE" ]; then
            chmod 600 "$BACKUP_FILE"   # holds the machine-API token and admin hash
            echo -e "${GREEN}[OK] Saved to $BACKUP_FILE${NC}"
        else
            # A failed backup must stop the uninstall: continuing would destroy
            # the data the operator just asked us to preserve.
            echo -e "${RED}[X] Backup failed — refusing to delete anything.${NC}"
            echo -e "${RED}    Copy $PROJECT_DIR/database.db somewhere safe yourself,${NC}"
            echo -e "${RED}    then re-run with --purge.${NC}"
            rm -f "$BACKUP_FILE"
            exit 1
        fi
    fi
else
    echo -e "\n${GREEN}[1/8] Skipping data backup (--purge).${NC}"
fi

# ── 2. Stop the service ──────────────────────────────────────────
echo -e "\n${GREEN}[2/8] Stopping and disabling the service...${NC}"
systemctl stop "$SERVICE" 2>/dev/null || true
systemctl disable "$SERVICE" 2>/dev/null || true
# A unit that failed leaves a latched failure state behind that survives the
# unit file being deleted; systemctl then reports a ghost service forever.
systemctl reset-failed "$SERVICE" 2>/dev/null || true
rm -f "/etc/systemd/system/$SERVICE.service"
rm -f "/etc/systemd/journald.conf.d/$SERVICE.conf"
rmdir /etc/systemd/journald.conf.d 2>/dev/null || true   # only if now empty
systemctl daemon-reload 2>/dev/null || true
systemctl restart systemd-journald 2>/dev/null || true
echo -e "${GREEN}[OK] Service removed.${NC}"

# ── 3. Kill anything still holding port 5000 ─────────────────────
# gunicorn workers occasionally outlive the unit (a worker stuck in a scan
# subprocess). Left behind, they keep the old code running and hold the port
# against a future reinstall.
echo -e "\n${GREEN}[3/8] Checking for leftover processes on port 5000...${NC}"
LEFTOVER_PIDS="$(ss -tlnp 2>/dev/null | grep ':5000 ' | grep -oE 'pid=[0-9]+' | cut -d= -f2 | sort -u | tr '\n' ' ')"
if [ -n "$LEFTOVER_PIDS" ]; then
    echo -e "${YELLOW}[!] Killing leftover PIDs: $LEFTOVER_PIDS${NC}"
    # shellcheck disable=SC2086
    kill -9 $LEFTOVER_PIDS 2>/dev/null || true
else
    echo -e "${GREEN}[OK] Port 5000 is free.${NC}"
fi

# ── 4. nginx ─────────────────────────────────────────────────────
echo -e "\n${GREEN}[4/8] Removing the nginx configuration...${NC}"
rm -f "/etc/nginx/sites-enabled/$SERVICE" "$NGINX_VHOST"
rm -f "/etc/nginx/conf.d/$SERVICE-ratelimit.conf"
rm -f "/var/log/nginx/$SERVICE-access.log"* "/var/log/nginx/$SERVICE-error.log"*

# The installer deletes nginx's stock default site so it can't fight us for
# port 80. Put it back on the way out, otherwise nginx is left serving nothing
# at all and the next person to use this server is debugging a blank port 80.
if [ -f /etc/nginx/sites-available/default ] && [ ! -e /etc/nginx/sites-enabled/default ]; then
    ln -sf /etc/nginx/sites-available/default /etc/nginx/sites-enabled/default
    echo -e "${GREEN}    Restored nginx's default site.${NC}"
fi

if nginx -t 2>/dev/null; then
    systemctl reload nginx 2>/dev/null || systemctl restart nginx 2>/dev/null || true
    echo -e "${GREEN}[OK] nginx reloaded.${NC}"
else
    echo -e "${YELLOW}[!] nginx config test failed — leaving nginx as it is.${NC}"
    echo -e "${YELLOW}    Run 'nginx -t' to see why; it's unrelated to this panel now.${NC}"
fi

# ── 5. SSL certificate (opt-in) ──────────────────────────────────
echo -e "\n${GREEN}[5/8] SSL certificate...${NC}"
if [ "$DELETE_CERT" = "1" ] && [ -n "$DOMAIN" ]; then
    if command -v certbot >/dev/null 2>&1; then
        certbot delete --cert-name "$DOMAIN" --non-interactive 2>/dev/null \
            && echo -e "${GREEN}[OK] Certificate for $DOMAIN deleted.${NC}" \
            || echo -e "${YELLOW}[!] No certbot certificate named $DOMAIN to delete.${NC}"
    fi
elif [ -n "$DOMAIN" ] && [ -d "/etc/letsencrypt/live/$DOMAIN" ]; then
    echo -e "${GREEN}[OK] Keeping the certificate for $DOMAIN.${NC}"
    echo -e "${GREEN}    Remove it later with: certbot delete --cert-name $DOMAIN${NC}"
else
    echo -e "${GREEN}[OK] No certificate to handle.${NC}"
fi

# ── 6. Scan engine binaries ──────────────────────────────────────
echo -e "\n${GREEN}[6/8] Removing the scan engine...${NC}"
rm -f /usr/local/bin/v2raydar
# Only ever remove a *symlink* here. The installer creates this as a symlink to
# a sing-box it found in /usr/bin; if someone has since put a real binary at
# this path, it isn't ours to delete.
if [ -L /usr/local/bin/sing-box ]; then
    rm -f /usr/local/bin/sing-box
fi
echo -e "${GREEN}[OK] Engine removed (a system-wide sing-box, if any, is untouched).${NC}"

# ── 7. Project directory ─────────────────────────────────────────
echo -e "\n${GREEN}[7/8] Removing $PROJECT_DIR...${NC}"
if [ -d "$PROJECT_DIR" ]; then
    # Guard against a caller that somehow blanked PROJECT_DIR: `rm -rf /` is one
    # unset variable away, and this script runs as root.
    case "$PROJECT_DIR" in
        /home/v2ray-sub) rm -rf "$PROJECT_DIR" ;;
        *) echo -e "${RED}[X] Refusing to delete an unexpected path: '$PROJECT_DIR'${NC}" ;;
    esac
fi
if [ -d "$PROJECT_DIR" ]; then
    echo -e "${RED}[X] $PROJECT_DIR is still there — remove it by hand.${NC}"
else
    echo -e "${GREEN}[OK] Project directory removed.${NC}"
fi

# ── 8. Summary ───────────────────────────────────────────────────
echo -e "\n${GREEN}[8/8] Done.${NC}"
echo ""
echo -e "${GREEN}==========================================${NC}"
echo -e "${GREEN}  Uninstall complete${NC}"
echo -e "${GREEN}==========================================${NC}"
if [ -n "$BACKUP_FILE" ]; then
    echo ""
    echo -e "${YELLOW}Your data was saved to:${NC}"
    echo -e "${YELLOW}  $BACKUP_FILE${NC}"
    echo -e "${YELLOW}It contains the admin password hash and the machine-API token —${NC}"
    echo -e "${YELLOW}keep it private, or delete it once you're sure you don't need it.${NC}"
fi
echo ""
echo -e "${GREEN}Still installed (shared with the rest of the server, so left alone):${NC}"
echo -e "${GREEN}  nginx, redis-server, certbot, python3${NC}"
echo -e "${GREEN}Remove them yourself if this server has no other use for them.${NC}"
echo ""
