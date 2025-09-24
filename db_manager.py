# db_manager.py (PostgreSQL version)
import psycopg2
import psycopg2.extras
import os
import json
from typing import Dict, List, Any
from psycopg2.extras import RealDictCursor
from datetime import datetime
# إعدادات الاتصال بـ PostgreSQL
DB_CONFIG = {
    "host": "localhost",
    "database": "database",  # ضع اسم قاعدة البيانات هنا
    "user": "buzidi",           # ضع اسم المستخدم هنا
    "password": "buzidimy987",       # ضع كلمة المرور هنا
    "port": 5432
}

def get_conn():
    """إنشاء اتصال جديد بـ PostgreSQL"""
    return psycopg2.connect(**DB_CONFIG)

def init_db():
    conn = get_conn()
    cur = conn.cursor()

    # إنشاء الجداول إذا لم تكن موجودة
    cur.execute("""
        CREATE TABLE IF NOT EXISTS visitors(
            pid TEXT PRIMARY KEY,
            name TEXT,
            department TEXT,
            title TEXT,
            notes TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS staff(
            pid TEXT PRIMARY KEY,
            name TEXT,
            office TEXT
        )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS appointments(
        id SERIAL PRIMARY KEY,
        chat_id BIGINT,  -- إضافة عمود chat_id
        name TEXT,
        department TEXT,
        title TEXT,
        date TEXT,
        time TEXT,
        notes TEXT,
        phone TEXT
    )
""")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS visits(
            id SERIAL PRIMARY KEY,
            pid TEXT,
            name TEXT,
            department TEXT,
            time TEXT,
            title TEXT,
            notes TEXT,
            date TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS staff_logs(
            id SERIAL PRIMARY KEY,
            pid TEXT,
            name TEXT,
            out_time TEXT,
            in_time TEXT,
            duration TEXT,
            notes TEXT,
            date TEXT
        )
    """)
    # جدول المستخدمين
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users_telegram(
            chat_id BIGINT PRIMARY KEY,
            name TEXT,
            role TEXT,         -- admin / staff / user
            office TEXT,
            phone TEXT,
            status TEXT        -- active / banned
        )
    """)

    # جدول قائمة الانتظار
    cur.execute("""
        CREATE TABLE IF NOT EXISTS waiting_list_telegram(
            id SERIAL PRIMARY KEY,
            chat_id BIGINT,
            name TEXT,
            role TEXT,
            office TEXT,
            phone TEXT,
            status TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)


    # جدول سجل العمليات
    cur.execute("""
        CREATE TABLE IF NOT EXISTS operations_log_telegram(
            id SERIAL PRIMARY KEY,
            chat_id BIGINT,
            name TEXT,
            role TEXT,
            action TEXT,
            timestamp TIMESTAMP DEFAULT NOW()
        )
    """)
        # جدول الأسئلة والأجوبة الخاصة بالـ Userbot
    cur.execute("""
        CREATE TABLE IF NOT EXISTS questions_userbot (
            id SERIAL PRIMARY KEY,
            chat_id TEXT,
            question TEXT NOT NULL,
            answer TEXT DEFAULT '',
            sent BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT NOW(),
            answered_at TIMESTAMP
        )
    """)
    # جدول الطلبات محدث مع عمود notified
    cur.execute("""
    CREATE TABLE IF NOT EXISTS requests_userbot (
        id SERIAL PRIMARY KEY,
        chat_id BIGINT NOT NULL,
        user_name TEXT,
        branch TEXT,
        grad_year TEXT,         -- مثال: "2025-2024"
        phone TEXT,
        notes TEXT,
        service TEXT,           -- نوع الخدمة مثل: "استخراج استمارة التخرج"
        status TEXT DEFAULT 'انتظار الموافقة',  -- حالات: انتظار الموافقة / قيد الانجاز / جاهز / مرفوض
        staff_note TEXT,        -- ملاحظة الموظف عند الرفض أو التحديث
        pickup_date TEXT,       -- عند اختيار موعد الاستلام (YYYY-MM-DD)
        notified BOOLEAN DEFAULT FALSE,  -- لتحديد ما إذا تم إشعار المستخدم
        created_at TIMESTAMP DEFAULT NOW(),
        updated_at TIMESTAMP DEFAULT NOW()
    )
    """)

    conn.commit()
    conn.close()

# ---------------- visitors ----------------
def get_visitors_dict() -> Dict[str, Dict[str, str]]:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT pid, name, department, title, notes FROM visitors")
    rows = cur.fetchall()
    conn.close()
    return {pid: {"name": name or "", "department": department or "", "title": title or "", "notes": notes or ""} for (pid, name, department, title, notes) in rows}

def save_visitors_dict(data: Dict[str, Dict[str, str]]):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM visitors")
    for pid, info in data.items():
        cur.execute(
            "INSERT INTO visitors(pid, name, department, title, notes) VALUES (%s, %s, %s, %s, %s) ON CONFLICT (pid) DO UPDATE SET name=EXCLUDED.name, department=EXCLUDED.department, title=EXCLUDED.title, notes=EXCLUDED.notes",
            (str(pid), info.get("name", ""), info.get("department", ""), info.get("title", ""), info.get("notes", ""))
        )
    conn.commit()
    conn.close()

# ---------------- staff ----------------
def get_staff_dict() -> Dict[str, Dict[str, str]]:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT pid, name, office FROM staff")
    rows = cur.fetchall()
    conn.close()
    return {pid: {"name": name or "", "office": office or ""} for (pid, name, office) in rows}

def save_staff_dict(data: Dict[str, Dict[str, str]]):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM staff")
    for pid, info in data.items():
        cur.execute("""
            INSERT INTO staff(pid, name, office) VALUES (%s, %s, %s)
            ON CONFLICT (pid) DO UPDATE SET name=EXCLUDED.name, office=EXCLUDED.office
        """, (str(pid), info.get("name", ""), info.get("office", "")))
    conn.commit()
    conn.close()

# ---------------- appointments ----------------
def get_appointments_dict() -> Dict[str, Dict[str, str]]:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id, chat_id, name, department, title, date, time, notes, phone FROM appointments ORDER BY id")
    rows = cur.fetchall()
    conn.close()
    result = {}
    for (id_, chat_id, name, dept, title, date, time, notes, phone) in rows:
        result[str(id_)] = {
            "chat_id": chat_id,
            "name": name or "",
            "department": dept or "",
            "title": title or "",
            "date": date or "",
            "time": time or "",
            "notes": notes or "",
            "phone": phone or ""
        }
    return result



def save_appointments_dict(data: Dict[str, Dict[str, str]]):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM appointments")
    for key, entry in sorted(data.items(), key=lambda x: int(x[0]) if str(x[0]).isdigit() else 0):
        if str(key).isdigit():
            cur.execute("""
                INSERT INTO appointments(id, chat_id, name, department, title, date, time, notes, phone)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    chat_id=EXCLUDED.chat_id,
                    name=EXCLUDED.name,
                    department=EXCLUDED.department,
                    title=EXCLUDED.title,
                    date=EXCLUDED.date,
                    time=EXCLUDED.time,
                    notes=EXCLUDED.notes,
                    phone=EXCLUDED.phone
            """, (int(key), entry.get("chat_id"), entry.get("name",""), entry.get("department",""), 
                  entry.get("title",""), entry.get("date",""), entry.get("time",""), 
                  entry.get("notes",""), entry.get("phone","")))
        else:
            cur.execute("""
                INSERT INTO appointments(chat_id, name, department, title, date, time, notes, phone)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (entry.get("chat_id"), entry.get("name",""), entry.get("department",""), entry.get("title",""),
                  entry.get("date",""), entry.get("time",""), entry.get("notes",""), entry.get("phone","")))
    conn.commit()
    conn.close()

