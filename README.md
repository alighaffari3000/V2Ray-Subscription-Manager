# V2Ray Subscription Manager 🚀

A self-hosted V2Ray/Xray subscription panel that **finds working configs by itself**. It fetches configs from public sources, tests each one through your server's real network connection, keeps only the ones that actually work, and republishes them at your own subscription link.

یک پنل خودمیزبان مدیریت سابسکریپشن V2Ray که **کانفیگ‌های سالم را خودش پیدا می‌کند**: از منابع عمومی کانفیگ می‌گیرد، تک‌تک آن‌ها را از طریق شبکه‌ی واقعی سرور شما تست می‌کند، فقط موارد سالم را نگه می‌دارد و روی لینک سابسکریپشن اختصاصی شما منتشرشان می‌کند.

---

## ✨ What it does / این پروژه چه می‌کند

| | |
|---|---|
| 🔍 **Auto-discovery** | Periodically fetches configs from subscription sources you define, probes each one, and imports the fastest working ones — ranked by latency. |
| ❤️ **Health checks** | Re-tests your active configs on a schedule. Dead configs are automatically disabled or deleted based on your policy. |
| 🔗 **Dynamic paths** | Change your subscription path any time from the panel. Create extra paths, disable one instantly (returns `404`), or generate a random 16-char path. |
| 🏷️ **Smart remarks** | Output names are re-indexed cleanly (`1`, `2`, `3`) while country flags (`🇩🇪`, `🇺🇸`) are preserved — all in-memory, your database stays untouched. |
| 📊 **Stats dashboard** | Downloads, unique visitors, protocol breakdown, and client apps (v2rayNG / Nekobox / Clash / Shadowrocket / Sing-box) detected via User-Agent. |
| 🌗 **Modern panel** | Responsive, dark/light mode, works well on mobile. |

**پشتیبانی از پروتکل‌ها:** VMess · VLESS · Trojan · Shadowsocks · Hysteria2

---

## 🚀 Quick Install / نصب سریع

On a fresh **Ubuntu/Debian** VPS, as root — one line:

روی یک VPS تازه‌ی اوبونتو یا دبیان، با کاربر root — فقط یک خط:

```bash
bash <(curl -Ls https://raw.githubusercontent.com/alighaffari3000/V2Ray-Subscription-Manager/master/v2raysub/install.sh)
```

<details>
<summary>Alternative: clone first / روش جایگزین: ابتدا clone کنید</summary>

```bash
git clone https://github.com/alighaffari3000/V2Ray-Subscription-Manager.git
cd V2Ray-Subscription-Manager
sudo bash v2raysub/install.sh
```
</details>

The installer is interactive — it asks for your domain, port, and admin credentials, then handles everything else:

اسکریپت نصب به صورت تعاملی دامنه، پورت و اطلاعات ورود ادمین را می‌پرسد و بقیه‌ی کارها را خودش انجام می‌دهد:

- System packages, Python venv, and dependencies / پکیج‌های سیستمی، محیط مجازی پایتون و پیش‌نیازها
- Downloads the **prebuilt** V2RayDAR scan engine from GitHub Releases; only compiles from source (installing Rust automatically) if the download fails / دانلود باینری **از پیش‌ساخته‌ی** موتور اسکن V2RayDAR از GitHub Releases؛ فقط در صورت شکستِ دانلود، از سورس کامپایل می‌کند (Rust را خودش نصب می‌کند)
- Installs the sing-box core used for probing / نصب هسته‌ی sing-box برای تست کانفیگ‌ها
- Nginx reverse proxy + systemd service / پروکسی معکوس Nginx و سرویس systemd
- Free SSL via Certbot (optional) / گواهی SSL رایگان با Certbot (اختیاری)

When it finishes you get your panel URL (`https://yourdomain.com/adminpanel`) and your subscription link (`https://yourdomain.com/sub/freeconfigs`).

### Requirements / پیش‌نیازها

