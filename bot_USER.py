# telethon_bot.py
import os
import re
import asyncio
import aiosqlite
from dotenv import load_dotenv
from telethon import TelegramClient, events, errors
from telethon.sessions import StringSession
from datetime import datetime, timezone
from langdetect import detect

load_dotenv()

API_ID = int(os.getenv("API_ID") or 0)
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN") or None
SESSION_NAME = os.getenv("SESSION_NAME") or "my_session"

DB_PATH = "bot_data.db"
MAX_QUEUE_SIZE = 10000

# ---------- Arabic text utilities ----------
_arabic_diacritics = re.compile("""
                             ّ    | # Tashdid
                             َ    | # Fatha
                             ً    | # Tanwin Fath
                             ُ    | # Damma
                             ٌ    | # Tanwin Damm
                             ِ    | # Kasra
                             ٍ    | # Tanwin Kasr
                             ْ    | # Sukun
                             ـ     # Tatwil/Kashida
                         """, re.VERBOSE)

def normalize_arabic(text: str) -> str:
    text = text.strip()
    text = _arabic_diacritics.sub('', text)
    # normalize alef variants
    text = re.sub("[إأآا]", "ا", text)
    text = re.sub("ى", "ي", text)
    text = re.sub("ئ", "ء", text)
    text = re.sub("ؤ", "ء", text)
    text = re.sub("ـ", "", text)
    text = re.sub(r"[^\w\sء-ي]", " ", text)  # remove punctuation (keep arabic letters)
    text = re.sub(r"\s+", " ", text)
    return text.lower()

# ---------- Simple Intent/FAQ engine (قابل للتوسيع) ----------
INTENTS = {
    "opening_hours": {
        "keywords": ["متى", "الدوام", "مواعيد", "متى تفتح", "متى يفتح"],
        "responses": [
            "دوام المعهد: من الأحد إلى الخميس، من الساعة 8 صباحًا حتى 2 ظهرًا. هل تريد مواعيد مكتب التسجيل؟",
            "مواعيدنا عادة تكون صباحية - هل تريد تفاصيل أكثر عن دورات بعينها؟"
        ]
    },
    "courses": {
        "keywords": ["دورة", "دورات", "مادة", "منهاج", "مقررات"],
        "responses": [
            "نقدم دورات في الفقه، التفسير، الحديث، وأصول الدين. هل تبحث عن مستوى معين (تمهيدي / متوسط / متقدم)؟",
            "هل تود معلومات عن المدة أو الشهادة أو المنهاج؟"
        ]
    },
    "registration": {
        "keywords": ["تسجيل", "سجل", "الالتحاق", "التسجيل"],
        "responses": [
            "للتسجيل الرجاء إرسال اسمك الكامل، رقم الهاتف، والبرنامج الذي ترغب به. سيتابعك موظف التسجيل بإذن الله.",
            "يمكن التسجيل عبر النموذج الإلكتروني أو الحضور لمكتب التسجيل في المواعيد أعلاه. تود الرابط؟"
        ]
    },
    "religious_question": {
        "keywords": ["حكم", "سؤال شرعي", "مشروعي", "كيف أفعل", "هل يجوز", "ما حكم"],
        "responses": [
            "بالنسبة للسؤال الشرعي: نعتمد على الأدلة الشرعية والفقهية. هل تستطيع تزويدي بتفصيل السؤال؟",
            "نرحب بالأسئلة الشرعية. سأحاول الإجابة باختصار، وإذا احتاج الأمر لتفصيل فسنحيلك لأحد المختصين."
        ]
    },
    "greeting": {
        "keywords": ["السلام", "مرحبا", "أهلا", "السلام عليكم", "وعليكم السلام"],
        "responses": [
            "وعليكم السلام ورحمة الله وبركاته — كيف أستطيع مساعدتك اليوم؟",
            "أهلاً وسهلاً بك في معهدنا، تفضل بسؤالك أو ما الذي تود معرفته؟"
        ]
    },
    "thanks": {
        "keywords": ["شكرا", "شكراً", "جزاك", "بارك الله فيك"],
        "responses": [
            "العفو، في خدمتك دائماً. هل تحتاج إلى شيء آخر؟",
            "بارك الله فيك، أسأل الله أن يبارك في علمك."
        ]
    },
}

FALLBACK_RESPONSES = [
    "جزاك الله خيراً على التواصل. لم أفهم سؤالك تماماً، هل يمكنك كتابته بصيغة أخرى أو إضافة تفاصيل؟",
    "أعتذر، لم أتمكن من تحديد ما تريد. هل تبحث عن مواعيد، دورات، أو سؤال شرعي محدد؟"
]