def add_visit(date_str: str, pid: str, name: str, department: str, time: str, title: str, notes: str):
    """إضافة زيارة جديدة دون حذف القديم"""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO visits(pid, name, department, time, title, notes, date)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
    """, (str(pid or ""), name or "", department or "", time or "", title or "", notes or "", date_str))
    conn.commit()
    conn.close()
def delete_appointment_by_id(appt_id: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM appointments WHERE id=%s", (appt_id,))
    conn.commit()
    conn.close()


# ---------------- visits logs (daily) ----------------
def get_visits_list_for_date(date_str: str) -> List[List[str]]:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT pid, name, department, time, title, notes FROM visits WHERE date=%s ORDER BY id", (date_str,))
    rows = cur.fetchall()
    conn.close()
    return [[pid or "", name or "", department or "", time or "", title or "", notes or ""] for (pid, name, department, time, title, notes) in rows]

def save_visits_list_for_date(date_str: str, rows: List[List[str]]):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM visits WHERE date=%s", (date_str,))
    for row in rows:
        pid, name, department, time, title, notes = (row + [""] * 6)[:6]
        cur.execute("""
            INSERT INTO visits(pid, name, department, time, title, notes, date)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (str(pid or ""), name or "", department or "", time or "", title or "", notes or "", date_str))
    conn.commit()
    conn.close()
def delete_visit(pid: str, date_str: str):
    """حذف زيارة معينة حسب الرقم الشخصي والتاريخ"""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM visits WHERE pid=%s AND date=%s", (pid, date_str))
    conn.commit()
    conn.close()

# ---------------- staff_logs ----------------
def get_staff_logs_list_for_date(date_str: str) -> List[List[str]]:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT pid, name, out_time, in_time, duration, notes FROM staff_logs WHERE date=%s ORDER BY id", (date_str,))
    rows = cur.fetchall()
    conn.close()
    return [[pid or "", name or "", out_time or "", in_time or "", duration or "", notes or ""] for (pid, name, out_time, in_time, duration, notes) in rows]

