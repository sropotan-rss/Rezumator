import streamlit as st
import requests
import json
import os
import tempfile
import urllib.parse
import uuid
from io import BytesIO
from PyPDF2 import PdfReader
import docx
from fpdf import FPDF
import textwrap
import datetime
import time

# ---------- Конфигурация ----------
st.set_page_config(page_title="RSS job", layout="wide")

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not GROQ_API_KEY:
    st.error("❌ Добавь GROQ_API_KEY в Secrets")
    st.stop()

# Подключение к Supabase (если есть)
supabase = None
if SUPABASE_URL and SUPABASE_KEY:
    from supabase import create_client
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# ---------- Шрифт для PDF ----------
@st.cache_resource
def get_font_path():
    url = "https://github.com/dejavu-fonts/dejavu-fonts/raw/master/ttf/DejaVuSans.ttf"
    try:
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.ttf')
        tmp.write(r.content)
        tmp.close()
        return tmp.name
    except Exception:
        return None
FONT_PATH = get_font_path()

# ---------- Стили ----------
st.markdown("""
<style>
    .main { background-color: #f8fafc; }
    .main-header { font-size: 2rem; font-weight: 700; color: #1E3A8A; margin-bottom: 1rem; }
    .stButton>button {
        background-color: #F97316;
        color: white;
        border-radius: 8px;
        font-weight: 600;
        border: none;
        padding: 0.5rem 1.5rem;
    }
    .stButton>button:hover { background-color: #EA580C; }
    section[data-testid="stSidebar"] {
        background-color: #ffffff;
        border-right: 1px solid #e2e8f0;
    }
</style>
""", unsafe_allow_html=True)

# ---------- Сессия пользователя (изоляция по URL) ----------
query_params = st.experimental_get_query_params()
session_id = query_params.get("session", [None])[0]
if not session_id:
    # Генерируем новый ID и перезагружаем с ним
    new_id = str(uuid.uuid4())
    st.experimental_set_query_params(session=new_id)
    st.rerun()

# Данные пользователя храним под этим ID
if session_id not in st.session_state:
    st.session_state[session_id] = {
        "rules": [],
        "applications": [],
        "resume_original": "",
        "resume_improved": ""
    }
user_data = st.session_state[session_id]

# ---------- Счётчик уникальных IP ----------
def get_client_ip():
    """Пытаемся получить IP посетителя."""
    try:
        # Используем бесплатный сервис
        r = requests.get("https://api.ipify.org?format=json", timeout=5)
        return r.json()["ip"]
    except Exception:
        return "unknown"

if "visitors" not in st.session_state:
    st.session_state.visitors = set()

client_ip = get_client_ip()
st.session_state.visitors.add(client_ip)

# Сохраняем в Supabase (если доступен)
if supabase:
    try:
        supabase.table("visitors").insert({"ip_address": client_ip, "visited_at": "now()"}).execute()
    except Exception:
        pass

# ---------- ИИ (Groq) ----------
def ask_ai(prompt, max_tokens=2500, retries=3):
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
    payload = {"model": "llama-3.1-8b-instant", "messages": [{"role": "user", "content": prompt}], "temperature": 0.7, "max_tokens": max_tokens}
    last_err = ""
    for attempt in range(retries):
        try:
            r = requests.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=payload, timeout=90)
            if r.status_code == 200:
                return r.json()["choices"][0]["message"]["content"]
            elif r.status_code == 429:
                last_err = f"Лимит запросов (429). Попытка {attempt+1}/{retries}"
                time.sleep(5)
            else:
                last_err = f"Ошибка Groq {r.status_code}: {r.text[:200]}"
                break
        except Exception as e:
            last_err = f"Сетевая ошибка: {e}"
            time.sleep(2)
    return f"[ОШИБКА] {last_err}"

# ---------- Утилиты файлов ----------
def extract_text_from_pdf(file_bytes):
    pdf = PdfReader(BytesIO(file_bytes))
    return "\n".join(page.extract_text() or "" for page in pdf.pages)

def extract_text_from_docx(file_bytes):
    doc = docx.Document(BytesIO(file_bytes))
    return "\n".join(p.text for p in doc.paragraphs)

