import asyncio
import re
import db_manager
import psycopg2
import traceback
import random
import os

from telethon import TelegramClient, events
from db_manager import get_conn, mark_answer_sent, insert_request, get_requests_for_chat
from datetime import date
from rapidfuzz import fuzz, process
from telethon.sessions import StringSession
from telethon.errors import RPCError

# بيانات الاتصال
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
STRING_SESSION = os.getenv("STRING_SESSION")

client = TelegramClient(StringSession(STRING_SESSION), API_ID, API_HASH)

# قائمة للتحيات
GREETINGS = ["السلام عليكم", "سلام عليكم", "مرحبا", "اهلا", "أهلاً", "السلام"]
#   =======================================
# حالات محلية لجمع الطلب
USER_REQUEST_STATE = {}  # key = chat_id -> dict {state:, service:, data:, messages_to_delete: []}
# حالات مسماة
SVC_CONFIRM, REQ_NAME, REQ_BRANCH, REQ_YEAR, REQ_PHONE, REQ_NOTES, REQ_CONFIRM = range(10, 17)

# regex validations
RE_ARABIC = re.compile(r'^[ء-ي\s]+$')
RE_YEAR = re.compile(r'^\d{4}-\d{4}$')  # مثال: 2025-2024
RE_PHONE = re.compile(r'^09\d{8}$')

VALID_BRANCHES = ["طرابلس", "مصراته", "جرير"]

def valid_branch(branch: str) -> bool:
    return branch in VALID_BRANCHES

def valid_year(year: str) -> bool:
    if not RE_YEAR.match(year):
        return False
    y1, y2 = map(int, year.split("-"))
    return y2 == y1 + 1 and 2000 <= y1 <= 2100

def valid_phone(phone: str) -> bool:
    return RE_PHONE.match(phone) is not None

def valid_notes(notes: str) -> bool:
    return len(notes) <= 300

#   ==================================
KEYWORDS = {
    ("بوت", "الحجز", "موعد", "سجل المواعيد", "كيف أحجز", "اريد احجز", "اريد موعد", "موعد جديد"): "bot_info"
}
async def send_bot_info(event):
    text = (
        "📌 *بارك الله فيك أخي الكريم / أختي الكريمة*\n\n"
        "✨ يسعدنا أن نخبرك أن خدمة **الحجز عبر البوت** متاحة الآن، وهي وسيلتك الميسّرة لترتيب أمورك معنا بانتظام.\n\n"
        "📅 من خلال البوت يمكنك:\n"
        "- حجز موعد بسهولة.\n"
        "- متابعة مواعيدك السابقة.\n"
        "- الحصول على تذكير قبل موعدك.\n\n"
        "⚠️ *ننصحك بالحجز قبل مراجعتنا، لأن قدومك من غير موعد قد يسبب بعض الإحراجات أو التأخير، وحرصنا أن يكون كل شيء مرتب ومنظم على خير وجه.*\n\n"
        "👉 تفضل بالدخول إلى البوت من هنا:\n"
        "[🤖 رابط البوت](@Atll77_bot)\n\n"
        "نسأل الله أن ييسر لك أمرك ويكتب لك التوفيق 🌿"
    )
    await event.reply(text, link_preview=False)
#=============================================
# ردود جاهزة
UNKNOWN_REPLIES = [
    "❓ لم أفهم رسالتك، حاول أن توضح أكثر من فضلك.",
    "🤔 ممكن تكتب سؤالك بشكل أوضح؟",
    "📌 لم أتمكن من فهم رسالتك، جرب صياغة أخرى.",
    "🧐 وضّح أكثر لو سمحت، حتى أقدر أساعدك.",
    "✍️ جرب تكتب طلبك بجملة كاملة عشان أساعدك.",
    "🔍 لم أستوعب كلامك، حاول توضّح أكثر.",
    "🙂 ممكن توضّح قصدك أكثر؟",
    "⚠️ الرسالة غير واضحة، جرب تعيد صياغتها."
]

#=========================================
async def get_answer(question: str):
    """البحث عن إجابة باستخدام Fuzzy Matching"""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT question, answer FROM questions_userbot WHERE answer <> ''")
    rows = cur.fetchall()
    conn.close()

    if not rows:
        return None

    # نحول الأسئلة لقاعدة بيانات صغيرة
    questions = {row[0]: row[1] for row in rows}

    # نبحث عن أقرب سؤال
    best_match, score, _ = process.extractOne(
        question.strip(),
        questions.keys(),
        scorer=fuzz.WRatio  # مقياس التشابه الأفضل
    )

    if score >= 80:  # لو التشابه 80% أو أكثر نرجع الجواب
        return questions[best_match]

    return None

