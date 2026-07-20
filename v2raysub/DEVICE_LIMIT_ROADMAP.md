# نقشه‌راه فنی — اجرای محدودیت دستگاه (`max_devices` enforcement)

> سند مرجع این feature. هر فاز را یکی‌یکی انجام می‌دهیم و checkboxها را همین‌جا علامت می‌زنیم.
> وضعیت کلی: **✅ کامل شد** — همه‌ی فازها (۰ تا ۵) پیاده و تست شدند. کل suite سبز: **۶۷ تست** (۵۷ قبلی + ۱۰ جدید کلاس `TestDeviceLimit`).

---

## 🎯 هدف و تصمیم‌های قطعی‌شده (تغییر ندهیم مگر با توافق)

- «دستگاه» = `hash(User-Agent + شبکه‌ی IP با prefix /24)`.
- شمارش با **پنجره‌ی لغزان**: دستگاهی «فعال» است که `last_seen` آن در N روز اخیر باشد (پیش‌فرض ۷).
- دستگاه‌های **از قبل ثبت‌شده هیچ‌وقت بلاک نمی‌شوند**؛ فقط دستگاه *جدیدِ* بعد از پر شدن سقف.
- بلاک = سرو کانفیگ dummy با عنوان «سقف دستگاه پر شده است» (همان مکانیزم expired، بدون قطعی).
- `max_devices = 0` ➜ نامحدود (همین الان در schema هست).
- enforcement فقط برای مسیرهای **کاربر** (`users`). مسیر عمومی/`subscription_paths` درگیر نمی‌شود.

### چرا /24 و پنجره‌ی لغزان؟
- **نه سخت‌گیر:** یک گوشی روی دیتای همراه که IP‌اش مدام در یک /24 عوض می‌شود، همان یک دستگاه می‌ماند.
- **نه باز:** پخش لینک بین افراد در شبکه‌ها/شهرهای مختلف ➜ /24‌های متفاوت ➜ سقف می‌گیرد.
- **بدون نیاز به reset دستی:** اسلات دستگاهِ قدیمی بعد از پایان پنجره خودبه‌خود آزاد می‌شود.

---

## 🗂️ فازبندی

### فاز ۰ — schema و ثابت‌ها
- [x] جدول `user_devices` در `init_db()` (database.py)
- [x] `STATUS_DEVICE_LIMIT` و prefixهای شبکه در constants.py

جدول:

```sql
CREATE TABLE IF NOT EXISTS user_devices (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER NOT NULL,
    fingerprint   TEXT    NOT NULL,   -- hash(ua + ip/24)
    first_seen    TEXT    NOT NULL,   -- UTC، فرمت _TS_FMT
    last_seen     TEXT    NOT NULL,   -- UTC — محرک پنجره‌ی لغزان
    network       TEXT,               -- کلید /24 برای نمایش (مثل 5.201.130.0/24)
    last_ip       TEXT,               -- آخرین IP خام برای دیباگ
    user_agent    TEXT,               -- UA خام برای نمایش
    hits          INTEGER DEFAULT 0,
    UNIQUE(user_id, fingerprint)
);
CREATE INDEX IF NOT EXISTS idx_user_devices_user ON user_devices(user_id, last_seen);
```

> `UNIQUE(user_id, fingerprint)` هم دستگاه تکراری را می‌بندد، هم race دو fetch هم‌زمان از یک دستگاه را.
> ⚠️ به `ON DELETE CASCADE` تکیه نمی‌کنیم (پروژه `PRAGMA foreign_keys` روشن ندارد) — پاک‌سازی صریح در فاز ۳.

ثوابت: `STATUS_DEVICE_LIMIT = 'DEVICE_LIMIT'`، `DEVICE_NETWORK_PREFIX_V4 = 24`، `DEVICE_NETWORK_PREFIX_V6 = 48`.

**معیار پذیرش:** `init_db` بدون خطا، جدول ساخته شد، دیتای موجود دست‌نخورده.

---

### فاز ۱ — helper محاسبه‌ی fingerprint
- [x] `network_key(ip)` و `device_fingerprint(ip, user_agent)` در utils/misc.py

```python
def network_key(ip: str) -> str:
    # IPv4 -> "a.b.c.0/24" ؛ IPv6 -> "prefix::/48" ؛ در خطا/None -> "unknown"
def device_fingerprint(ip: str, user_agent: str) -> tuple[str, str]:
    net = network_key(ip)
    ua  = (user_agent or '').strip()
    fp  = sha256(f"{net}|{ua}".encode()).hexdigest()[:16]
    return fp, net
```

- از ماژول استاندارد `ipaddress` برای درست‌درآوردن /24 و /48.
- `ip=None` ➜ `network_key` مقدار `"unknown"`؛ در فاز ۲ این‌ها را نمی‌شماریم (fail-open).

**معیار پذیرش:** تست واحد — دو IP در یک /24 با UA یکسان ➜ fingerprint یکسان؛ /24 متفاوت ➜ متفاوت؛ IPv6 هم کار کند.

---

### فاز ۲ — نقطه‌ی enforcement در `resolve_user_request`
- [x] منطق شمارش/ثبت دستگاه، درست قبل از `return ('serve', user)` در user_service.py