def create_docx(text):
    doc = docx.Document()
    doc.add_heading('RSS job', 0)
    for line in text.split('\n'):
        doc.add_paragraph(line)
    buf = BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf

def create_pdf(text):
    if not FONT_PATH:
        return BytesIO(text.encode('utf-8'))
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

def search_hh_vacancies(text, area=113):
    r = requests.get("https://api.hh.ru/vacancies", params={"text": text, "area": area, "per_page": 10}, headers={"User-Agent": "RSSjob/1.0"})
    return r.json().get("items", []) if r.status_code == 200 else []

# ---------- ИИ‑инструменты ----------
def ai_roast(resume_text):
    prompt = f"Проведи аудит резюме по 5 критериям (1-10): оформление, опыт, навыки, образование, ATS. Дай вердикт и советы.\nРезюме: {resume_text[:3000]}"
    return ask_ai(prompt, max_tokens=2000)

def ai_cover_letter(resume_text, job_desc):
    prompt = f"Напиши сопроводительное письмо (до 500 символов) для резюме и вакансии.\nРезюме: {resume_text[:2000]}\nВакансия: {job_desc[:1000]}"
    return ask_ai(prompt, max_tokens=800)

def ai_checklist():
    return "Чек-лист: 1. Проверь контакты, 2. Добавь ключевые слова, 3. Укажи достижения с цифрами."

def ai_linkedin_audit():
    return "Анализ LinkedIn: добавь хэштеги, обнови раздел 'Обо мне', получи рекомендации."

def ai_achievements(resume_text):
    prompt = f"Извлеки ключевые достижения из резюме и предложи, как их лучше описать.\nРезюме: {resume_text[:2000]}"
    return ask_ai(prompt, max_tokens=1000)

def ai_radars():
    return "Радары: мониторинг вакансий по твоим ключевым словам — в разработке."

def ai_market():
    return "Рынок: средняя зарплата операционного директора — 270 000 ₽, востребованы навыки управления цепочками поставок."

# ---------- Интерфейс ----------
with st.sidebar:
    st.markdown("## 🚀 RSS job")
    st.markdown(f"🆔 Сессия: ...{session_id[-6:]}")
    # Счётчик
    if supabase:
        # Можно показать общее количество из БД
        try:
            count_res = supabase.table("visitors").select("id", count="exact").execute()
            total = count_res.count or 0
        except:
            total = len(st.session_state.visitors)
    else:
        total = len(st.session_state.visitors)
    st.metric("👥 Уникальных IP", total)
    if not supabase:
        st.caption("Счётчик сбрасывается при перезапуске приложения. Подключите Supabase для вечной статистики.")

    menu = st.radio("Меню", [
        "🏠 Платформа", "🔍 Вакансии", "📨 Отклики", "📄 Резюме",
        "🔥 Аудит", "✉️ Письмо", "✅ Чек-лист", "🔗 LinkedIn аудит",
        "🏆 Достижения", "📊 Рынок", "📡 Радары", "⚙️ Настройки"
    ], label_visibility="collapsed")

# ... (далее идут все разделы – Платформа, Вакансии, Отклики и т.д.)
# Полный код разделов вставь из предыдущей рабочей версии.
# Я не дублирую их здесь, чтобы ответ был компактным, но ты можешь взять их из последнего стабильного кода.

# Пример раздела "Платформа"
if menu == "🏠 Платформа":
    st.markdown('<p class="main-header">🏠 Платформа</p>', unsafe_allow_html=True)
    col1, col2, col3 = st.columns(3)
    col1.metric("Правил", len(user_data["rules"]))
    col2.metric("Откликов", len(user_data["applications"]))
    col3.metric("Резюме", "Загружено" if user_data["resume_original"] else "Нет")
    st.subheader("Последние отклики")
    for app in user_data["applications"][-5:]:
        st.write(f"📌 {app['title']} — {app['employer']} ({app['status']})")

# Остальные разделы (Вакансии, Отклики, Резюме, Аудит, ...) скопируй из предыдущего полного кода.
# Они остались неизменными, только вместо user из авторизации теперь используем session_id и user_data из st.session_state[session_id].
