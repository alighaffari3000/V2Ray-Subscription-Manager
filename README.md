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

---

## 🏗️ How it's built / معماری

```text
├── v2raysub/          # The Flask panel — see v2raysub/README.md for details
│                      # پنل تحت وب Flask — جزئیات در v2raysub/README.md
│   ├── routes/        # HTTP endpoints (client subscription + admin panel/API)
│   ├── services/      # Business logic (automation, configs, paths, stats)
│   ├── utils/         # Parsers and helpers
│   └── install.sh     # The automated installer / اسکریپت نصب خودکار
│
└── V2RayDAR-main/     # Vendored Rust scan engine (third-party, see Credits)
                       # موتور اسکن Rust (پروژه‌ی جانبی — بخش Credits را ببینید)
```

The panel runs under gunicorn behind Nginx and stores everything in a single SQLite file. A background scheduler triggers scans on the intervals you configure; each scan runs the V2RayDAR engine as a subprocess, exchanging JSON over stdin/stdout. The engine does the actual network probing through sing-box.

پنل با gunicorn پشت Nginx اجرا می‌شود و همه‌چیز را در یک فایل SQLite نگه می‌دارد. یک زمان‌بند پس‌زمینه طبق بازه‌های تنظیم‌شده اسکن‌ها را اجرا می‌کند و هر اسکن، موتور V2RayDAR را به‌صورت یک پروسه‌ی جدا صدا می‌زند و داده‌ها را با JSON از طریق ورودی/خروجی استاندارد رد و بدل می‌کند.

For manual (non-scripted) installation, panel internals, and the full file map, see **[v2raysub/README.md](v2raysub/README.md)**.

برای نصب دستی، جزئیات داخلی پنل و نقشه‌ی کامل فایل‌ها، به **[v2raysub/README.md](v2raysub/README.md)** مراجعه کنید.

---

## 🔒 Security / امنیت

- The admin password is stored **hashed** (Werkzeug scrypt/pbkdf2), never in plain text. The installer hashes it for you. / رمز ادمین به صورت **هش‌شده** ذخیره می‌شود، نه متن ساده. اسکریپت نصب خودش این کار را انجام می‌دهد.
- `.env` and `database.db` are git-ignored and never committed. / فایل‌های `.env` و `database.db` در گیت نادیده گرفته می‌شوند.
- Login is rate-limited against brute-force; session cookies are `HttpOnly` + `SameSite=Lax`, and `Secure` once SSL is enabled. / صفحه‌ی ورود در برابر حملات brute-force محدود شده و کوکی‌های سشن با `HttpOnly` و `SameSite=Lax` (و پس از فعال شدن SSL با `Secure`) تنظیم می‌شوند.

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