- Ubuntu / Debian VPS with root access / سرور مجازی اوبونتو یا دبیان با دسترسی root
- A domain pointing to the server (needed for SSL) / یک دامنه که به سرور اشاره کند (برای SSL لازم است)
- RAM: any size is fine when the prebuilt engine binary downloads successfully (the normal case). **2 GB+ (or swap) is only needed if the installer has to compile the engine from source** — e.g. non-x86_64 servers or very old distros. / رم: اگر باینری از پیش‌ساخته‌ی موتور دانلود شود (حالت عادی) هر مقداری کافی است. **حداقل ۲ گیگ رم (یا swap) فقط وقتی لازم است که نصاب مجبور به کامپایل از سورس شود** — مثلاً سرورهای غیر x86_64 یا توزیع‌های خیلی قدیمی.

### Updating / به‌روزرسانی

Re-run the same install command. It detects the existing installation and updates the code, dependencies, and engine in place — your domain, port, SSL certificate, admin login, and database are all kept.

همان دستور نصب را دوباره اجرا کنید. نصب موجود را تشخیص می‌دهد و کد، پیش‌نیازها و موتور را به‌روز می‌کند — دامنه، پورت، گواهی SSL، ورود ادمین و دیتابیس دست‌نخورده می‌مانند.

---

## 🗑️ Uninstall / حذف

To remove the panel from a server — one line, same style as the install:

برای حذف کامل پنل از سرور — یک خط، با همان سبک نصب:

```bash
bash <(curl -Ls https://raw.githubusercontent.com/alighaffari3000/V2Ray-Subscription-Manager/master/v2raysub/uninstall.sh)
```

It asks for confirmation, then removes the systemd service, the project directory (`/home/v2ray-sub`), the nginx vhost and rate-limit zone, the nginx logs, the journald cap, and the scan engine binary.

تأیید می‌گیرد، سپس سرویس systemd، پوشه‌ی پروژه (`/home/v2ray-sub`)، تنظیمات nginx، لاگ‌ها و باینری موتور اسکن را حذف می‌کند.

**Your database and `.env` are copied to `/root/v2ray-sub-data-<date>.tar.gz` before anything is deleted** — if that copy fails, nothing is removed at all. Shared packages (nginx, redis, certbot, python3) are always kept, since other services on the server may need them; so is the SSL certificate, because re-issuing counts against Let's Encrypt's rate limits.

**دیتابیس و فایل `.env` قبل از هر حذفی در `/root/v2ray-sub-data-<تاریخ>.tar.gz` ذخیره می‌شوند** — اگر این کپی شکست بخورد، هیچ‌چیز حذف نمی‌شود. پکیج‌های مشترک (nginx، redis، certbot، python3) و گواهی SSL همیشه نگه داشته می‌شوند.

| Option | Effect / اثر |
|---|---|
| `--yes` | Skip the confirmation prompt (for scripts) / بدون پرسش تأیید |
| `--purge` | Delete the database too, with no backup copy / دیتابیس هم بدون هیچ نسخه‌ی پشتیبانی حذف شود |
| `--delete-cert` | Also delete the Let's Encrypt certificate / گواهی SSL هم حذف شود |

---

## 🏗️ How it's built / معماری

```text
├── v2raysub/          # The Flask panel — see v2raysub/README.md for details
│                      # پنل تحت وب Flask — جزئیات در v2raysub/README.md
│   ├── routes/        # HTTP endpoints (client subscription + admin panel/API)
│   ├── services/      # Business logic (automation, configs, paths, stats)
│   ├── utils/         # Parsers and helpers
│   ├── install.sh     # The automated installer / اسکریپت نصب خودکار
│   └── uninstall.sh   # Removes everything the installer created / حذف کامل از سرور
│
└── V2RayDAR-main/     # Vendored Rust scan engine (third-party, see Credits)
                       # موتور اسکن Rust (پروژه‌ی جانبی — بخش Credits را ببینید)
```

The panel runs under gunicorn behind Nginx and stores everything in a single SQLite file. A background scheduler triggers scans on the intervals you configure; each scan runs the V2RayDAR engine as a subprocess, exchanging JSON over stdin/stdout. The engine does the actual network probing through sing-box.

پنل با gunicorn پشت Nginx اجرا می‌شود و همه‌چیز را در یک فایل SQLite نگه می‌دارد. یک زمان‌بند پس‌زمینه طبق بازه‌های تنظیم‌شده اسکن‌ها را اجرا می‌کند و هر اسکن، موتور V2RayDAR را به‌صورت یک پروسه‌ی جدا صدا می‌زند و داده‌ها را با JSON از طریق ورودی/خروجی استاندارد رد و بدل می‌کند.

