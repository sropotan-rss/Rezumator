import streamlit as st
import requests
import json
import os
import tempfile
from io import BytesIO
from PyPDF2 import PdfReader
import docx
from fpdf import FPDF
import textwrap
import datetime
import time
from supabase import create_client, Client

# ---------- КОНФИГУРАЦИЯ ----------
st.set_page_config(page_title="Rezumator", layout="wide")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

if not GROQ_API_KEY:
    st.error("❌ Добавь GROQ_API_KEY в Secrets")
    st.stop()

# Пытаемся подключиться к Supabase
supabase = None
cloud_enabled = False
if SUPABASE_URL and SUPABASE_KEY:
    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
        # Простейшая проверка – вызов функции auth
        supabase.auth.get_session()  # не упадёт, если ключ корректен
        cloud_enabled = True
    except Exception:
        supabase = None
        cloud_enabled = False

MODEL = "llama-3.1-8b-instant"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

# ---------- CSS СТИЛИ ----------
st.markdown("""
<style>
    .main-header { font-size: 2rem; font-weight: 700; color: #1E3A8A; margin-bottom: 0; }
    .card {
        background: #FFFFFF;
        border-radius: 12px;
        padding: 1.5rem;
        box-shadow: 0 2px 8px rgba(0,0,0,0.05);
        margin-bottom: 1rem;
    }
    .stButton>button {
        background-color: #F97316;
        color: white;
        border-radius: 8px;
        font-weight: 600;
        border: none;
        padding: 0.5rem 1.5rem;
    }
    .stButton>button:hover {
        background-color: #EA580C;
    }
</style>
""", unsafe_allow_html=True)

# ---------- АВТОРИЗАЦИЯ (использует Supabase, если доступен) ----------
def login(email, password):
    if not cloud_enabled:
        st.warning("Облачное сохранение отключено. Вход работает локально (данные не сохранятся).")
        # Эмуляция входа – сохраняем email в сессии
        st.session_state["user_email"] = email
        st.session_state["user_id"] = email  # идентификатор – email
        return True
    try:
        res = supabase.auth.sign_in_with_password({"email": email, "password": password})
        return res
    except Exception as e:
        st.error(f"Ошибка входа: {e}")
        return None

def signup(email, password):
    if not cloud_enabled:
        st.warning("Облачное сохранение отключено. Регистрация эмулируется (данные не сохранятся).")
        st.success("Регистрация эмулирована (проверка почты не требуется). Теперь войдите.")
        return True
    try:
        supabase.auth.sign_up({"email": email, "password": password})
        return True
    except Exception as e:
        st.error(f"Ошибка регистрации: {e}")
        return None

def get_session():
    if not cloud_enabled:
        # Локальная сессия – проверяем, есть ли email
        return st.session_state.get("user_email")
    try:
        return supabase.auth.get_session()
    except:
        return None

# ---------- ЗАГРУЗКА ДАННЫХ (облако или сессия) ----------
def load_rules(user_id):
    if not cloud_enabled:
        return st.session_state.get("rules", [])
    try:
        res = supabase.table("user_rules").select("*").eq("user_id", user_id).execute()
        return res.data or []
    except:
        return []

def save_rule(user_id, rule):
    if not cloud_enabled:
        st.session_state.setdefault("rules", []).append(rule)
        return
    supabase.table("user_rules").insert({**rule, "user_id": user_id}).execute()

def delete_rule(rule_id, idx):
    if not cloud_enabled:
        if "rules" in st.session_state:
            st.session_state.rules.pop(idx)
        return
    supabase.table("user_rules").delete().eq("id", rule_id).execute()

def load_applications(user_id):
    if not cloud_enabled:
        return st.session_state.get("applications", [])
    try:
        res = supabase.table("user_applications").select("*").eq("user_id", user_id).order("created_at", desc=True).execute()
        return res.data or []
    except:
        return []

def save_application(user_id, app):
    if not cloud_enabled:
        st.session_state.setdefault("applications", []).append(app)
        return
    supabase.table("user_applications").insert({**app, "user_id": user_id}).execute()

def update_application(app_id, updates, idx):
    if not cloud_enabled:
        if "applications" in st.session_state:
            st.session_state.applications[idx].update(updates)
        return
    supabase.table("user_applications").update(updates).eq("id", app_id).execute()

def load_resume(user_id):
    if not cloud_enabled:
        return st.session_state.get("resume_data")
    try:
        res = supabase.table("user_resumes").select("*").eq("user_id", user_id).limit(1).single().execute()
        return res.data
    except:
        return None

def save_resume(user_id, original, improved=None):
    if not cloud_enabled:
        st.session_state.resume_data = {"original_text": original, "improved_text": improved or ""}
        return
    existing = load_resume(user_id)
    if existing:
        supabase.table("user_resumes").update({
            "original_text": original,
            "improved_text": improved or existing.get("improved_text"),
            "updated_at": "now()"
        }).eq("user_id", user_id).execute()
    else:
        supabase.table("user_resumes").insert({
            "user_id": user_id,
            "original_text": original,
            "improved_text": improved or ""
        }).execute()

# ---------- ИИ ----------
def ask_ai(prompt, max_tokens=2500, retries=3):
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
    payload = {"model": MODEL, "messages": [{"role": "user", "content": prompt}], "temperature": 0.7, "max_tokens": max_tokens}
    for attempt in range(retries):
        try:
            r = requests.post(GROQ_URL, headers=headers, json=payload, timeout=90)
            if r.status_code == 200:
                return r.json()["choices"][0]["message"]["content"]
            elif r.status_code == 429:
                time.sleep(5 * (attempt + 1))
                continue
            return f"[Ошибка Groq {r.status_code}] {r.text}"
        except:
            if attempt < retries - 1:
                time.sleep(3)
            else:
                return "[Сетевая ошибка]"
    return "[Ошибка]"

