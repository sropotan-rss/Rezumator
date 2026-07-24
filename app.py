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

st.set_page_config(page_title="RSS job", layout="wide")

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
if not GROQ_API_KEY:
    st.error("❌ Добавь GROQ_API_KEY в Secrets")
    st.stop()

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

# ---------- CSS ----------
st.markdown("""
<style>
    .main-header { font-size: 2rem; font-weight: 700; color: #1E3A8A; }
    .stButton>button {
        background-color: #F97316;
        color: white;
        border-radius: 8px;
        font-weight: 600;
        border: none;
        padding: 0.5rem 1.5rem;
    }
    .stButton>button:hover { background-color: #EA580C; }
</style>
""", unsafe_allow_html=True)

# ---------- Сессия и локальная авторизация ----------
if "user" not in st.session_state:
    st.session_state.user = None
if "users" not in st.session_state:
    st.session_state.users = {}

def login(email, password):
    users = st.session_state.users
    if email in users and users[email] == password:
        st.session_state.user = email
        return True
    return False

def register(email, password):
    users = st.session_state.users
    if email in users:
        return False
    users[email] = password
    st.session_state.users = users
    st.session_state.user = email
    return True

def logout():
    st.session_state.user = None
    st.rerun()

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
                last_err = f"Лимит запросов (429). Попытка {attempt+1}/{retries}"
                time.sleep(5)
            else:
                last_err = f"Ошибка Groq {r.status_code}: {r.text[:200]}"
                break
        except Exception as e:
            last_err = f"Сетевая ошибка: {e}"
            time.sleep(2)
    return f"[ОШИБКА] {last_err}"

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

# ---------- ИИ-функции разделов ----------
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
def main():
    user = st.session_state.user
    st.sidebar.markdown(f"👤 {user}")
    menu = st.sidebar.radio("Меню", [
        "🏠 Платформа",
        "🔍 Вакансии",
        "📨 Отклики",
        "📄 Резюме",
        "🔥 Аудит",
        "✉️ Письмо",
        "✅ Чек-лист",
        "🔗 LinkedIn аудит",
        "🏆 Достижения",
        "📊 Рынок",
        "📡 Радары",
        "⚙️ Настройки"
    ], label_visibility="collapsed")
    if st.sidebar.button("Выйти"):
        logout()

    user_data = st.session_state.setdefault(user, {
        "rules": [], "applications": [],
        "resume_original": "", "resume_improved": ""
    })

    if menu == "🏠 Платформа":
        st.header("Платформа")
        col1, col2, col3 = st.columns(3)
        col1.metric("Правил", len(user_data["rules"]))
        col2.metric("Откликов", len(user_data["applications"]))
        col3.metric("Резюме", "Загружено" if user_data["resume_original"] else "Нет")
        st.subheader("Последние отклики")
        for app in user_data["applications"][-5:]:
            st.write(f"📌 {app['title']} — {app['employer']} ({app['status']})")

    elif menu == "🔍 Вакансии":
        st.header("Поиск вакансий (hh.ru)")
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

    elif menu == "📨 Отклики":
        st.header("Мои отклики")
        if not user_data["applications"]:
            st.info("Нет откликов")
        else:
            for i, app in enumerate(user_data["applications"]):
                with st.expander(f"{app['title']} — {app['employer']} ({app['status']})"):
                    st.write(app["description"])
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

    elif menu == "📄 Резюме":
        st.header("Моё резюме")
        uploaded = st.file_uploader("Загрузить PDF/DOCX/TXT", type=["pdf","docx","txt"])
        if uploaded:
            file_bytes = uploaded.read()
            if uploaded.type == "application/pdf":
                user_data["resume_original"] = extract_text_from_pdf(file_bytes)
            elif uploaded.type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
                user_data["resume_original"] = extract_text_from_docx(file_bytes)
            else:
                user_data["resume_original"] = file_bytes.decode("utf-8")
            st.success("Загружено!")
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

    elif menu == "🔥 Аудит":
        st.header("Аудит резюме (Roast)")
        if user_data["resume_original"]:
            if st.button("Запустить аудит"):
                with st.spinner("Анализируем..."):
                    result = ai_roast(user_data["resume_original"])
                st.write(result)
        else:
            st.warning("Сначала загрузите резюме")

    elif menu == "✉️ Письмо":
        st.header("Сопроводительное письмо")
        job_desc = st.text_area("Описание вакансии")
        if st.button("Сгенерировать"):
            if user_data["resume_original"] and job_desc:
                with st.spinner("..."):
                    letter = ai_cover_letter(user_data["resume_original"], job_desc)
                st.code(letter)
            else:
                st.warning("Нужны резюме и описание вакансии")

    elif menu == "✅ Чек-лист":
        st.header("Чек-лист перед откликом")
        st.write(ai_checklist())

    elif menu == "🔗 LinkedIn аудит":
        st.header("Аудит LinkedIn профиля")
        st.write(ai_linkedin_audit())

    elif menu == "🏆 Достижения":
        st.header("Мои достижения")
        if user_data["resume_original"]:
            if st.button("Проанализировать достижения"):
                with st.spinner("..."):
                    result = ai_achievements(user_data["resume_original"])
                st.write(result)
        else:
            st.warning("Нужно резюме")

    elif menu == "📊 Рынок":
        st.header("Аналитика рынка")
        st.write(ai_market())

    elif menu == "📡 Радары":
        st.header("Радары вакансий")
        st.write(ai_radars())

    elif menu == "⚙️ Настройки":
        st.header("Настройки аккаунта")
        st.write("Здесь будут настройки профиля, уведомлений и т.д.")

# ---------- Экран входа ----------
def auth_screen():
    st.title("🔐 RSS job")
    choice = st.radio("", ["Вход", "Регистрация"])
    email = st.text_input("Email")
    password = st.text_input("Пароль", type="password")
    if choice == "Вход":
        if st.button("Войти"):
            if login(email, password):
                st.success("Добро пожаловать!")
                st.rerun()
            else:
                st.error("Неверный email или пароль")
    else:
        if st.button("Зарегистрироваться"):
            if register(email, password):
                st.success("Регистрация успешна!")
                st.rerun()
            else:
                st.error("Этот email уже используется")

if st.session_state.user:
    main()
else:
    auth_screen()
