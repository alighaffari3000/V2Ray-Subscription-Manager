# Changelog

تمام تغییرهای قابل‌توجه این پروژه در این فایل ثبت می‌شوند.

قالب بر اساس [Keep a Changelog](https://keepachangelog.com/fa/1.1.0/)
و نسخه‌گذاری بر اساس [Semantic Versioning](https://semver.org/lang/fa/) است.

فرمت نسخه: `MAJOR.MINOR.PATCH`
- **MAJOR** — تغییرهای ناسازگار با نسخه‌های قبل.
- **MINOR** — افزودن قابلیت جدید به‌صورت سازگار با نسخه‌های قبل.
- **PATCH** — رفع باگ به‌صورت سازگار با نسخه‌های قبل.

## [Unreleased]

## [1.2.1] - 2026-07-21

### Fixed
- **خرابی UI پنل مدیریت روی موبایل.** در media query موبایل، نوار کناری با
  `inset-inline-end` مقداردهی شده بود که چون کل صفحه RTL است به لبه‌ی چپ resolve می‌شد،
  و ترنسفورمِ مخفی‌سازی (`translateX(100%)`) پنلِ بسته را به‌جای خارج‌کردن از صفحه، وسط
  صفحه می‌نشاند و روی محتوا می‌افتاد (در حالت عمودی محتوا پوشیده می‌شد و در حالت افقی
  نوار کناری وسط دیده می‌شد). اکنون نوار کناری با پراپرتی‌های فیزیکی (`right`) به لبه‌ی
  راست چسبیده و کاملاً از صفحه خارج می‌شود؛ عرض آن هم به `min(86vw, --sidebar-w)` و
  ارتفاعش به `100dvh` محدود شد.

## [1.2.0] - 2026-07-21

### Added
- **جایگزینی پیوسته‌ی کانفیگ‌ها هنگام پر بودن ظرفیت.** پیش از این، وقتی تعداد کانفیگ‌های
  active به `max_active_configs` می‌رسید، discovery کاملاً skip می‌شد و استخر تا مرگِ
  کانفیگ‌ها هیچ‌وقت تازه نمی‌شد. اکنون اگر `discovery_replace_when_full` روشن باشد (پیش‌فرض)،
  اسکن ادامه می‌یابد و بدترین کانفیگ‌های auto (پرتأخیرترین) با کاندیدهای جدیدِ به‌طور
  معنادار سریع‌تر (حداقل ۵۰ms بهتر) جایگزین می‌شوند. کانفیگ‌های دستی (`mode='manual'`)
  هرگز دست‌کاری نمی‌شوند و نرخ جابه‌جایی به `max_new_configs_per_scan` در هر اسکن محدود است.

### Fixed
- **گرسنگی همیشگی health check در scheduler.** چون `health_check_interval` مضرب
  `scan_interval` بود، health و discovery همیشه هم‌زمان موعدشان می‌رسید و discovery (که اول
  استارت می‌شد) هر بار قفل مشترک اسکن را می‌گرفت؛ در نتیجه health هیچ‌وقت اجرا نمی‌شد،
  کانفیگ‌های مرده prune نمی‌شدند و ظرفیت هیچ‌وقت خالی نمی‌شد (قفل‌شدن سیستم روی سقف).
  اکنون وقتی هر دو موعدشان می‌رسد health اولویت دارد، و تا وقتی اسکنی در حال اجراست هیچ
  تایمری «سوزانده» نمی‌شود.

### Changed
- **تسریع مرحله‌ی TCP pre-filter اسکن engine.** کف concurrency غربال از ۶۴ به ۲۵۶ رسید و
  timeout اتصالِ این مرحله به ۳ ثانیه (به‌جای ۵ ثانیه‌ی probe اصلی) محدود شد؛ چون
  endpointهای مرده هرکدام تا سررسید timeout بلاک می‌شوند، این دو تغییر زمانِ غربال روی
  صف‌های چندهزارتایی را چند برابر کاهش می‌دهد.

## [1.1.1] - 2026-07-21

### Fixed
- تشخیص‌پذیری اسکن worker: پیش از این، اسکن‌های `worker discovery`/`worker health` هیچ لاگ
  داخلی (اندازه‌ی batch، نتیجه‌ی TCP pre-filter و...) را جایی نشان نمی‌دادند؛ کانال progress
  به `None` ست شده بود و سطح لاگ روی `warn` قفل بود. اکنون اسپن‌های `info` ماژول probe در
  worker mode فعال‌اند و سرویس پایتون stderr موفق ورکر را هم در لاگ‌های خودش (و در نتیجه در
  journalctl) چاپ می‌کند.

## [1.1.0] - 2026-07-21

### Added
- نصب و راه‌اندازی خودکار Redis در `install.sh` برای اشتراک‌گذاری شمارنده‌ی محدودیت نرخ
  ورود بین workerهای gunicorn (`RATELIMIT_STORAGE_URI`). اگر Redis در دسترس نباشد، بدون
  متوقف‌کردن نصب، به حالت قبلی (شمارش جداگانه در هر worker) برمی‌گردد.

### Fixed
- شناسایی دستگاه در محدودیت تعداد دستگاه (`max_devices`) اکنون فقط بر اساس شبکه‌ی IP
  (پیشوند /24) است، نه ترکیب آن با User-Agent. قبلاً کاربری که با یک گوشی/یک اینترنت چند
  کلاینت مختلف (مثلاً v2rayNG و Hiddify) را امتحان می‌کرد به‌اشتباه چند دستگاه شمرده می‌شد.

## [1.0.0] - 2026-07-21

اولین نسخه‌ی رسمی و پایدار.

### Added
- نسخه‌گذاری معنایی (SemVer) با فایل `VERSION` به‌عنوان تنها منبع حقیقت.
- نمایش نسخه در پایان نصب/آپدیت: «Version X.Y.Z installed/updated successfully».
- مدیریت کاربران (user-management) و محدودیت تعداد دستگاه (device-limit).

[Unreleased]: https://github.com/alighaffari3000/V2Ray-Subscription-Manager/compare/v1.2.1...HEAD
[1.2.1]: https://github.com/alighaffari3000/V2Ray-Subscription-Manager/compare/v1.2.0...v1.2.1
[1.2.0]: https://github.com/alighaffari3000/V2Ray-Subscription-Manager/compare/v1.1.1...v1.2.0
[1.1.1]: https://github.com/alighaffari3000/V2Ray-Subscription-Manager/compare/v1.1.0...v1.1.1
[1.1.0]: https://github.com/alighaffari3000/V2Ray-Subscription-Manager/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/alighaffari3000/V2Ray-Subscription-Manager/releases/tag/v1.0.0
