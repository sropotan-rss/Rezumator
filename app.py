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

if not SUPABASE_URL or not SUPABASE_KEY:
    st.error("❌ Добавь SUPABASE_URL и SUPABASE_KEY в Secrets")
    st.stop()
if not GROQ_API_KEY:
    st.error("❌ Добавь GROQ_API_KEY в Secrets")
    st.stop()

# Проверка формата ключа
if not SUPABASE_KEY.startswith("sb_publishable_"):
    st.error("❌ SUPABASE_KEY должен начинаться с 'sb_publishable_'. Ты, вероятно, вставил секретный ключ. Используй Publishable key из Supabase → API Keys.")
    st.stop()

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

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

# ---------- АВТОРИЗАЦИЯ ----------
def login(email, password):
    try:
        return supabase.auth.sign_in_with_password({"email": email, "password": password})
    except Exception as e:
        st.error(f"Ошибка входа: {e}")
        return None

def signup(email, password):
    try:
        return supabase.auth.sign_up({"email": email, "password": password})
    except Exception as e:
        st.error(f"Ошибка регистрации: {e}")
        return None

def get_session():
    try:
        return supabase.auth.get_session()
    except:
        return None

# ---------- ЗАГРУЗКА ДАННЫХ ИЗ БД ----------
def load_rules(user_id):
    try:
        res = supabase.table("user_rules").select("*").eq("user_id", user_id).execute()
        return res.data or []
    except:
        return []

def save_rule(user_id, rule):
    supabase.table("user_rules").insert({**rule, "user_id": user_id}).execute()

def delete_rule(rule_id):
    supabase.table("user_rules").delete().eq("id", rule_id).execute()

def load_applications(user_id):
    try:
        res = supabase.table("user_applications").select("*").eq("user_id", user_id).order("created_at", desc=True).execute()
        return res.data or []
    except:
        return []

def save_application(user_id, app):
    supabase.table("user_applications").insert({**app, "user_id": user_id}).execute()

def update_application(app_id, updates):
    supabase.table("user_applications").update(updates).eq("id", app_id).execute()

def load_resume(user_id):
    try:
        res = supabase.table("user_resumes").select("*").eq("user_id", user_id).limit(1).single().execute()
        return res.data
    except:
        return None

