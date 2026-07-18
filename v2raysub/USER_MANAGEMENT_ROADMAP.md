# نقشه راه — مدیریت کاربران و بازطراحی تب‌محور پنل

> سند مرجع این feature. هر فاز را یکی‌یکی انجام می‌دهیم و checkboxها را همین‌جا علامت می‌زنیم.
> وضعیت کلی: **در حال انجام** — فاز جاری: فاز ۶ (تست‌ها). فازهای ۰ تا ۵ تمام شدند.
>
> **شاخه‌ی `ui-redesign`:** بازطراحی کامل ظاهر پنل (سایدبار کناری + تم تیره‌ی مدرن + فونت Vazirmatn) + UI تب کاربران (فاز ۵) روی این شاخه. `master` دست‌نخورده (طرح تب‌بالای فاز ۴). کامیت‌ها: baseline `94c36ae`، redesign `b560a21`، users-tab (این commit).

---

## 🎯 هدف

امکان مدیریت کاربران در پنل ادمین: ساخت کاربر با مدت اشتراک (روز)، لینک اشتراک یکتای قابل‌ویرایش برای هر کاربر،
و انقضای خودکار. همه‌ی کاربرانِ فعال از **همان استخر سراسری کانفیگ‌های فعال** تغذیه می‌شوند (aggregator است، سهمیه‌ی
مصرف/پهنای‌باند ندارد). وقتی اشتراک کاربر منقضی/متوقف/غیرفعال شود، به‌جای لیست واقعی فقط یک **کانفیگ ساختگی** با
عنوان «اشتراک شما به پایان رسیده است» به کلاینت برمی‌گردد.

در کنارش، پنل شلوغ فعلی (۲۴۰۰+ خط، تک‌اسکرول) به یک ساختار **۶‌تبی** بازچینش می‌شود.

---

## ✅ تصمیم‌های قطعی‌شده (تغییر ندهیم مگر با توافق)

**رفتار کاربر و انقضا:**
- **فعال‌سازی در اولین استفاده (Activation on First Use):** موقع ساخت `activated_at=NULL, expire_at=NULL`.
  اولین باری که کلاینت لینک را می‌کشد → `activated_at=now`, `expire_at=now+duration_days`. فعال‌سازی **اتمیک**
  (`UPDATE ... WHERE activated_at IS NULL`) برای جلوگیری از race.
- **تمدید مدت:** اگر هنوز فعال نشده فقط `duration_days` عوض می‌شود؛ اگر فعال شده `expire_at += delta`.
- **Pause/Resume منصفانه:** Pause → `paused_at=now`. Resume → `expire_at += (now - paused_at)` و `paused_at=NULL`.
- **`status` فقط نیتِ ادمین است:** مقادیر `ACTIVE / PAUSED / DISABLED`. حالت **`EXPIRED` محاسبه‌ای** است
  (`expire_at IS NOT NULL AND expire_at < now`) و ذخیره نمی‌شود (تک‌منبعِ حقیقت).

**Path:**
- ثابت جدا `USER_PATH_REGEX = r'^[A-Za-z0-9_-]{8,64}$'` (زیرخط و خط‌تیره مجاز، حداقل ۸ کاراکتر) —
  متمایز از `PATH_REGEX` فعلی مسیرهای سراسری.
- یکتایی path موقع ساخت/ویرایش روی **هر دو** جدول `users` و `subscription_paths` چک می‌شود.
- auto-generate به‌صورت پیش‌فرض، ولی ادمین می‌تواند path سفارشی بدهد.

**کانفیگ ساختگی (منقضی):**
- از همان منطق `output_format` (base64/plain) استفاده می‌کند — هاردکد نمی‌شود.
- لینک نمونه: `trojan://expired-user@127.0.0.1:443#⚠️ اشتراک شما به پایان رسیده است ⚠️`

**لینک عمومی فعلی (`/sub/freeconfigs`) — جایگزینی نرم:**
- جدول `subscription_paths` در پس‌زمینه **زنده می‌ماند** و به‌عنوان fallback در روت کار می‌کند تا کاربران فعلی قطع نشوند.
- UI مدیریت مسیرها از پنل **حذف** می‌شود.
- freeconfigs مثل یک کاربرِ عمومی رفتار می‌کند؛ فعلاً حذف نمی‌شود ولی بعداً به‌راحتی (پاک‌کردن یک row) قابل‌حذف است.

