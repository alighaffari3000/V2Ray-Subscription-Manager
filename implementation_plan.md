# برنامه پیاده‌سازی اصلاحات پروژه مدیریت سابسکریپشن V2Ray

هدف از این برنامه، برطرف کردن باگ‌ها، مشکلات کارایی و ساختاری شناسایی‌شده در پروژه مدیریت سابسکریپشن V2Ray است تا برنامه برای استقرار امن و بدون نقص در محیط واقعی (Production) آماده شود.

---

## User Review Required

> [!WARNING]
> **۱. معافیت مسیرهای ادمین از Rate Limiter:**  
> نرخ محدودکننده (Rate Limiter) همچنان روی مسیرهای سابسکریپشن کلاینت‌ها (`/sub/<path>`) با محدودیت ۲۲۰ درخواست در روز و ۵۰ درخواست در ساعت اعمال خواهد شد تا از سوءاستفاده جلوگیری شود. مسیرهای ادمین (`/adminpanel/...`) کاملاً معاف می‌شوند تا ادمین به صورت ناخواسته مسدود نشود.
> 
> **۲. پاک‌سازی کدهای مرده:**  
> کدهای غیرقابل استفاده در پوشه `utils/` که هیچ ایمپورتی ندارند حذف خواهند شد تا ساختار پروژه سبک‌تر و خواناتر شود.

---

## Open Questions

> [!NOTE]
> هیچ سوال مبهمی برای پیاده‌سازی این تغییرات وجود ندارد. تمام کدها در محیط تست بررسی شده و آماده اصلاح هستند.

---

## Proposed Changes

### بخش آمار و لاگ‌ها (statistics_service)

در این بخش، تمام کوئری‌های مقایسه تاریخ برای اصلاح باگ منطقه زمانی به‌روزرسانی شده و محاسبات سنگین کلاینت‌ها مستقیماً به سمت دیتابیس هدایت می‌شوند.

#### [MODIFY] [statistics_service.py](file:///F:/Telegram%20Bots/v2ray-sub/services/statistics_service.py)
* اصلاح توابع `get_stats` و `get_usage_stats` و `get_chart_data` جهت استفاده از `date(accessed_at, 'localtime')` و `strftime('%H', accessed_at, 'localtime')`.
* جایگزینی حلقه پایتونی پردازش User-Agent با کوئری گروه‌بندی کارآمد SQLite به کمک دستور `CASE WHEN`.

---

### بخش سرویس کانفیگ (config_service)

رفع خطای احتمالی زمان اجرا هنگام پردازش کانفیگ‌های VMess با فرمت بیس۶۴ نامعتبر.

#### [MODIFY] [config_service.py](file:///F:/Telegram%20Bots/v2ray-sub/services/config_service.py)
* انتقال خطوط مربوط به حذف کلید `ps` به داخل بلوک شرطی `if decoded:` در تابع `get_config_identity`.

---

### بخش تنظیمات و کنترلرها (admin_api & app_factory)

اصلاح رفتار محدودکننده نرخ و رفع ناهماهنگی در پارامتر مرتب‌سازی کانفیگ‌ها.

#### [MODIFY] [app_factory.py](file:///F:/Telegram%20Bots/v2ray-sub/app_factory.py)
* تغییر نحوه نمونه‌سازی `Limiter` و معاف کردن دوBlueprintِ `admin_pages_bp` و `admin_api_bp` به وسیله متد `limiter.exempt()`.

#### [MODIFY] [routes/admin_api.py](file:///F:/Telegram%20Bots/v2ray-sub/routes/admin_api.py)
* اصلاح استخراج ترتیب مرتب‌سازی در تابع `set_sort_order` به طوری که هر دو پارامتر `sort_order` و `order` را در درخواست‌های JSON پشتیبانی کند.

#### [MODIFY] [config.py](file:///F:/Telegram%20Bots/v2ray-sub/config.py)
* اضافه کردن یک اخطار کوچک در صورت عدم وجود `SECRET_KEY` در متغیرهای محیطی جهت آگاه‌سازی توسعه‌دهنده در محیط‌های لوکال.

---

### پاک‌سازی فایل‌های بلااستفاده (Dead Code Cleanup)

حذف فایل‌های کمکی که پیشتر کپی شده ولی هیچ وابستگی به آن‌ها وجود ندارد.

#### [DELETE] [config_parser.py](file:///F:/Telegram%20Bots/v2ray-sub/utils/config_parser.py)
#### [DELETE] [misc.py](file:///F:/Telegram%20Bots/v2ray-sub/utils/misc.py)

---

## Verification Plan

### Automated Tests
* اجرای مجدد تست‌های یکپارچه‌سازی جهت اطمینان از عدم شکستن عملکردهای فعلی:
  ```powershell
  python -m unittest test_integration.py
  ```
* اجرای کامپایل پایتون روی کل فایل‌ها برای اطمینان از عدم وجود خطای نگارشی (Syntax Error):
  ```powershell
  python -m py_compile app.py app_factory.py config.py database.py routes/*.py services/*.py utils/*.py
  ```

### Manual Verification
* ورود به پنل مدیریت و بررسی بارگذاری سریع آمار کلاینت‌ها در داشبورد.
* بررسی فعال/غیرفعال کردن کانفیگ‌ها چندین بار متوالی برای اطمینان از معافیت ادمین از Rate Limiter.
