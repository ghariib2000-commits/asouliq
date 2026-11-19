# ASOUL.IQ

بوت Telegram مالي لمتابعة الأسواق والأصول في مصر.

## الهيكل

```
bot.py                     نقطة التشغيل (متوافقة مع Procfile)
app/config.py              الإعدادات من متغيرات البيئة
app/clock.py               توقيت القاهرة
app/db/connection.py       اتصال SQLite (WAL + Foreign Keys)
app/db/migrations.py       ترحيلات مُصدَّرة بإصدارات
app/providers/             مزودو البيانات (واجهة موحدة)
app/services/market.py     محرك الأسعار + تخزين مؤقت + صياغة الرسائل
app/services/users.py      بيانات المستخدمين وتفضيلاتهم
app/bot/handlers.py        أزرار وقوائم Telegram
legacy/                    الكود القديم للمراجعة فقط (غير مستخدم)
tests/                     اختبارات
```

## التشغيل محليًا

```bash
pip install -r requirements.txt
cp .env.example .env      # ثم ضع TELEGRAM_TOKEN
python bot.py
```

## الاختبارات

```bash
python -m unittest discover -s tests -t . -v
```

## قواعد حماية البيانات

- لا تُرفع قاعدة البيانات أو `.env` إلى GitHub (`.gitignore` يمنع ذلك).
- كل تغيير في المخطط يمر عبر `app/db/migrations.py` بإصدار جديد.
- لا نستخدم `DROP TABLE` أو `DROP COLUMN`، ولا نُعيد إنشاء القاعدة.
- الترحيل يعمل تلقائيًا عند بدء التشغيل ويحافظ على المستخدمين الحاليين.

## Railway: تخزين دائم (إلزامي)

بدون Volume يُمسح نظام الملفات مع كل Deploy أو Restart، ويفقد البوت كل المستخدمين.

1. Service → Settings → Volumes → **New Volume**.
2. Mount path: `/data`.
3. Variables → `DATABASE_PATH=/data/asouliq.db`.
4. Variables → `OWNER_TELEGRAM_ID=<معرّفك في Telegram>` لتفعيل `/backup`.
5. Redeploy واتأكد إن السجل لا يطبع تحذير "قاعدة البيانات داخل مجلد المشروع".

### نسخة احتياطية من قاعدة الإنتاج

- من داخل البوت: أرسل `/backup` من حساب المالك — يصل الملف كوثيقة Telegram.
- من الخادم: `python -m app.cli backup`

## حالة المصادر

- **الذهب:** بيانات حقيقية من `api.gold-api.com` و `open.er-api.com`،
  والسعر **تقديري محسوب** ويُذكر ذلك في الرسالة.
- **البورصة المصرية:** لا يوجد مصدر مرخّص متصل بعد، ولذلك تظهر رسالة
  "البيانات غير متاحة" بدون أي أرقام. **لا تُعرض أرقام وهمية نهائيًا.**