**فرانت — ۶ تب:** داشبورد / کاربران / کانفیگ‌ها / اسکن خودکار / تنظیمات / لاگ‌ها.
- الگوی تب موجود (`switchAutomationTab` در `admin.html`) به `switchTab` سطح‌بالا تعمیم داده می‌شود؛ زیرتب‌های اسکن خودکار تودرتو می‌مانند.
- تب فعال در `localStorage` ذخیره می‌شود تا refresh ریست نکند.

**`max_devices`:** فقط در schema قرار می‌گیرد؛ در این نسخه enforce نمی‌شود.

---

## 🗂️ فازبندی

هر فاز مستقل و قابل‌تست است. بعد از هر فاز verify می‌کنیم، بعد می‌رویم فاز بعد.

### فاز ۰ — پایه‌ها: schema و ثابت‌ها ✅
- [x] جدول `users` در `init_db()` ([database.py](database.py)) با کل فیلدهای توافق‌شده
- [x] `USER_PATH_REGEX` و statusهای جدید لاگ (`STATUS_EXPIRED`, `STATUS_USER_DISABLED`, `STATUS_USER_PAUSED`) + ثابت‌های `USER_STATUS_*` و `USER_PATH_LENGTH` در [constants.py](utils/constants.py)
- [x] helperهای اولیه‌ی دیتابیس (در صورت نیاز) — فعلاً لازم نشد؛ CRUD در فاز ۱ داخل `user_service.py`
- **معیار پذیرش:** ✅ `init_db` بدون خطا اجرا شد، جدول `users` با ۱۶ ستون و defaultهای درست ساخته شد، دیتای واقعی (`configs`/`subscription_paths`) دست‌نخورده.

### فاز ۱ — لایه سرویس: `services/user_service.py` ✅
- [x] `add_user(name, duration_days, custom_path=None, note, max_devices)` + auto-generate path + یکتایی دوجدولی + `validate_user_path`
- [x] `get_all_users()` / `get_user()` با محاسبه‌ی وضعیت مؤثر (EXPIRED) و زمان باقیمانده (فیلدهای `_local` برای نمایش)
- [x] `update_user(...)` با منطق تمدید (فعال‌شده → shift؛ فعال‌نشده → فقط عدد)
- [x] `pause_user` / `resume_user` (حفظ زمان با `paused_at`) / `reset_user` / `delete_user` / `set_user_enabled` (DISABLED)
- [x] `resolve_user_request(sub_path, ip, user_agent)`: فعال‌سازی اتمیک + آپدیت last_seen/ip/ua + تصمیم serve/dummy/disabled/None
- **معیار پذیرش:** ✅ اسکریپت تست مستقیم (بدون HTTP) — **۴۲/۴۲ پاس**. زمان‌ها UTC داخلی؛ `datetime.utcnow()` منسوخ با `now(timezone.utc)` جایگزین شد.

### فاز ۲ — سرو سابسکریپشن: `routes/client.py` ✅
- [x] lookup در `users` اول (`resolve_user_request`)، سپس fallback به `subscription_paths`
- [x] ترتیب چک: DISABLED→۴۰۴ / PAUSED→dummy / منقضی→dummy / وگرنه سرو
- [x] کانفیگ dummy با احترام به `output_format` — `generate_dummy_content()` در [subscription_service.py](services/subscription_service.py) (helper `_encode` مشترک شد)
- [x] آپدیت `last_seen`/`last_ip`/`last_user_agent` در هر hit (داخل `resolve_user_request`)
- [x] لاگ statusهای جدید (`STATUS_EXPIRED`/`STATUS_USER_PAUSED`/`STATUS_USER_DISABLED`)
- **معیار پذیرش:** ✅ تست end-to-end با Flask test client — **۱۳/۱۳ پاس** (فعال/منقضی/pause/disabled/عمومی/ناشناس + رعایت plain). کل ۴۳ تست یکپارچه‌ی موجود هم سبز (بدون regression).

### فاز ۳ — API و صفحه ادمین ✅
- [x] endpointها در [admin_api.py](routes/admin_api.py): `GET/POST /adminpanel/api/users`، `PUT/POST/DELETE /adminpanel/api/users/<id>` + `/toggle` `/pause` `/resume` `/reset` (+ helper `_user_link` که `sub_url` می‌سازد)
- [x] پاس‌دادن `users` + `total_users` به قالب در [admin_pages.py](routes/admin_pages.py)
- **معیار پذیرش:** ✅ تست API با test client — **۲۳/۲۳ پاس** (auth، CRUD، pause/resume/reset/toggle، رندر صفحه). ۴۳ تست یکپارچه‌ی موجود هم سبز.

