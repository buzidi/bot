import os
import asyncio
import random
import re
from telethon import TelegramClient, events
from openai import OpenAI

# --- إعدادات OpenAI ---
openai_api_key = os.environ.get("OPENAI_API_KEY")
openai_client = OpenAI(api_key=openai_api_key)

# --- إعدادات Telethon ---
api_id = int(os.environ.get("API_ID"))
api_hash = os.environ.get("API_HASH")

# --- اختيار نوع الجلسة ---
bot_token = os.environ.get("BOT_TOKEN")
session_string = os.environ.get("SESSION_STRING")

if bot_token:
    # استخدام بوت رسمي
    client = TelegramClient('bot', api_id, api_hash).start(bot_token=bot_token)
elif session_string:
    # استخدام حساب شخصي مع Session String
    client = TelegramClient.from_session_string(session_string, api_id, api_hash)
    client.start()
else:
    raise ValueError("يرجى وضع BOT_TOKEN أو SESSION_STRING في متغيرات البيئة")

# --- ذاكرة المحادثة لكل مستخدم ---
conversations = {}

async def get_chatgpt_reply(user_id: int, user_text: str) -> str:
    """إرسال النص إلى ChatGPT مع حفظ السياق"""
    if user_id not in conversations:
        conversations[user_id] = [
            {"role": "system", "content": "انت بوت ودود ومساعد في الدردشة."}
        ]
    conversations[user_id].append({"role": "user", "content": user_text})

    try:
        response = openai_client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=conversations[user_id],
            max_tokens=200,
            temperature=0.7
        )
        reply = response.choices[0].message.content
        conversations[user_id].append({"role": "assistant", "content": reply})

        # إزالة أقدم الرسائل إذا تجاوزت 15 رسالة لتقليل الذاكرة
        if len(conversations[user_id]) > 15:
            conversations[user_id] = [conversations[user_id][0]] + conversations[user_id][-14:]

        return reply
    except Exception as e:
        return f"حصل خطأ: {e}"

def is_spam(text: str) -> bool:
    """تجاهل الرسائل القصيرة جدًا أو التي تحتوي على روابط"""
    if len(text.strip()) < 3:
        return True
    if re.search(r"(http[s]?://|t\.me/|www\.)", text.lower()):
        return True
    return False

# --- مستمع للرسائل الخاصة ---
@client.on(events.NewMessage(incoming=True))
async def handler(event):
    if event.is_private:
        user_id = event.sender_id
        text = event.raw_text

        if is_spam(text):
            return

        reply = await get_chatgpt_reply(user_id, text)

        # تأخير عشوائي لتقليل احتمالية الحظر
        await asyncio.sleep(random.randint(2, 6))

        await event.reply(reply)

# --- تشغيل البوت ---
print("🚀 Bot is running...")
client.run_until_disconnected()
