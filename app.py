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

st.set_page_config(page_title="Rezumator", layout="wide")

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
if not GROQ_API_KEY:
    st.error("❌ Добавь GROQ_API_KEY в Secrets")
    st.stop()

MODEL = "llama-3.1-8b-instant"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

# ---------- Загрузка шрифта (с кэшированием) ----------
@st.cache_resource
def get_font_path():
    """Загружает DejaVuSans.ttf один раз за сессию."""
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
    .main-header { font-size: 2rem; font-weight: 700; color: #1E3A8A; margin-bottom: 0; }
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

# ---------- Локальная авторизация ----------
def login(email, password):
    users = st.session_state.get("users", {})
    if email in users and users[email] == password:
        st.session_state.user = email
        return True
    return False

def register(email, password):
    users = st.session_state.get("users", {})
    if email in users:
        return False
    users[email] = password
    st.session_state.users = users
    st.session_state.user = email
    return True

def logout():
    st.session_state.pop("user", None)
    st.rerun()

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
                time.sleep(5)
                continue
            return f"[Ошибка Groq {r.status_code}] {r.text}"
        except Exception:
            time.sleep(2)
    return "[Ошибка]"

def extract_text_from_pdf(file_bytes):
    pdf = PdfReader(BytesIO(file_bytes))
    return "\n".join(page.extract_text() or "" for page in pdf.pages)

def extract_text_from_docx(file_bytes):
    doc = docx.Document(BytesIO(file_bytes))
    return "\n".join(p.text for p in doc.paragraphs)

def ai_rewrite_resume(resume_text, job="", style="professional"):
    prompt = f"""Улучши резюме. Стиль: {style}. Язык: русский.
{f'Вакансия: {job}' if job else ''}
Резюме: {resume_text}
JSON: {{"rewritten": "текст", "changes_summary": ["изменение1"]}}"""
    raw = ask_ai(prompt)
    try:
        if "{" in raw:
            d = json.loads(raw[raw.find("{"):raw.rfind("}")+1])
            return {"rewritten": d.get("rewritten", raw), "changes_summary": d.get("changes_summary", [])}
    except:
        pass
    return {"rewritten": raw, "changes_summary": []}

def ai_analyze_match(resume_text, job_desc):
    prompt = f"""Оцени соответствие (0-100). Резюме: {resume_text}. Вакансия: {job_desc}
JSON: {{"score": число, "cover_letter": "письмо", "missing_skills": [], "tips": []}}"""
    raw = ask_ai(prompt, max_tokens=1000)
    try:
        if "{" in raw:
            return json.loads(raw[raw.find("{"):raw.rfind("}")+1])
    except:
        pass
    return {"score": 0, "cover_letter": raw[:500], "missing_skills": [], "tips": []}

def ai_audit_resume(resume_text):
    prompt = f"""Аудит резюме по 5 критериям (1-10).
Резюме: {resume_text}
JSON: {{"verdict": "...", "sections": [{{"name": "...", "score": N, "comment": "..."}}], "overall_score": N, "top_3_strengths": [...], "top_3_weaknesses": [...], "action_plan": [...], "keywords_to_add": [...]}}"""
    raw = ask_ai(prompt, max_tokens=3000)
    try:
        if "{" in raw:
            return json.loads(raw[raw.find("{"):raw.rfind("}")+1])
    except:
        pass
    return {"verdict": raw, "sections": [], "overall_score": 0, "top_3_strengths": [], "top_3_weaknesses": [], "action_plan": [], "keywords_to_add": []}

def search_hh_vacancies(text, area=113):
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

def create_pdf(text):
    """Создаёт PDF с поддержкой кириллицы (если шрифт загрузился)."""
    if not FONT_PATH:
        # fallback: сохраняем как текст
        return BytesIO(text.encode('utf-8'))
    pdf = FPDF()
    pdf.add_page()
    pdf.add_font('DejaVu', '', FONT_PATH, uni=True)
    pdf.set_font('DejaVu', '', 12)
    for line in text.split('\n'):
        wrapped = textwrap.wrap(line, width=80)
        for wline in wrapped:
            pdf.cell(0, 8, wline, ln=True)
    buf = BytesIO()
    pdf.output(buf)
    buf.seek(0)
    return buf

# ---------- ОСНОВНОЙ ИНТЕРФЕЙС ----------
def main():
    user = st.session_state.user
    st.sidebar.markdown(f"👤 {user}")
    menu = st.sidebar.radio("Меню", ["🏠 Платформа", "⚙️ Автоправила", "📨 Отклики", "📄 Резюме", "📊 Анализ"], label_visibility="collapsed")
    if st.sidebar.button("Выйти"):
        logout()

    user_data = st.session_state.setdefault(user, {"rules": [], "applications": [], "resume_original": "", "resume_improved": ""})

    if menu == "🏠 Платформа":
        st.header("Платформа")
        col1, col2, col3 = st.columns(3)
        col1.metric("Правил", len(user_data["rules"]))
        col2.metric("Откликов", len(user_data["applications"]))
        col3.metric("Резюме", "Загружено" if user_data["resume_original"] else "Нет")
        st.subheader("Последние отклики")
        for app in user_data["applications"][-5:]:
            st.write(f"📌 {app['title']} — {app['employer']} ({app['status']})")

    elif menu == "⚙️ Автоправила":
        st.header("Автоправила")
        with st.form("rule"):
            name = st.text_input("Название")
            keywords = st.text_input("Ключевые слова")
            area = st.selectbox("Регион", [("РФ",113),("Москва",1),("СПб",2)], format_func=lambda x: x[0])
            letters = st.checkbox("Генерировать письма", True)
            if st.form_submit_button("Создать"):
                user_data["rules"].append({"name": name, "keywords": keywords, "area": area[1], "letters": letters})
                st.success("Правило создано!")
                st.rerun()
        for rule in user_data["rules"]:
            with st.expander(f"📌 {rule['name']}"):
                st.write(f"Ключевые слова: {rule['keywords']}")
                if st.button("Запустить", key=f"run_{rule['name']}"):
                    vacs = search_hh_vacancies(rule["keywords"], rule["area"])
                    if vacs:
                        for v in vacs[:5]:
                            title = v["name"]
                            emp = v.get("employer", {}).get("name", "")
                            url = v.get("alternate_url", "")
                            desc = v.get("snippet", {}).get("requirement", "") + " " + v.get("snippet", {}).get("responsibility", "")
                            letter = ""
                            if rule["letters"] and user_data["resume_original"]:
                                letter = ai_analyze_match(user_data["resume_original"], desc).get("cover_letter", "")
                            user_data["applications"].append({"title": title, "employer": emp, "url": url, "description": desc[:300], "letter": letter, "status": "Новый"})
                        st.success(f"Добавлено {min(len(vacs), 5)} откликов")
                        st.rerun()
                    else:
                        st.warning("Ничего не найдено")
                if st.button("Удалить", key=f"del_{rule['name']}"):
                    user_data["rules"].remove(rule)
                    st.rerun()

    elif menu == "📨 Отклики":
        st.header("Отклики")
        if not user_data["applications"]:
            st.info("Нет откликов")
        else:
            for i, app in enumerate(user_data["applications"]):
                with st.expander(f"{app['title']} — {app['employer']} ({app['status']})"):
                    st.write(app["description"])
                    if app["letter"]:
                        st.code(app["letter"])
                    st.markdown(f"[Открыть на hh.ru]({app['url']})")
                    c1, c2, c3 = st.columns(3)
                    if c1.button("Отправил", key=f"sent_{i}"):
                        app["status"] = "Отправлен"
                        st.rerun()
                    if c2.button("Повторить", key=f"repeat_{i}"):
                        app["status"] = "Повтор"
                        st.rerun()
                    if c3.button("Пропустить", key=f"skip_{i}"):
                        app["status"] = "Пропущен"
                        st.rerun()

    elif menu == "📄 Резюме":
        st.header("Резюме")
        uploaded = st.file_uploader("Загрузить файл", type=["pdf", "docx", "txt"])
        if uploaded:
            file_bytes = uploaded.read()
            if uploaded.type == "application/pdf":
                text = extract_text_from_pdf(file_bytes)
            elif uploaded.type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
                text = extract_text_from_docx(file_bytes)
            else:
                text = file_bytes.decode("utf-8")
            user_data["resume_original"] = text
            st.success("Резюме загружено!")
        if user_data["resume_original"]:
            with st.expander("Исходный текст"):
                st.text(user_data["resume_original"][:1000])
        if st.button("✨ Улучшить"):
            if not user_data["resume_original"]:
                st.warning("Загрузите резюме")
            else:
                with st.spinner("ИИ работает..."):
                    res = ai_rewrite_resume(user_data["resume_original"])
                if not res["rewritten"].startswith("[Ошибка"):
                    user_data["resume_improved"] = res["rewritten"]
                    st.success("Улучшено!")
                    st.download_button("📥 DOCX", create_docx(res["rewritten"]), "rezumator.docx")
                    pdf = create_pdf(res["rewritten"])
                    st.download_button("📥 PDF", pdf, "rezumator.pdf", mime="application/pdf")
                else:
                    st.error(res["rewritten"])
        if st.button("🔍 Аудит резюме"):
            if not user_data["resume_original"]:
                st.warning("Нет резюме")
            else:
                with st.spinner("Аудит..."):
                    audit = ai_audit_resume(user_data["resume_original"])
                if not audit["verdict"].startswith("[Ошибка"):
                    st.write(audit["verdict"])
                    st.progress(audit["overall_score"]/10)
                    for sec in audit.get("sections", []):
                        cols = st.columns([1,4])
                        cols[0].metric(sec["name"], f"{sec['score']}/10")
                        cols[1].caption(sec.get("comment", ""))
                    c1, c2 = st.columns(2)
                    c1.subheader("Сильные стороны")
                    for s in audit["top_3_strengths"]:
                        c1.write(f"- {s}")
                    c2.subheader("Слабые стороны")
                    for w in audit["top_3_weaknesses"]:
                        c2.write(f"- {w}")
                else:
                    st.error(audit["verdict"])

    elif menu == "📊 Анализ":
        st.header("Анализ вакансий")
        query = st.text_input("Ключевые слова")
        area = st.selectbox("Регион", [("РФ",113),("Москва",1),("СПб",2)], format_func=lambda x: x[0])
        if st.button("Найти"):
            vacs = search_hh_vacancies(query, area[1])
            if vacs:
                for v in vacs[:10]:
                    with st.expander(f"{v['name']} — {v['employer']['name'] if v.get('employer') else ''}"):
                        desc = v.get("snippet", {}).get("requirement", "") + " " + v.get("snippet", {}).get("responsibility", "")
                        st.write(desc[:300])
                        if user_data["resume_original"] and st.button(f"Анализировать {v['id']}", key=v["id"]):
                            analysis = ai_analyze_match(user_data["resume_original"], desc)
                            st.metric("Соответствие", f"{analysis['score']}%")
                            st.code(analysis["cover_letter"])
                            st.write("Недостающие навыки:", analysis["missing_skills"])
                            st.write("Советы:", analysis["tips"])
            else:
                st.warning("Ничего не найдено")

# ---------- ЭКРАН АВТОРИЗАЦИИ ----------
def auth_screen():
    st.title("🔐 Rezumator")
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
                st.success("Регистрация прошла успешно!")
                st.rerun()
            else:
                st.error("Этот email уже зарегистрирован")

if "user" not in st.session_state:
    auth_screen()
else:
    main()