For manual (non-scripted) installation, panel internals, and the full file map, see **[v2raysub/README.md](v2raysub/README.md)**.

برای نصب دستی، جزئیات داخلی پنل و نقشه‌ی کامل فایل‌ها، به **[v2raysub/README.md](v2raysub/README.md)** مراجعه کنید.

---

## 🔌 Machine API / API ماشینی

The panel exposes an optional token-authenticated REST API so an external client — a Telegram sales bot, your own billing system, a script — can create and manage subscriptions without touching the web UI.

پنل یک REST API اختیاری با احراز هویت توکنی دارد تا یک کلاینت بیرونی (بات فروش تلگرام، سیستم صورت‌حساب خودت، یا یک اسکریپت) بتواند بدون ورود به پنل، اشتراک بسازد و مدیریت کند.

**It is disabled by default.** Generate a token from **Settings → 🤖 API بات فروش** in the panel; until you do, every endpoint returns `503`. Send it as `Authorization: Bearer <token>`.

**به‌صورت پیش‌فرض غیرفعال است.** از تب **تنظیمات → 🤖 API بات فروش** یک توکن بساز؛ تا آن موقع همه‌ی endpointها `503` برمی‌گردانند.

```bash
# Create a 30-day subscription for up to 2 devices
curl -X POST https://yourdomain.com/api/v1/subs \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"name":"customer-42","duration_days":30,"max_devices":2}'
# -> {"success":true,"subscription":{"id":7,"sub_url":"https://yourdomain.com/sub/aB3xK9..."}}
```

| Endpoint | Purpose |
|---|---|
| `GET /api/v1/health` | Verify the token; returns the panel version |
| `GET /api/v1/subs` | List every subscription (reconcile your own records) |
| `POST /api/v1/subs` | Create one → returns its `sub_url` |
| `GET /api/v1/subs/{id}` | State: activation, expiry, remaining time, active devices |
| `POST /api/v1/subs/{id}/extend` | **Renew** — add `{"days":N}` |
| `PATCH /api/v1/subs/{id}` | Edit `name` / `duration_days` / `max_devices` / `note` / `path` |
| `POST /api/v1/subs/{id}/pause` · `/resume` · `/reset` · `/toggle` | State transitions |
| `GET /api/v1/subs/{id}/devices` | Registered devices, the cap, and the active count |
| `POST /api/v1/subs/{id}/devices/reset` | Free every device slot |
| `DELETE /api/v1/subs/{id}/devices/{device_id}` | Kick one device |
| `DELETE /api/v1/subs/{id}` | Delete the subscription |

Errors carry a machine-readable `error` code — never parse the human `message`:

| Code | HTTP | Meaning |
|---|---|---|
| `api_disabled` | 503 | No token configured yet |
| `unauthorized` | 401 | Missing or wrong token |
| `invalid_request` | 400 | A field failed validation (the offending one is in `field`) |
| `path_taken` | 409 | That `path` already exists — the response carries the **existing** subscription |
| `not_found` / `device_not_found` | 404 | No such subscription / device |
| `internal_error` | 500 | The operation failed server-side; safe to retry |

Supply your own `path` (an order id, say) to make creates **retry-safe**: a duplicate returns `409` with the subscription that already exists, so a retried payment webhook recovers the original instead of creating a second one. Types are strict — integer fields reject strings, floats and booleans; `enabled` must be a real `true`/`false` — so a malformed request fails loudly rather than being silently coerced.

**Use `/extend` for renewals, not `PATCH duration_days`.** `PATCH` *sets* the total and shifts the expiry by the difference, so renewing a subscription that lapsed 10 days ago by 30 would land only 20 days out. `/extend` restarts an expired subscription from now, so nobody loses days they paid for.

**برای تمدید از `/extend` استفاده کن، نه `PATCH duration_days`.** حالت `PATCH` مقدار کل را *تنظیم* می‌کند و انقضا را به اندازه‌ی تفاوت جابجا می‌کند؛ پس تمدیدِ ۳۰ روزه‌ی اشتراکی که ۱۰ روز پیش منقضی شده، فقط ۲۰ روز اعتبار می‌دهد. `/extend` اشتراک منقضی را از همین لحظه شروع می‌کند.