def save_staff_logs_list_for_date(date_str: str, rows: List[List[str]]):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM staff_logs WHERE date=%s", (date_str,))
    for row in rows:
        pid, name, out_time, in_time, duration, notes = (row + [""] * 6)[:6]
        cur.execute("""
            INSERT INTO staff_logs(pid, name, out_time, in_time, duration, notes, date)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (str(pid or ""), name or "", out_time or "", in_time or "", duration or "", notes or "", date_str))
    conn.commit()
    conn.close()

#=============================================================
#=================================================================
def log_operation(chat_id: int, name: str, role: str, action: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO operations_log_telegram(chat_id, name, role, action)
        VALUES (%s, %s, %s, %s)
    """, (chat_id, name, role, action))
    conn.commit()
    conn.close()

def add_user_question(chat_id: int, question: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO questions_userbot (chat_id, question, answer, sent) 
        VALUES (%s, %s, %s, %s)
    """, (chat_id, question.strip(), "", False))
    conn.commit()
    conn.close()

def update_user_question_answer(qid: int, answer: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        UPDATE questions_userbot 
        SET answer = %s, answered_at = NOW(), sent = FALSE
        WHERE id = %s
    """, (answer.strip(), qid))
    conn.commit()
    conn.close()

def get_answer_for_question(question: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT answer FROM questions_userbot 
        WHERE LOWER(question) = LOWER(%s) AND answer <> ''
    """, (question.strip(),))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else None

def get_unsent_answers():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, chat_id, question, answer 
        FROM questions_userbot 
        WHERE answer <> '' AND sent = FALSE
    """)
    rows = cur.fetchall()
    conn.close()
    return rows

def mark_answer_sent(qid: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        UPDATE questions_userbot 
        SET sent = TRUE, chat_id = NULL 
        WHERE id = %s
    """, (qid,))
    conn.commit()
    conn.close()

#=================================
# ---------------- Q&A (questions_userbot) ----------------
def insert_question_answer(question: str, answer: str):
    """إضافة سؤال/جواب جديد"""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO questions_userbot (chat_id, question, answer, sent)
        VALUES (%s, %s, %s, %s)
    """, (0, question.strip(), answer.strip(), True))  # chat_id=0 لأن السؤال عام
    conn.commit()
    conn.close()


def get_all_questions():
    """إرجاع جميع الأسئلة/الأجوبة"""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id, question, answer FROM questions_userbot ORDER BY id")
    rows = cur.fetchall()
    conn.close()
    return rows


def delete_question(qid: int):
    """حذف سؤال/جواب بالـ ID"""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM questions_userbot WHERE id=%s", (qid,))
    conn.commit()
    conn.close()


def update_question_answer(qid: int, new_question: str, new_answer: str):
    """تحديث سؤال/جواب موجود"""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        UPDATE questions_userbot
        SET question=%s, answer=%s, answered_at=NOW()
        WHERE id=%s
    """, (new_question.strip(), new_answer.strip(), qid))
    conn.commit()
    conn.close()


def update_question_id(old_id: int, new_id: int):
    """تحديث رقم السؤال (لإعادة الترقيم إذا لزم)"""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE questions_userbot SET id=%s WHERE id=%s", (new_id, old_id))
    conn.commit()
    conn.close()

def get_unanswered_questions():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, chat_id, question 
        FROM questions_userbot
        WHERE COALESCE(answer, '') = ''
        ORDER BY id
    """)
    rows = cur.fetchall()
    conn.close()
    return rows

#   ==========  لادارة الطلبات
def insert_request(chat_id: int, service: str, user_name: str, branch: str,
                   grad_year: str, phone: str, notes: str) -> int:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO requests_userbot
        (chat_id, service, user_name, branch, grad_year, phone, notes, status)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id
    """, (chat_id, service, user_name, branch, grad_year, phone, notes, "انتظار الموافقة"))
    rid = cur.fetchone()[0]
    conn.commit()
    conn.close()
    return rid

def get_all_requests():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id, chat_id, service, user_name, branch, grad_year, phone, notes, status, pickup_date FROM requests_userbot ORDER BY id")
    rows = cur.fetchall()
    conn.close()
    return rows

def get_request_by_id(rid: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id, chat_id, service, user_name, branch, grad_year, phone, notes, status, staff_note, pickup_date FROM requests_userbot WHERE id=%s", (rid,))
    row = cur.fetchone()
    conn.close()
    return row

def update_request_status(rid: int, new_status: str, staff_note: str = None, pickup_date: str = None):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        UPDATE requests_userbot
        SET status=%s,
            staff_note=COALESCE(%s, staff_note),
            pickup_date=COALESCE(%s, pickup_date),
            updated_at=NOW(),
            notified=FALSE
        WHERE id=%s
    """, (new_status, staff_note, pickup_date, rid))
    conn.commit()
    conn.close()

def get_requests_for_chat(chat_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id, service, status, created_at FROM requests_userbot WHERE chat_id=%s ORDER BY id DESC", (chat_id,))
    rows = cur.fetchall()
    conn.close()
    return rows