```
max_dev = int(user['max_devices'] or 0)
if max_dev <= 0:               return ('serve', user)     # نامحدود
if ip is None:                 return ('serve', user)     # fail-open
fp, net = device_fingerprint(ip, user_agent)
window_cut = utcnow - device_window_days           # رشته‌ی _TS_FMT

dev = SELECT id FROM user_devices WHERE user_id=? AND fingerprint=?
if dev:                                                   # دستگاه شناخته‌شده
    UPDATE last_seen=now, last_ip, hits=hits+1
    return ('serve', user)                                # هیچ‌وقت بلاک نمی‌شود

active = SELECT COUNT(*) FROM user_devices
         WHERE user_id=? AND last_seen >= window_cut      # فقط اسلات‌های فعال
if active < max_dev:
    INSERT دستگاه جدید (first_seen=last_seen=now, hits=1) # با UNIQUE امن
    return ('serve', user)
else:
    return ('device_limit', user)                         # سقف پر — dummy
```

نکات دقیق:
- **مقایسه‌ی زمانی:** از همان `_utcnow`/`_parse`/`_TS_FMT` موجود. فرمت ISO مرتب‌شدنی است ➜ مقایسه‌ی رشته‌ای در SQL درست کار می‌کند.
- **race شمارش:** ممکن است لحظه‌ای `max+1` شود — با توجه به نادر بودن fetch، مثل تلورانس activation می‌پذیریم.
- **grace (اختیاری، پیش‌فرض خاموش):** `device_grace_hours`. چون /24 خودش سخت‌گیری موبایل را حل می‌کند، شروع با grace=0 تا حفره‌ی «ثبت انبوه در ساعت اول» باز نشود.

خروجی جدید `('device_limit', user)` به mapهای بالادست اضافه می‌شود.

**معیار پذیرش:** تست مستقیم سرویس (فاز ۵).

---

### فاز ۳ — سرو، لاگ، dummy، و پاک‌سازی
- [x] شاخه‌ی `'device_limit'` در routes/client.py ➜ dummy + لاگ `STATUS_DEVICE_LIMIT`
- [x] پارامتری‌کردن پیام remark در `generate_dummy_content` (subscription_service.py)
- [x] پاک‌سازی صریح دستگاه‌ها در `delete_user` و `reset_user` (user_service.py)
- [x] retention: حذف دستگاه‌های خیلی قدیمی (scheduler.py یا opportunistic)

**معیار پذیرش:** hit سقف‌رد‌شده کانفیگ dummy درست (طبق output_format) می‌گیرد و در تب لاگ‌ها با وضعیت `DEVICE_LIMIT` دیده می‌شود.

---

### فاز ۴ — API و UI
- [x] فیلدهای `active_device_count` و `max_devices` در پاسخ `GET /adminpanel/api/users`
- [x] `GET /adminpanel/api/users/<id>/devices` (لیست دستگاه‌ها + active/stale)
- [x] `POST /adminpanel/api/users/<id>/devices/reset` (آزادسازی همه اسلات‌ها)
- [x] `DELETE /adminpanel/api/users/<id>/devices/<device_id>` (اخراج یک دستگاه)
- [x] بج «۲ / ۳ دستگاه» + مودال دستگاه‌ها در admin.html
- [x] knobهای سراسری `device_window_days` (۷) و `device_grace_hours` (۰) در تب تنظیمات

**معیار پذیرش:** verify زنده — بج درست، مودال درست، ریست اسلات‌ها را آزاد می‌کند.

---

### فاز ۵ — تست (`TestDeviceLimit` در test_integration.py)
- [x] زیر سقف ➜ کانفیگ واقعی
- [x] دستگاه N+1‌اُم (network متفاوت) ➜ dummy + لاگ `DEVICE_LIMIT`
- [x] همان دستگاه، IP متفاوت در همان /24 ➜ دوباره شمرده نمی‌شود، سرو واقعی
- [x] دستگاه شناخته‌شده حتی وقتی سقف پر است ➜ هیچ‌وقت بلاک نمی‌شود
- [x] پنجره‌ی لغزان: با backdate‌کردن `last_seen` اسلات آزاد می‌شود
- [x] `max_devices=0` ➜ نامحدود
- [x] reset devices ➜ اسلات‌ها آزاد
- [x] احترام به `output_format=plain` در dummy

**معیار پذیرش:** کل suite سبز، بدون regression روی ۵۵ تست موجود.

---

## 📌 فایل‌های درگیر (نقشه‌ی سریع)

| فایل | نقش |
| --- | --- |
| `database.py` | جدول `user_devices` |
| `utils/constants.py` | `STATUS_DEVICE_LIMIT`، prefixها |
| `utils/misc.py` | `network_key` + `device_fingerprint` |
| `services/user_service.py` | **قلب enforcement** در `resolve_user_request` + پاک‌سازی در delete/reset |
| `services/subscription_service.py` | dummy پارامتری |
| `routes/client.py` | شاخه‌ی `device_limit` + لاگ |
| `routes/admin_api.py` | endpointهای devices + فیلدهای شمارش |
| `templates/admin.html` | بج + مودال دستگاه‌ها + knobها |
| `services/scheduler.py` | retention cleanup |
| `test_integration.py` | `TestDeviceLimit` |

---

## ⚠️ ریسک‌ها و tradeoffهای پذیرفته‌شده
- دو نفر روی دقیقاً یک /24 با اپ یکسان = یک دستگاه (سهل‌گیری آگاهانه).
- race نادر ➜ لحظه‌ای `max+1` (تلورانس‌شده).
- `ip=None` ➜ fail-open (کاربر واقعی قربانی نمی‌شود).
