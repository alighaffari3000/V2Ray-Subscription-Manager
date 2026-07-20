# Changelog

تمام تغییرهای قابل‌توجه این پروژه در این فایل ثبت می‌شوند.

قالب بر اساس [Keep a Changelog](https://keepachangelog.com/fa/1.1.0/)
و نسخه‌گذاری بر اساس [Semantic Versioning](https://semver.org/lang/fa/) است.

فرمت نسخه: `MAJOR.MINOR.PATCH`
- **MAJOR** — تغییرهای ناسازگار با نسخه‌های قبل.
- **MINOR** — افزودن قابلیت جدید به‌صورت سازگار با نسخه‌های قبل.
- **PATCH** — رفع باگ به‌صورت سازگار با نسخه‌های قبل.

## [Unreleased]

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

[Unreleased]: https://github.com/alighaffari3000/V2Ray-Subscription-Manager/compare/v1.1.1...HEAD
[1.1.1]: https://github.com/alighaffari3000/V2Ray-Subscription-Manager/compare/v1.1.0...v1.1.1
[1.1.0]: https://github.com/alighaffari3000/V2Ray-Subscription-Manager/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/alighaffari3000/V2Ray-Subscription-Manager/releases/tag/v1.0.0