def save_resume(user_id, original, improved=None):
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
    user = get_session().user
    user_id = user.id

    # Боковая панель
    with st.sidebar:
        st.markdown("## 🚀 Rezumator")
        st.markdown(f"👤 {user.email}")
        menu = st.radio("Меню", ["🏠 Платформа", "⚙️ Автоправила", "📨 Отклики", "📄 Резюме", "📊 Анализ"], label_visibility="collapsed")
        st.markdown("---")
        if st.button("🚪 Выйти"):
            supabase.auth.sign_out()
            st.session_state.clear()
            st.rerun()

    # Загрузка облачных данных
    rules = load_rules(user_id)
    applications = load_applications(user_id)
    resume_data = load_resume(user_id)

    if "resume_text" not in st.session_state:
        st.session_state.resume_text = resume_data.get("original_text", "") if resume_data else ""
    if "improved_resume" not in st.session_state:
        st.session_state.improved_resume = resume_data.get("improved_text", "") if resume_data else ""

    # ======== ПЛАТФОРМА (главный дашборд) ========
    if menu == "🏠 Платформа":
        st.markdown('<p class="main-header">🏠 Платформа</p>', unsafe_allow_html=True)
        col1, col2, col3 = st.columns(3)
        col1.metric("Правил", len(rules))
        col2.metric("Откликов", len(applications))
        col3.metric("Резюме", "Загружено" if st.session_state.resume_text else "Нет")
        st.markdown("### Последние отклики")
        if applications:
            for app in applications[:5]:
                st.markdown(f"📌 **{app['title']}** — {app['employer']} ({app['status']})")
        else:
            st.info("Пока нет откликов")

    # ======== АВТОПРАВИЛА ========
    elif menu == "⚙️ Автоправила":
        st.markdown('<p class="main-header">⚙️ Автоправила</p>', unsafe_allow_html=True)
        with st.form("rule_form"):
            name = st.text_input("Название")
            keywords = st.text_input("Ключевые слова")
            area = st.selectbox("Регион", [("РФ",113),("Москва",1),("СПб",2)], format_func=lambda x: x[0])
            min_sal = st.number_input("Мин. зарплата", 0, 1000000, 0, 10000)
            interval = st.selectbox("Периодичность (дни)", [1,3,7,14,30])
            letters = st.checkbox("Генерировать письма", True)
            if st.form_submit_button("✅ Создать правило"):
                rule = {
                    "name": name, "keywords": keywords, "area": area[1],
                    "min_salary": min_sal, "interval_days": interval, "letters": letters
                }
                save_rule(user_id, rule)
                st.success("Правило добавлено!")
                st.rerun()

        if rules:
            for rule in rules:
                with st.expander(f"📌 {rule['name']}"):
                    st.write(f"Ключевые слова: {rule['keywords']}")
                    c1, c2 = st.columns(2)
                    if c1.button("🚀 Запустить", key=f"run_{rule['id']}"):
                        vacs = search_hh_vacancies(rule["keywords"], rule["area"])
                        if vacs:
                            for vac in vacs[:5]:
                                title = vac.get("name","")
                                emp = vac["employer"]["name"] if vac.get("employer") else ""
                                url = vac.get("alternate_url","")
                                desc = vac.get("snippet",{}).get("requirement","") + " " + vac.get("snippet",{}).get("responsibility","")
                                letter = ""
                                if rule["letters"] and st.session_state.resume_text:
                                    match = ai_analyze_match(st.session_state.resume_text, desc)
                                    letter = match.get("cover_letter","")
                                app = {"title":title,"employer":emp,"url":url,"description":desc[:300],"letter":letter,"status":"Новый","rule_name":rule["name"]}
                                save_application(user_id, app)
                            st.success(f"Добавлено вакансий: {len(vacs[:5])}")
                            st.rerun()
                        else:
                            st.warning("Ничего не найдено")
                    if c2.button("🗑 Удалить", key=f"del_{rule['id']}"):
                        delete_rule(rule["id"])
                        st.rerun()
        else:
            st.info("Нет правил")

    # ======== ОТКЛИКИ ========
    elif menu == "📨 Отклики":
        st.markdown('<p class="main-header">📨 Отклики</p>', unsafe_allow_html=True)
        if not applications:
            st.info("Нет откликов")
        else:
            status_filter = st.selectbox("Статус", ["Все","Новый","Отправлен","Повтор"])
            filtered = [a for a in applications if status_filter == "Все" or a["status"] == status_filter]
            for app in filtered:
                with st.expander(f"{app['title']} — {app['employer']} ({app['status']})"):
                    st.write(app.get("description",""))
                    if app.get("letter"):
                        st.code(app["letter"])
                    st.markdown(f"[Открыть на hh.ru]({app['url']})")
                    c1,c2,c3 = st.columns(3)
                    if c1.button("✅ Отправил", key=f"sent_{app['id']}"):
                        update_application(app["id"], {"status": "Отправлен"})
                        st.rerun()
                    if c2.button("⏰ Повторить через 3 дн.", key=f"rep_{app['id']}"):
                        update_application(app["id"], {"status": "Повтор", "follow_up_date": str(datetime.date.today() + datetime.timedelta(days=3))})
                        st.rerun()
                    if c3.button("❌ Пропустить", key=f"skip_{app['id']}"):
                        update_application(app["id"], {"status": "Пропущен"})
                        st.rerun()

    # ======== РЕЗЮМЕ ========
    elif menu == "📄 Резюме":
        st.markdown('<p class="main-header">📄 Резюме</p>', unsafe_allow_html=True)
        uploaded = st.file_uploader("Загрузить резюме", type=["pdf","docx","txt"])
        if uploaded:
            file_bytes = uploaded.read()
            if uploaded.type == "application/pdf":
                st.session_state.resume_text = extract_text_from_pdf(file_bytes)
            elif uploaded.type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
                st.session_state.resume_text = extract_text_from_docx(file_bytes)
            else:
                st.session_state.resume_text = file_bytes.decode("utf-8")
            save_resume(user_id, st.session_state.resume_text)
            st.success("Резюме сохранено!")

        col1, col2 = st.columns(2)
        with col1:
            with st.expander("📋 Исходный текст"):
                st.text(st.session_state.resume_text[:1000])
        with col2:
            if st.session_state.improved_resume:
                with st.expander("✨ Улучшенное"):
                    st.text(st.session_state.improved_resume[:1000])

        style = st.selectbox("Стиль улучшения", ["professional","creative","minimal"])
        job = st.text_input("Целевая вакансия (опционально)")
        if st.button("✨ Улучшить"):
            if not st.session_state.resume_text:
                st.warning("Загрузите резюме")
            else:
                with st.spinner("ИИ работает..."):
                    res = ai_rewrite_resume(st.session_state.resume_text, job, style)
                if not res["rewritten"].startswith("[Ошибка"):
                    st.session_state.improved_resume = res["rewritten"]
                    save_resume(user_id, st.session_state.resume_text, st.session_state.improved_resume)
                    st.success("Готово!")
                    st.download_button("📥 DOCX", create_docx(res["rewritten"]), "rezumator.docx")
                    pdf = create_pdf(res["rewritten"])
                    if pdf: st.download_button("📥 PDF", pdf, "rezumator.pdf")
                else:
                    st.error(res["rewritten"])

        st.markdown("---")
        if st.button("🔍 Аудит резюме"):
            if not st.session_state.resume_text:
                st.warning("Нет резюме")
            else:
                with st.spinner("Аудит..."):
                    audit = ai_audit_resume(st.session_state.resume_text)
                if not audit.get("verdict","").startswith("[Ошибка"):
                    st.success("Аудит готов")
                    st.write(audit.get("verdict"))
                    st.progress(audit.get("overall_score",0)/10)
                    for s in audit.get("sections",[]):
                        cols = st.columns([1,4])
                        cols[0].metric(s["name"], f"{s['score']}/10")
                        cols[1].caption(s.get("comment",""))
                    col_str, col_weak = st.columns(2)
                    col_str.write("💪 Сильные стороны")
                    for s in audit.get("top_3_strengths",[]): col_str.write(f"- {s}")
                    col_weak.write("⚠️ Слабые стороны")
                    for w in audit.get("top_3_weaknesses",[]): col_weak.write(f"- {w}")
                else:
                    st.error(audit["verdict"])

    # ======== АНАЛИЗ ВАКАНСИЙ ========
    elif menu == "📊 Анализ":
        st.markdown('<p class="main-header">📊 Анализ вакансий</p>', unsafe_allow_html=True)
        query = st.text_input("Ключевые слова")
        area = st.selectbox("Регион", [("РФ",113),("Москва",1),("СПб",2)])
        if st.button("🔍 Найти вакансии"):
            vacs = search_hh_vacancies(query, area[1])
            if vacs:
                for v in vacs[:10]:
                    with st.expander(f"{v['name']} — {v['employer']['name'] if v.get('employer') else ''}"):
                        desc = v.get("snippet",{}).get("requirement","") + " " + v.get("snippet",{}).get("responsibility","")
                        st.write(desc[:300])
                        if st.session_state.resume_text and st.button(f"Анализировать {v['id']}", key=v["id"]):
                            analysis = ai_analyze_match(st.session_state.resume_text, desc)
                            st.metric("Соответствие", f"{analysis['score']}%")
                            st.code(analysis.get("cover_letter",""))
                            st.write("Недостающие навыки:", analysis.get("missing_skills"))
                            st.write("Советы:", analysis.get("tips"))
            else:
                st.warning("Ничего не найдено")

# ========== ЭКРАН АВТОРИЗАЦИИ ==========
def auth_screen():
    st.title("🔐 Rezumator")
    menu = st.radio("Действие", ["Вход", "Регистрация"], label_visibility="visible")
    email = st.text_input("Email")
    password = st.text_input("Пароль", type="password")
    if menu == "Вход":
        if st.button("Войти"):
            if login(email, password):
                st.success("Успешный вход!")
                st.rerun()
    else:
        if st.button("Зарегистрироваться"):
            if signup(email, password):
                st.success("Проверьте почту для подтверждения!")

# ---------- ЗАПУСК ----------
if get_session():
    main_app()
else:
    auth_screen()