**یادداشت برای فاز فرانت:** endpointها آماده‌اند. فیلدهای هر کاربر در پاسخ API: `id, uuid, name, path, sub_url, status, effective_status, duration_days, remaining_text, remaining_seconds, activated_at_local, expire_at_local, last_seen_local, last_ip, last_user_agent, note, max_devices`.

### فاز ۴ — پوسته‌ی تب‌محور فرانت (بازچینش `admin.html`) ✅
- [x] نوار تب اصلی `.main-tabs` (pill بنفش سازگار با هدر) + `switchTab()` مستقل؛ `switchAutomationTab` نگه داشته شد (زیرتب تودرتو)
- [x] ۶ پنل: داشبورد / کاربران(placeholder) / کانفیگ‌ها / اسکن خودکار / تنظیمات / لاگ‌ها
- [x] حذف کامل UI مدیریت مسیرها (فرم تغییر مسیر + جدول)؛ لینک عمومی read-only به تنظیمات منتقل شد
- [x] `output_format` + `sort` از کارت کانفیگ به تب تنظیمات منتقل شد
- [x] modal لاگ → تب لاگ‌ها (fetchLogs موقع باز شدن تب)؛ statusهای جدید کاربر (منقضی/متوقف/کاربر غیرفعال) به نمایش لاگ اضافه شد
- [x] ذخیره‌ی تب فعال در `localStorage` (`restoreActiveTab`) + resize چارت‌ها موقع بازگشت به داشبورد
- **معیار پذیرش:** ✅ تست رندر ۲۱/۲۱ (تعادل div ۱۰۷/۱۰۷)؛ verify زنده در مرورگر: هر ۶ تب سوییچ می‌شن، زیرتب‌های اتوماسیون سالم، لاگ on-demand، بدون خطای JS جدید. (تنها خطای console یک باگ **از‌پیش‌موجود** renderChart/usageChart است که به‌عنوان کار جدا flag شد — ربطی به این فاز ندارد.)

### فاز ۵ — تب کاربران (UI) ✅ (روی شاخه‌ی ui-redesign)
- [x] جدول کاربران: نام+یادداشت، لینک (کپی با کلیک)، مدت، انقضا، باقیمانده، وضعیت رنگی (`.ust-*`)
- [x] مودال افزودن/ویرایش (نام، مدت، path سفارشی + دکمه تصادفی، یادداشت، حداکثر دستگاه)
- [x] اکشن‌ها: ویرایش / Pause-Resume / Reset / فعال-غیرفعال / حذف (با confirm) + AJAX به endpointهای فاز ۳؛ `switchTab('users')→loadUsers`، آپدیت شمارنده‌ی سایدبار
- **معیار پذیرش:** ✅ تست زنده در مرورگر (via JS، چون کلیک/screenshot در این محیط بی‌ثباته): ساخت (auto-path)، توقف→PAUSED، ازسرگیری→ACTIVE، حذف→empty state، آپدیت شمارنده — همه کار کرد، بدون خطای console. ۴۳ تست یکپارچه سبز.

### فاز ۶ — تست و تأیید نهایی
- [ ] تست‌های یکپارچه در [test_integration.py](test_integration.py): ساخت + path تکراری دوجدولی + فعال‌سازی first-use + سرو فعال + dummy منقضی/pause + احترام به output_format
- [ ] تست دستی end-to-end: کاربر با مدت کوتاه بساز، لینک را در v2rayNG بکش، منقضی‌شدن را ببین
- **معیار پذیرش:** تست‌ها سبز، رفتار end-to-end در کلاینت واقعی تأیید شد.

---

## 📌 فایل‌های درگیر (نقشه‌ی سریع)

| فایل | نقش در این feature |
| --- | --- |
| `database.py` | schema جدول `users` |
| `utils/constants.py` | `USER_PATH_REGEX`، statusهای لاگ |
| `services/user_service.py` | **جدید** — کل منطق کاربر |
| `routes/client.py` | سرو سابسکریپشن + fallback |
| `routes/admin_api.py` | endpointهای CRUD کاربر |
| `routes/admin_pages.py` | پاس‌دادن داده به قالب |
| `templates/admin.html` | پوسته‌ی ۶‌تبی + تب کاربران |
| `test_integration.py` | تست‌ها |