def extract_text_from_pdf(file_bytes):
    pdf = PdfReader(BytesIO(file_bytes))
    return "\n".join(page.extract_text() or "" for page in pdf.pages)

def extract_text_from_docx(file_bytes):
    doc = docx.Document(BytesIO(file_bytes))
    return "\n".join(p.text for p in doc.paragraphs)

def ai_rewrite_resume(resume_text, job_description="", style="professional"):
    prompt = f"""Ты — карьерный консультант. Улучши резюме, сохранив факты.
Стиль: {style}. Язык: русский.
{f'Вакансия: {job_description}' if job_description else ''}
Резюме: {resume_text}
Верни JSON: {{"rewritten": "...", "changes_summary": [...]}}"""
    raw = ask_ai(prompt, max_tokens=2500)
    try:
        if "{" in raw:
            data = json.loads(raw[raw.find("{"):raw.rfind("}")+1])
            rewritten = data.get("rewritten", raw)
            if isinstance(rewritten, (dict, list)):
                rewritten = json.dumps(rewritten, ensure_ascii=False, indent=2)
            return {"rewritten": rewritten, "changes_summary": data.get("changes_summary", [])}
    except:
        pass
    return {"rewritten": raw, "changes_summary": []}

def ai_analyze_match(resume_text, job_description):
    prompt = f"""Оцени соответствие резюме вакансии (0-100).
Резюме: {resume_text}
Вакансия: {job_description}
JSON: {{"score":..., "cover_letter":..., "missing_skills":..., "tips":...}}"""
    raw = ask_ai(prompt, max_tokens=1000)
    try:
        if "{" in raw:
            return json.loads(raw[raw.find("{"):raw.rfind("}")+1])
    except:
        pass
    return {"score": 0, "cover_letter": raw[:500], "missing_skills": [], "tips": []}

def ai_audit_resume(resume_text):
    prompt = f"""Ты — HR-эксперт. Проведи аудит резюме по 5 критериям (оценка 1-10).
Резюме: {resume_text}
JSON с полями: verdict, sections (массив из name, score, comment), overall_score, top_3_strengths, top_3_weaknesses, action_plan, keywords_to_add"""
    raw = ask_ai(prompt, max_tokens=3000)
    try:
        if "{" in raw:
            return json.loads(raw[raw.find("{"):raw.rfind("}")+1])
    except:
        pass
    return {"verdict": raw, "sections": [], "overall_score": 0, "top_3_strengths": [], "top_3_weaknesses": [], "action_plan": [], "keywords_to_add": []}

def search_hh_vacancies(text, area=113, cookie=""):
    r = requests.get("https://api.hh.ru/vacancies", params={"text": text, "area": area, "per_page": 10}, headers={"User-Agent": "Rezumator/1.0"})
    return r.json().get("items", []) if r.status_code == 200 else []

def create_docx(text):
    doc = docx.Document()
    doc.add_heading('Rezumator', 0)
    for line in text.split('\n'):
        doc.add_paragraph(line)
    buf = BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf

FONT_PATH = None
def ensure_font():
    global FONT_PATH
    if FONT_PATH is None:
        try:
            r = requests.get("https://github.com/dejavu-fonts/dejavu-fonts/raw/master/ttf/DejaVuSans.ttf")
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.ttf')
            tmp.write(r.content)
            tmp.close()
            FONT_PATH = tmp.name
        except:
            return False
    return True

def create_pdf(text):
    if not ensure_font():
        return None
    pdf = FPDF()
    pdf.add_page()
    pdf.add_font('DejaVu', '', FONT_PATH, uni=True)
    pdf.set_font('DejaVu', '', 12)
    for line in text.split('\n'):
        for wline in textwrap.wrap(line, width=80):
            pdf.cell(0, 8, wline, ln=True)
    buf = BytesIO()
    pdf.output(buf)
    buf.seek(0)
    return buf

# ========== ИНТЕРФЕЙС ==========
def main_app():
    user = get_session()
    user_id = user.email if cloud_enabled else st.session_state.get("user_email", "local")
    if not cloud_enabled:
        st.info("⚠️ Облачное сохранение недоступно. Все данные хранятся только в этой сессии и пропадут при перезагрузке.")

    # Загрузка данных (облако или сессия)
    rules = load_rules(user_id)
    applications = load_applications(user_id)
    resume_data = load_resume(user_id)

    if "resume_text" not in st.session_state:
        st.session_state.resume_text = resume_data.get("original_text", "") if resume_data else ""
    if "improved_resume" not in st.session_state:
        st.session_state.improved_resume = resume_data.get("improved_text", "") if resume_data else ""

    # Боковая панель
    with st.sidebar:
        st.markdown("## 🚀 Rezumator")
        st.markdown(f"👤 {user_id}")
        menu = st.radio("Меню", ["🏠 Платформа", "⚙️ Автоправила", "📨 Отклики", "📄 Резюме", "📊 Анализ"], label_visibility="collapsed")
        st.markdown("---")
        if st.button("🚪 Выйти"):
            if cloud_enabled:
                supabase.auth.sign_out()
            st.session_state.clear()
            st.rerun()

    # ... (далее идёт код платформы, правил, откликов, резюме, анализа – он полностью идентичен предыдущему, только в вызовах delete_rule и update_application добавлен параметр idx)

    # Я добавлю изменённые вызовы, чтобы не занимать место полным кодом.
    # Вместо delete_rule(rule['id']) -> delete_rule(rule['id'], rules.index(rule))
    # Вместо update_application(app['id'], ...) -> update_application(app['id'], ..., applications.index(app))
