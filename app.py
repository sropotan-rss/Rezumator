import streamlit as st
import requests
import json
import os
import tempfile
import uuid
from io import BytesIO
from PyPDF2 import PdfReader
import docx
from fpdf import FPDF
import textwrap
import datetime
import time

st.set_page_config(page_title="RSS Job", layout="wide")

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
if not GROQ_API_KEY:
    st.error("❌ Добавь GROQ_API_KEY в Secrets")
    st.stop()

# ---------- Шрифт PDF ----------
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

# ---------- CSS (тёмная тема Сопровод) ----------
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Onest:wght@400;500;600;700&display=swap');
    html, body, [class*="css"] {
        font-family: 'Onest', sans-serif;
    }
    .stApp {
        background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
    }
    .main-header {
        font-size: 2.5rem;
        font-weight: 700;
        text-align: center;
        margin-bottom: 2rem;
        background: linear-gradient(to right, #38bdf8, #818cf8, #c084fc);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
    }
    .tool-card {
        background: rgba(30, 41, 59, 0.6);
        backdrop-filter: blur(10px);
        border: 1px solid rgba(255, 255, 255, 0.1);
        border-radius: 20px;
        padding: 2rem;
        text-align: center;
        transition: transform 0.2s, box-shadow 0.2s;
        cursor: pointer;
        height: 200px;
        display: flex;
        flex-direction: column;
        justify-content: center;
        align-items: center;
    }
    .tool-card:hover {
        transform: translateY(-5px) scale(1.02);
        box-shadow: 0 10px 25px rgba(0,0,0,0.3);
        border-color: rgba(56, 189, 248, 0.3);
    }
    .tool-card h3 {
        color: #f1f5f9;
        margin: 0;
        font-size: 1.3rem;
    }
    .tool-card p {
        color: #94a3b8;
        margin: 0.5rem 0 0;
    }
    .stButton>button {
        background: linear-gradient(135deg, #38bdf8, #818cf8);
        color: white;
        border-radius: 12px;
        font-weight: 600;
        border: none;
        padding: 0.5rem 1.5rem;
    }
    .stButton>button:hover {
        background: linear-gradient(135deg, #0ea5e9, #6366f1);
        transform: scale(1.02);
    }
    section[data-testid="stSidebar"] {
        background: rgba(15, 23, 42, 0.9);
        backdrop-filter: blur(10px);
        border-right: 1px solid rgba(255,255,255,0.1);
    }
</style>
""", unsafe_allow_html=True)

# ---------- Сессия ----------
query_params = st.experimental_get_query_params()
session_id = query_params.get("session", [None])[0]
if not session_id:
    new_id = str(uuid.uuid4())
    st.experimental_set_query_params(session=new_id)
    st.rerun()

if session_id not in st.session_state:
    st.session_state[session_id] = {
        "rules": [],
        "applications": [],
        "resume_original": "",
        "resume_improved": "",
        "page": "home"
    }
user_data = st.session_state[session_id]

# ---------- Счётчик IP ----------
@st.cache_resource
def get_visitor_set():
    return set()
visitors = get_visitor_set()
try:
    client_ip = requests.get("https://api.ipify.org?format=json", timeout=5).json()["ip"]
except:
    client_ip = "неизвестно"
visitors.add(client_ip)

# ---------- ИИ ----------
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
                last_err = f"Лимит (429). Попытка {attempt+1}/{retries}"
                time.sleep(5)
            else:
                last_err = f"Ошибка Groq {r.status_code}: {r.text[:200]}"
                break
        except Exception as e:
            last_err = f"Сеть: {e}"
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
    doc.add_heading('RSS Job', 0)
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

# ---------- ИИ-инструменты ----------
def ai_roast(resume_text):
    prompt = f"Проведи аудит резюме по 5 критериям (1-10): оформление, опыт, навыки, образование, ATS. Дай вердикт и советы.\nРезюме: {resume_text[:3000]}"
    return ask_ai(prompt, max_tokens=2000)

def ai_cover_letter(resume_text, job_desc):
    prompt = f"Напиши сопроводительное письмо (до 500 символов) для резюме и вакансии.\nРезюме: {resume_text[:2000]}\nВакансия: {job_desc[:1000]}"
    return ask_ai(prompt, max_tokens=800)

def ai_checklist():
    return "✅ Проверь контакты\n✅ Добавь ключевые слова\n✅ Укажи достижения с цифрами"

def ai_linkedin_audit():
    return "🔗 Добавь хэштеги, обнови 'Обо мне', получи рекомендации."

def ai_achievements(resume_text):
    prompt = f"Извлеки ключевые достижения из резюме и предложи, как их лучше описать.\nРезюме: {resume_text[:2000]}"
    return ask_ai(prompt, max_tokens=1000)

def ai_radars():
    return "📡 Мониторинг вакансий — в разработке"

def ai_market():
    return "📊 Средняя зарплата COO — 270 000 ₽"

# ---------- Страницы инструментов ----------
def show_tool_page(title, func, *args, **kwargs):
    st.markdown(f'<h1 class="main-header">{title}</h1>', unsafe_allow_html=True)
    if st.button("← Назад ко всем инструментам"):
        user_data["page"] = "home"
        st.rerun()
    func(*args, **kwargs)

def tool_resume():
    st.markdown("### 📄 Загрузка резюме")
    uploaded = st.file_uploader("Загрузите PDF/DOCX/TXT", type=["pdf","docx","txt"])
    if uploaded:
        file_bytes = uploaded.read()
        if uploaded.type == "application/pdf":
            user_data["resume_original"] = extract_text_from_pdf(file_bytes)
        elif uploaded.type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
            user_data["resume_original"] = extract_text_from_docx(file_bytes)
        else:
            user_data["resume_original"] = file_bytes.decode("utf-8")
        st.success("Резюме загружено!")
    if user_data["resume_original"]:
        with st.expander("Исходный текст"):
            st.text(user_data["resume_original"][:1000])
        if st.button("✨ Улучшить резюме"):
            with st.spinner("ИИ работает..."):
                improved = ask_ai(f"Улучши резюме: {user_data['resume_original'][:3000]}", max_tokens=1500)
            if not improved.startswith("[ОШИБКА"):
                user_data["resume_improved"] = improved
                st.download_button("📥 DOCX", create_docx(improved), "rss_job_resume.docx")
                st.download_button("📥 PDF", create_pdf(improved), "rss_job_resume.pdf")
            else:
                st.error(improved)

def tool_audit():
    st.markdown("### 🔥 Аудит резюме")
    if user_data["resume_original"]:
        if st.button("Запустить аудит"):
            with st.spinner("Анализируем..."):
                result = ai_roast(user_data["resume_original"])
            st.write(result)
    else:
        st.warning("Сначала загрузите резюме")

def tool_vacancies():
    st.markdown("### 🔍 Поиск вакансий (hh.ru)")
    query = st.text_input("Ключевые слова")
    area = st.selectbox("Регион", [("РФ",113),("Москва",1),("СПб",2)], format_func=lambda x: x[0])
    if st.button("Найти"):
        vacs = search_hh_vacancies(query, area[1])
        if vacs:
            for v in vacs[:10]:
                with st.expander(f"{v['name']} — {v['employer']['name'] if v.get('employer') else ''}"):
                    desc = v.get("snippet",{}).get("requirement","") + " " + v.get("snippet",{}).get("responsibility","")
                    st.write(desc[:300])
                    st.markdown(f"[Открыть на hh.ru]({v.get('alternate_url')})")
        else:
            st.warning("Ничего не найдено")

def tool_applications():
    st.markdown("### 📨 Мои отклики")
    if not user_data["applications"]:
        st.info("Нет откликов")
    else:
        for i, app in enumerate(user_data["applications"]):
            with st.expander(f"{app['title']} — {app['employer']} ({app['status']})"):
                st.write(app.get("description",""))
                if app.get("letter"):
                    st.code(app["letter"])
                st.markdown(f"[Открыть на hh.ru]({app['url']})")
                col1, col2, col3 = st.columns(3)
                if col1.button("Отправил", key=f"sent_{i}"):
                    app["status"] = "Отправлен"
                    st.rerun()
                if col2.button("Повторить", key=f"rep_{i}"):
                    app["status"] = "Повтор"
                    st.rerun()
                if col3.button("Пропустить", key=f"skip_{i}"):
                    app["status"] = "Пропущен"
                    st.rerun()

def tool_cover_letter():
    st.markdown("### ✉️ Сопроводительное письмо")
    job_desc = st.text_area("Описание вакансии")
    if st.button("Сгенерировать"):
        if user_data["resume_original"] and job_desc:
            with st.spinner("..."):
                letter = ai_cover_letter(user_data["resume_original"], job_desc)
            st.code(letter)
        else:
            st.warning("Нужны резюме и описание вакансии")

def tool_checklist():
    st.write(ai_checklist())

def tool_linkedin_audit():
    st.write(ai_linkedin_audit())

def tool_achievements():
    if user_data["resume_original"]:
        if st.button("Проанализировать достижения"):
            with st.spinner("..."):
                result = ai_achievements(user_data["resume_original"])
            st.write(result)
    else:
        st.warning("Нужно резюме")

def tool_market():
    st.write(ai_market())

def tool_radars():
    st.write(ai_radars())

def tool_settings():
    st.write("⚙️ Настройки (в разработке)")

# ---------- Главная: карточки инструментов ----------
def home_page():
    st.markdown('<h1 class="main-header">Инструменты RSS Job</h1>', unsafe_allow_html=True)
    tools = [
        ("📄 Резюме", "Загрузка и AI-улучшение"),
        ("🔥 Аудит", "Оценка резюме по 5 критериям"),
        ("🔍 Вакансии", "Поиск на hh.ru"),
        ("📨 Отклики", "Очередь откликов"),
        ("✉️ Письмо", "Генерация сопроводительного"),
        ("✅ Чек-лист", "Что проверить перед откликом"),
        ("🔗 LinkedIn", "Аудит профиля"),
        ("🏆 Достижения", "Анализ достижений"),
        ("📊 Рынок", "Аналитика зарплат"),
        ("📡 Радары", "Мониторинг вакансий"),
        ("⚙️ Настройки", "Управление аккаунтом"),
    ]
    cols = st.columns(3)
    for i, (name, desc) in enumerate(tools):
        with cols[i % 3]:
            card_html = f"""
            <div class="tool-card">
                <h3>{name}</h3>
                <p>{desc}</p>
            </div>
            """
            st.markdown(card_html, unsafe_allow_html=True)
            if st.button(name, key=f"tool_{i}"):
                user_data["page"] = name.split(" ")[0]
                st.rerun()

# ---------- Боковая панель ----------
with st.sidebar:
    st.markdown("## 🚀 RSS Job")
    st.caption(f"🆔 ...{session_id[-8:]}")
    st.metric("👥 Уникальных IP", len(visitors))
    if st.button("🏠 Главная"):
        user_data["page"] = "home"
        st.rerun()

# ---------- Роутинг ----------
page = user_data.get("page", "home")
if page == "home":
    home_page()
else:
    pages = {
        "📄": lambda: show_tool_page("📄 Резюме", tool_resume),
        "🔥": lambda: show_tool_page("🔥 Аудит резюме", tool_audit),
        "🔍": lambda: show_tool_page("🔍 Поиск вакансий", tool_vacancies),
        "📨": lambda: show_tool_page("📨 Мои отклики", tool_applications),
        "✉️": lambda: show_tool_page("✉️ Сопроводительное письмо", tool_cover_letter),
        "✅": lambda: show_tool_page("✅ Чек-лист", tool_checklist),
        "🔗": lambda: show_tool_page("🔗 LinkedIn аудит", tool_linkedin_audit),
        "🏆": lambda: show_tool_page("🏆 Достижения", tool_achievements),
        "📊": lambda: show_tool_page("📊 Рынок", tool_market),
        "📡": lambda: show_tool_page("📡 Радары", tool_radars),
        "⚙️": lambda: show_tool_page("⚙️ Настройки", tool_settings),
    }
    pages.get(page, lambda: home_page())()