async def save_question(chat_id: int, question: str):
    """حفظ السؤال أو إضافة المستخدم للقائمة إذا موجود"""
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT id, chat_id FROM questions_userbot
        WHERE question = %s
        LIMIT 1
    """, (question.strip(),))
    row = cur.fetchone()

    if row:
        qid, chat_id = row
        users = chat_id.split(",") if chat_id else []
        if str(chat_id) not in users:
            users.append(str(chat_id))
            cur.execute("""
                UPDATE questions_userbot
                SET chat_id = %s
                WHERE id = %s
            """, (",".join(users), qid))
    else:
        cur.execute("""
            INSERT INTO questions_userbot (chat_id, question, answer, sent)
            VALUES (%s, %s, %s, %s)
        """, (str(chat_id), question.strip(), "", False))

    conn.commit()
    conn.close()

def is_valid_question(message: str) -> bool:
    """
    يتحقق إذا كانت الرسالة سؤال أو استفسار صالح للحفظ
    """

    text = message.strip()

    # 1) تجاهل القصيرة جداً
    if len(text) < 3:
        return False

    # 2) تجاهل إذا كلها أرقام أو رموز
    if re.fullmatch(r"[\d\W]+", text):
        return False

    # 3) تجاهل الضحك والكلام الفارغ (تكرار نفس الحرف)
    if re.fullmatch(r"(.)\1{3,}", text):  # مثل هههه, مممم, وااااا
        return False

    # 4) كلمات/أصوات شائعة غير مفيدة
    NOISE_WORDS = ["هههه", "ممم", "اوكي", "تمام", "سلام", "باي", "👍", "👌"]
    if any(word in text for word in NOISE_WORDS):
        return False

    # 5) أسئلة واضحة (فيها ؟ أو كلمات استفهام)
    question_words = ["كيف", "متى", "هل", "أين", "ماذا", "ليش", "لماذا"]
    if "؟" in text or any(text.startswith(w) for w in question_words):
        return True

    # 6) نص عربي طويل فيه معنى (مش مجرد تكرار)
    if re.match(r"^[ء-ي\s]{3,}$", text):
        return True

    return False

def classify_message(message: str) -> str:
    msg = message.strip()

    # 1) تحية
    if any(g in msg for g in GREETINGS):
        return "greeting"

    # 2) كلمات مفتاحية
    for words, action in KEYWORDS.items():
        if any(w in msg for w in words):
            return "keyword"

    # 3) تجاهل النصوص القصيرة جدًا أو غير المفهومة
    if len(msg) < 3 or re.fullmatch(r"[\d\W]+", msg):
        return "unknown"

    # 4) فلترة الضحك/التكرارات
    if re.fullmatch(r"(.)\1{3,}", msg):  # مثل هههه, مممم, وااااا
        return "noise"

    # 5) كلمات/أصوات شائعة غير مفيدة
    NOISE_WORDS = ["هههه", "ممم", "اوكي", "تمام", "سلام", "باي", "👍", "👌", "🤣", "😂"]
    if any(word in msg for word in NOISE_WORDS):
        return "noise"

    # 6) أسئلة واضحة (؟ أو كلمات استفهام)
    question_words = ["كيف", "متى", "هل", "أين", "ماذا", "ليش", "لماذا"]
    if "؟" in msg or any(msg.startswith(w) for w in question_words):
        return "question"

    # 7) جملة عربية طبيعية (أغلبها حروف عربية)
    if re.match(r"^[ء-ي\s]{3,}$", msg):
        return "question"

    return "unknown"


@client.on(events.NewMessage(incoming=True))
async def handler(event):
    # تجاهل أي رسالة ليست من الخاص
    if not event.is_private:
        return

    sender = await event.get_sender()
    if sender and sender.bot:
        return
    
    chat_id = event.chat_id
    message = event.raw_text.strip()

    if not message:
        return

    # استدعاء الحالة الحالية (لو في مسار طلب)
    state = USER_REQUEST_STATE.get(chat_id)

    # --------- بداية منطق الطلبات ---------
    if not state and any(k in message for k in ["استمارة", "استخراج", "طلب استمارة", "استمارة التخرج"]):
        svc_text = "استخراج استمارة التخرج"
        msg = await event.reply(
            f"هل تقصد {svc_text}؟\n\n"
            "للتأكيد أرسل: نعم، وإذا لا أرسل: لا.\n\n"
            "نسأل الله أن ييسر لك أمرك 🌿"
        )
        USER_REQUEST_STATE[chat_id] = {
            "state": SVC_CONFIRM,
            "service": svc_text,
            "data": {},
            "messages": [msg.id, event.message.id]
        }
        return

    if state:
        st = state["state"]

        # 👇 هنا يبقى منطق الاستمارة كاملاً كما كان (SVC_CONFIRM → REQ_CONFIRM)
        # بدون تغيير ...
        # -------------------
        if st == SVC_CONFIRM:
            if message == "نعم":
                m = await event.reply(
                    "جزاك الله خيراً ✨\n\n"
                    "الرجاء إدخال الاسم الرباعي بالكامل (بالعربية فقط):"
                )
                state["messages"].append(m.id)
                state["state"] = REQ_NAME
            elif message == "لا":
                await event.reply("حسناً، يمكنك توضيح الخدمة التي تحتاجها أو كتابة 'استمارة' مجدداً.")
                USER_REQUEST_STATE.pop(chat_id, None)
            else:
                await event.reply("أرسل نعم للتأكيد أو لا للإلغاء.")
            return

        if st == REQ_NAME:
            if not RE_ARABIC.match(message):
                await event.reply("❌ الاسم يجب أن يكون بالعربية فقط. أعد المحاولة:")
                return
            state["data"]["name"] = message
            m = await event.reply("✅  الآن أدخل اسم الفرع :")
            state["messages"].append(m.id)
            state["state"] = REQ_BRANCH
            return

        if st == REQ_BRANCH:
            if not valid_branch(message):
                await event.reply("❌ الفرع غير صحيح. الفروع المسموحة هي: " + ", ".join(VALID_BRANCHES))
                return
            state["data"]["branch"] = message
            m = await event.reply("✅  الرجاء إدخال سنة التخرج مثل: 2025-2024 :")
            state["messages"].append(m.id)
            state["state"] = REQ_YEAR
            return

        if st == REQ_YEAR:
            if not valid_year(message):
                await event.reply("❌ الصيغة غير صحيحة. مثال صحيح: 2025-2024")
                return
            state["data"]["grad_year"] = message
            m = await event.reply("✅  الرجاء إدخال رقم الهاتف :")
            state["messages"].append(m.id)
            state["state"] = REQ_PHONE
            return

        if st == REQ_PHONE:
            if not valid_phone(message):
                await event.reply("❌ رقم الهاتف غير صحيح. يجب أن يبدأ بـ09 ويحتوي 10 أرقام.")
                return
            state["data"]["phone"] = message
            m = await event.reply("✅  إذا لديك ملاحظات إضافية مثل تجهيز الكشف الدرجات او التعديل في البيانات فيرجا ذكرها الان، وإذا لا يوجد اكتب تم:")
            state["messages"].append(m.id)
            state["state"] = REQ_NOTES
            return

        if st == REQ_NOTES:
            if not valid_notes(message):
                await event.reply("❌ الملاحظات طويلة جداً. الحد الأقصى 300 حرف.")
                return
            state["data"]["notes"] = "" if message == "تم" else message
            d = state["data"]
            confirm_text = (
                "📝 *الرجاء مراجعة بيانات طلبك لكي يتم ارسالها للموظف المكلف لتلبية طلبك:* \n\n"
                f"👤 الاسم: {d['name']}\n"
                f"🏷️ الفرع: {d['branch']}\n"
                f"📚 سنة التخرج: {d['grad_year']}\n"
                f"📱 الهاتف: {d['phone']}\n"
                f"🗒️ الملاحظات: {d['notes'] or '—'}\n\n"
                "إذا موافق أرسل نعم، وإذا تحتاج تعديل أرسل لا."
            )
            m = await event.reply(confirm_text)
            state["messages"].append(m.id)
            state["state"] = REQ_CONFIRM
            return

        if st == REQ_CONFIRM:
            if message == "نعم":
                d = state["data"]
                insert_request(
                    chat_id, state["service"],
                    d["name"], d["branch"], d["grad_year"],
                    d["phone"], d["notes"]
                )
                try:
                    await client.delete_messages(chat_id, state["messages"])
                except RPCError as e:
                    print("لم أستطع حذف الرسائل:", e)
                await event.reply(
                    "✅ تم إرسال طلبك إلى الموظف المكلف بإذن الله.\n\n"
                    "سوف يتم الرد عليك قريباً.\n"
                    "لمتابعة حالة طلبك لاحقاً أرسل كلمة: طلبي "
                )
                USER_REQUEST_STATE.pop(chat_id, None)
            elif message == "لا":
                await event.reply("تم إلغاء الطلب. يمكنك البدء من جديد بكتابة 'استمارة'.")
                USER_REQUEST_STATE.pop(chat_id, None)
            else:
                await event.reply("أرسل نعم لتأكيد أو لا لإلغاء.")
            return
        # -------------------

    # --------- نهاية منطق الطلبات ---------

    # خاصية عرض الطلبات السابقة
    if message == "طلبي":
        rows = get_requests_for_chat(chat_id)
        if not rows:
            await event.reply("📭 لا توجد طلبات مسجلة لك.")
        else:
            txt = "📋 طلباتك:\n\n"
            for r in rows[:8]:
                txt += f"🔹 رقم {r[0]} — {r[1]} — الحالة: {r[2]}\n"
            await event.reply(txt)
        return

    # --------- منطق التصنيف ---------
    msg_type = classify_message(message)

    if msg_type == "greeting":
        await event.reply("وعليكم السلام ورحمة الله وبركاته ")
        return

    elif msg_type == "keyword":
        for words, action in KEYWORDS.items():
            if any(w in message for w in words):
                if action == "bot_info":
                    await send_bot_info(event)
                    return

    elif msg_type == "question":
        answer = await get_answer(message)
        if answer:
            await asyncio.sleep(2)
            await event.reply(answer)
        else:
            await save_question(chat_id, message)  # ✅ يحفظ فقط الأسئلة الحقيقية
            await asyncio.sleep(2)
            await event.reply(
                "سيتم الرد على استفسارك في أقرب وقت ممكن.\n"
                "إذا كنت بحاجة للرد العاجل على استفسارك، اتصل على هذا الرقم: 0911448222"
            )
        return

    elif msg_type == "unknown":
        await event.reply(random.choice(UNKNOWN_REPLIES))
        return

# -------------------------------
# مهمة خلفية لإرسال الإجابات الجديدة
# -------------------------------
import db_manager

async def notify_users():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, chat_id, service, status, staff_note, pickup_date
        FROM requests_userbot
        WHERE notified=FALSE
    """)
    rows = cur.fetchall()

    for rid, chat_id, service, status, staff_note, pickup_date in rows:
        msg = [
            "📢 *إشعار تحديث حالة الطلب*",
            f"🆔 رقم الطلب: {rid}",
            f"📝 الخدمة: {service}",
            f"📌 الحالة الجديدة: {status}"
        ]
        if pickup_date:
            msg.append(f"📅 تاريخ الاستلام: {pickup_date}")
        if staff_note:
            msg.append(f"💬 ملاحظة الموظف: {staff_note}")

        try:
            await client.send_message(chat_id, "\n".join(msg))
            cur.execute("UPDATE requests_userbot SET notified=TRUE WHERE id=%s", (rid,))
        except RPCError as e:
            print(f"خطأ من تيليجرام عند إرسال الإشعار: {e}")
        except psycopg2.Error as e:
            print(f"خطأ في قاعدة البيانات عند تحديث حالة الإشعار: {e}")

    conn.commit()
    conn.close()