Two things worth knowing / دو نکته‌ی مهم:

- **The clock starts on first connection**, not at creation — a subscription created today but first used next week still gets its full duration. / **شمارش مدت از اولین اتصال شروع می‌شود**، نه از لحظه‌ی ساخت.
- If your client reaches the panel on an address customers don't use (e.g. `127.0.0.1:5000`), set **آدرس عمومی پنل** in the same settings card, otherwise generated `sub_url`s point at that internal address. The installer pins this automatically when the panel runs on a non-standard port, because nginx forwards `Host` without the port. / اگر کلاینت از آدرسی غیر از دامنه‌ی عمومی وصل می‌شود، «آدرس عمومی پنل» را در همان کارت تنظیمات پر کن. نصاب این مقدار را وقتی پنل روی پورت غیراستاندارد است خودش تنظیم می‌کند.
- Pausing freezes the clock, and extending a paused subscription adds to the frozen remainder — resume still credits the full paused span. / توقف، شمارش را متوقف می‌کند و تمدیدِ اشتراک متوقف به همان باقی‌مانده‌ی منجمد اضافه می‌شود.

---

## 🔒 Security / امنیت

- The admin password is stored **hashed** (Werkzeug scrypt/pbkdf2), never in plain text. The installer hashes it for you. / رمز ادمین به صورت **هش‌شده** ذخیره می‌شود، نه متن ساده. اسکریپت نصب خودش این کار را انجام می‌دهد.
- `.env` and `database.db` are git-ignored and never committed. / فایل‌های `.env` و `database.db` در گیت نادیده گرفته می‌شوند.
- Login is rate-limited against brute-force; session cookies are `HttpOnly` + `SameSite=Lax`, and `Secure` once SSL is enabled. / صفحه‌ی ورود در برابر حملات brute-force محدود شده و کوکی‌های سشن با `HttpOnly` و `SameSite=Lax` (و پس از فعال شدن SSL با `Secure`) تنظیم می‌شوند.
- The **Machine API token** grants full control over subscriptions, so it is treated as a secret: blanked out of standard backups (which are unencrypted and can be auto-delivered to Telegram), and preserved on restore rather than overwritten by a stale value. Keep it off-panel too, and regenerate it if it ever leaks — that instantly invalidates the old one. / **توکن API ماشینی** کنترل کامل اشتراک‌ها را می‌دهد، پس مثل یک راز رفتار می‌شود: از بکاپ‌های استاندارد حذف می‌شود و موقع بازیابی، مقدار محلی حفظ می‌شود. اگر لو رفت، دوباره تولیدش کن تا توکن قبلی فوراً باطل شود.

If you upgrade an old install that had a plain-text password in `.env`, re-run the installer or replace the value with a hash — see [v2raysub/README.md](v2raysub/README.md#3-setup-configuration).

---

## 🙏 Credits / منابع

The scan engine in `V2RayDAR-main/` is **[V2RayDAR](https://github.com/411A/V2RayDAR)** by [@411A](https://github.com/411A), licensed under **AGPL-3.0**. It is vendored here so the installer can build it; all credit for the engine goes to its authors. Please review its license terms before redistributing this project.

موتور اسکن موجود در پوشه‌ی `V2RayDAR-main/` پروژه‌ی **[V2RayDAR](https://github.com/411A/V2RayDAR)** ساخته‌ی [@411A](https://github.com/411A) با لایسنس **AGPL-3.0** است و صرفاً برای اینکه اسکریپت نصب بتواند آن را کامپایل کند اینجا قرار داده شده. پیش از بازتوزیع این پروژه، لطفاً شرایط لایسنس آن را مطالعه کنید.

Probing is performed by the [sing-box](https://sing-box.sagernet.org/) core.

---

## ⚖️ Disclaimer / سلب مسئولیت

This project only manages and tests subscription links you choose to add — it does not provide any servers or configs. You are responsible for complying with the laws and regulations that apply to you.

این پروژه صرفاً لینک‌های سابسکریپشنی را که خودتان اضافه می‌کنید مدیریت و تست می‌کند و هیچ سرور یا کانفیگی ارائه نمی‌دهد. رعایت قوانین و مقررات مربوطه بر عهده‌ی خود شماست.