# ---------- Database helpers (SQLite) ----------
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS contexts (
                user_id INTEGER PRIMARY KEY,
                last_update TEXT,
                context TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                incoming TEXT,
                outgoing TEXT,
                ts TEXT
            )
        """)
        await db.commit()

async def save_context(user_id: int, context_text: str):
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR REPLACE INTO contexts (user_id, last_update, context) VALUES (?, ?, ?)",
                         (user_id, now, context_text))
        await db.commit()

async def get_context(user_id: int) -> str:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT context FROM contexts WHERE user_id = ?", (user_id,)) as cur:
            row = await cur.fetchone()
            return row[0] if row else ""

async def log_message(user_id: int, incoming: str, outgoing: str):
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO logs (user_id, incoming, outgoing, ts) VALUES (?, ?, ?, ?)",
                         (user_id, incoming, outgoing, now))
        await db.commit()

# ---------- Intent detection ----------
def detect_intent(text: str):
    """Simple keyword-based intent detection (Arabic). Returns (intent, score)."""
    text_norm = normalize_arabic(text)
    best = (None, 0)
    for intent, info in INTENTS.items():
        score = 0
        for kw in info["keywords"]:
            kw_norm = normalize_arabic(kw)
            if kw_norm in text_norm:
                score += 2
            # word-by-word match
            for token in text_norm.split():
                if token == kw_norm:
                    score += 1
        # small boost if language seems Arabic
        try:
            lang = detect(text)
            if lang == "ar":
                score += 0.5
        except Exception:
            pass
        if score > best[1]:
            best = (intent, score)
    return best

def generate_response_for_intent(intent: str, user_message: str, context: str) -> str:
    if not intent:
        return FALLBACK_RESPONSES[0]
    candidates = INTENTS[intent]["responses"]
    # simple selection: choose first candidate; could be randomized or context-aware
    resp = candidates[0]
    # personalize tiny bit
    if "سؤال شرعي" in user_message or intent == "religious_question":
        resp += " (ملاحظة: هذه إجابة عامة، وللحكم النهائي يرجى الرجوع إلى أحد العلماء أو مكتب الفتوى بالمعهد.)"
    return resp

# ---------- Bot / Client setup ----------
async def start_client():
    await init_db()

    # If BOT_TOKEN present, start as bot (simpler for استضافة)
    if BOT_TOKEN:
        client = TelegramClient(SESSION_NAME, API_ID, API_HASH)
        await client.start(bot_token=BOT_TOKEN)
        print("Started as bot (via BOT_TOKEN).")
    else:
        client = TelegramClient(SESSION_NAME, API_ID, API_HASH)
        # If no session file exists, this will prompt (once) for phone & code when running interactively.
        await client.start()
        print("Started as user-client (session stored).")

    # message queue (simple backpressure)
    queue = asyncio.Queue(maxsize=MAX_QUEUE_SIZE)

    @client.on(events.NewMessage(incoming=True))
    async def handler(event):
        # avoid acting on channels/bots if desired; here we process private messages only
        if not event.is_private:
            return
        sender = await event.get_sender()
        user_id = sender.id
        text = event.raw_text or ""
        # push to queue for background processing
        try:
            queue.put_nowait((event, user_id, text))
        except asyncio.QueueFull:
            await event.reply("عذراً، عدد الرسائل كبير الآن. حاول لاحقاً. بارك الله فيك.")
            return

    async def worker():
        while True:
            event, user_id, text = await queue.get()
            try:
                await process_message(client, event, user_id, text)
            except Exception as e:
                print("Error processing message:", e)
            queue.task_done()

    # spawn workers
    workers = [asyncio.create_task(worker()) for _ in range(4)]  # 4 workers — قابل للزيادة
    print("Workers started.")
    await client.run_until_disconnected()
    for w in workers:
        w.cancel()

async def process_message(client: TelegramClient, event, user_id: int, text: str):
    # get context
    ctx = await get_context(user_id) or ""
    intent, score = detect_intent(text)
    # generate response
    resp = generate_response_for_intent(intent, text, ctx)
    # optionally, include short context-aware personalization
    if ctx:
        resp = resp + "\n\n" + "معلومة سابقة محفوظة لدينا: " + (ctx[:120] + "..." if len(ctx) > 120 else ctx)
    # update context (simple policy: keep last user message)
    new_ctx = text if len(text) < 1000 else text[:1000]
    await save_context(user_id, new_ctx)
    # log
    await log_message(user_id, text, resp)
    # send reply
    try:
        await event.reply(resp)
    except errors.BotMethodInvalidError:
        # fallback if reply not allowed
        await client.send_message(user_id, resp)

# ---------- Entrypoint ----------
if __name__ == "__main__":
    try:
        asyncio.run(start_client())
    except KeyboardInterrupt:
        print("Exiting...")