async def check_pending_answers():
    while True:
        try:
            rows = db_manager.get_unsent_answers()
            for qid, chat_ids, question, answer in rows:
                if not chat_ids:
                    continue
                users = [u for u in chat_ids.split(",") if u.strip()]
                for uid in users:
                    try:
                        await client.send_message(
                            int(uid),
                            f"❓ سؤالك: {question}\n\n💬 الجواب: {answer}"
                        )
                    except RPCError as e:
                        print(f"خطأ تيليجرام عند إرسال الجواب إلى {uid}: {e}")
                # ✅ تحديث أن الجواب أُرسل
                db_manager.mark_answer_sent(qid)

        except psycopg2.Error as e:
            print(f"خطأ في قاعدة البيانات داخل check_pending_answers: {e}")
        except RPCError as e:
            print(f"خطأ تيليجرام داخل check_pending_answers: {e}")
        except Exception:
            traceback.print_exc()

        await asyncio.sleep(10)  # فحص كل 10 ثوانٍ

async def scheduler():
    while True:
        try:
            await notify_users()
        except Exception as e:
            print("خطأ في scheduler:", e)
        await asyncio.sleep(60)  # فحص كل دقيقة


# -------------------------------
# تشغيل البوت
# -------------------------------
async def main():
    print("🚀 Userbot is running...")

    # تشغيل المهمات الخلفية
    client.loop.create_task(check_pending_answers())
    client.loop.create_task(scheduler())   # 👈 هنا أضفنا المجدول

    # تشغيل الـ client نفسه
    await client.run_until_disconnected()


with client:
    client.loop.run_until_complete(main())
