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

st.set_page_config(page_title="Rezumator Pro", layout="wide")
st.title("🚀 Rezumator Pro — умный автопилот")

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
if not GROQ_API_KEY:
    st.error("❌ Добавь GROQ_API_KEY в Secrets")
    st.stop()

MODEL = "llama-3.1-8b-instant"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

# ---------- Автозагрузка шрифта ----------
FONT_URL = "https://github.com/dejavu-fonts/dejavu-fonts/raw/master/ttf/DejaVuSans.ttf"

@st.cache_resource
def get_font_path():
    r = requests.get(FONT_URL, timeout=30)
    r.raise_for_status()
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.ttf')
    tmp.write(r.content)
    tmp.close()
    return tmp.name

FONT_PATH = None

def ensure_font():
    global FONT_PATH
    if FONT_PATH is None:
        try:
            FONT_PATH = get_font_path()
        except Exception:
            return False
    return True

# ---------- Сессия ----------
if "resume_text" not in st.session_state:
    st.session_state.resume_text = ""
if "improved_resume" not in st.session_state:
    st.session_state.improved_resume = ""
if "hh_cookie" not in st.session_state:
    st.session_state.hh_cookie = ""
if "rules" not in st.session_state:
    st.session_state.rules = []
if "applications" not in st.session_state:
    st.session_state.applications = []

# ========== ИИ-ФУНКЦИИ ==========
def ask_ai(prompt, max_tokens=2500):
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.7,
        "max_tokens": max_tokens
    }
    try:
        r = requests.post(GROQ_URL, headers=headers, json=payload, timeout=90)
        if r.status_code == 200:
            return r.json()["choices"][0]["message"]["content"]
        else:
            return f"[Ошибка Groq {r.status_code}] {r.text}"
    except Exception as e:
        return f"[Сетевая ошибка] {e}"

def extract_text_from_pdf(file_bytes):
    pdf = PdfReader(BytesIO(file_bytes))
    return "\n".join(page.extract_text() or "" for page in pdf.pages)

def extract_text_from_docx(file_bytes):
    doc = docx.Document(BytesIO(file_bytes))
    return "\n".join(p.text for p in doc.paragraphs)

def ai_rewrite_resume(resume_text, job_description="", style="professional"):
    prompt = f"""Ты — карьерный консультант. Улучши резюме, сохранив все фактические данные.
Стиль: {style}. Язык: русский.
{f'Вакансия: {job_description}' if job_description else ''}
Исходное резюме:
{resume_text}

Верни ТОЛЬКО JSON с полями:
- rewritten: полный улучшенный текст
- changes_summary: список сделанных изменений
"""
    raw = ask_ai(prompt)
    try:
        if "{" in raw:
            start = raw.find('{')
            end = raw.rfind('}') + 1
            return json.loads(raw[start:end])
    except:
        pass
    return {"rewritten": raw, "changes_summary": ["Ответ не в JSON."]}

def ai_analyze_match(resume_text, job_description):
    prompt = f"""Проанализируй соответствие резюме и вакансии. Оцени по шкале 0-100.
Резюме: {resume_text}
Вакансия: {job_description}
Верни ТОЛЬКО JSON с полями:
- score: число
- cover_letter: сопроводительное письмо (до 500 символов)
- missing_skills: список
- tips: список
"""
    raw = ask_ai(prompt, max_tokens=1500)
    try:
        if "{" in raw:
            start = raw.find('{')
            end = raw.rfind('}') + 1
            return json.loads(raw[start:end])
    except:
        pass
    return {"score": 0, "cover_letter": raw[:500], "missing_skills": [], "tips": []}

def ai_roast_resume_v2(resume_text):
    """Расширенный анализ по 5 разделам с оценками."""
    prompt = f"""Ты — самый строгий HR-эксперт. Проведи полный разбор резюме по 5 критериям, каждый оцени по шкале 1-10.
Резюме: {resume_text}

Верни ТОЛЬКО JSON с полями:
- verdict: общий вердикт (2-3 предложения)
- sections: массив из 5 объектов, каждый с полями:
    name: название раздела (например, "Оформление и структура", "Опыт работы и достижения", "Навыки и ключевые слова", "Образование и сертификаты", "Общее впечатление / ATS-совместимость")
    score: число от 1 до 10
    comment: развёрнутый комментарий (что хорошо, что плохо)
- overall_score: средний балл (округли до десятых)
- top_3_strengths: список из 3 главных сильных сторон
- top_3_weaknesses: список из 3 главных слабых мест
- action_plan: список конкретных шагов по улучшению (5-7 пунктов)
- keywords_to_add: список ключевых слов, которые стоит добавить
"""
    raw = ask_ai(prompt, max_tokens=3000)
    try:
        if "{" in raw:
            start = raw.find('{')
            end = raw.rfind('}') + 1
            data = json.loads(raw[start:end])
            return data
    except:
        pass
    return {"verdict": raw, "sections": [], "overall_score": 0, "top_3_strengths": [], "top_3_weaknesses": [], "action_plan": [], "keywords_to_add": []}

def search_hh_vacancies(text, area=113, per_page=10, cookie=""):
    url = "https://api.hh.ru/vacancies"
    params = {"text": text, "area": area, "per_page": per_page, "page": 0}
    headers = {"User-Agent": "Rezumator/1.0"}
    if cookie:
        headers["Cookie"] = f"hh_session={cookie}"
    r = requests.get(url, params=params, headers=headers)
    if r.status_code == 200:
        return r.json().get("items", [])
    else:
        st.error("Ошибка hh.ru")
        return []

def create_docx(text):
    doc = docx.Document()
    doc.add_heading('Улучшенное резюме', 0)
    for line in text.split('\n'):
        doc.add_paragraph(line)
    buf = BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf

def create_pdf(text):
    if not ensure_font():
        return None
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

# ========== ВКЛАДКИ ==========
tab1, tab2, tab3, tab4 = st.tabs(["📄 Резюме", "🏠 Платформа", "📨 Отклики", "📊 Анализ"])

# --- Вкладка Резюме ---
with tab1:
    st.header("Загрузи резюме")
    uploaded_file = st.file_uploader("PDF, DOCX, TXT", type=["pdf","docx","txt"])
    if uploaded_file:
        file_bytes = uploaded_file.read()
        if uploaded_file.type == "application/pdf":
            st.session_state.resume_text = extract_text_from_pdf(file_bytes)
        elif uploaded_file.type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
            st.session_state.resume_text = extract_text_from_docx(file_bytes)
        else:
            st.session_state.resume_text = file_bytes.decode("utf-8")
        st.success("Готово!")

    with st.expander("📋 Исходный текст"):
        st.text_area("Резюме", st.session_state.resume_text, height=200, disabled=True)

    st.header("Улучшить резюме")
    style = st.selectbox("Стиль", ["professional","creative","minimal"])
    target_job = st.text_area("Целевая вакансия (необязательно)", "")
    if st.button("✨ Улучшить"):
        if not st.session_state.resume_text:
            st.warning("Загрузите резюме")
        else:
            with st.spinner("ИИ работает..."):
                res = ai_rewrite_resume(st.session_state.resume_text, target_job, style)
            st.session_state.improved_resume = res["rewritten"]
            st.session_state.changes = res.get("changes_summary", [])
            col1, col2 = st.columns(2)
            with col1:
                st.subheader("Было")
                st.text(st.session_state.resume_text[:500])
            with col2:
                st.subheader("Стало")
                st.text(st.session_state.improved_resume[:500])
            st.subheader("Изменения")
            for c in st.session_state.changes:
                st.write(f"- {c}")
            st.download_button("📥 DOCX", create_docx(st.session_state.improved_resume), "rezumator.docx")
            pdf_f = create_pdf(st.session_state.improved_resume)
            if pdf_f:
                st.download_button("📥 PDF", pdf_f, "rezumator.pdf")

    # ===== ПРОЖАРКА 2.0 =====
    st.header("🔥 Прожарка 2.0")
    if st.button("🔥 Полный разбор"):
        resume = st.session_state.improved_resume or st.session_state.resume_text
        if not resume:
            st.warning("Нет резюме")
        else:
            with st.spinner("Анализируем по 5 критериям..."):
                roast = ai_roast_resume_v2(resume)
            st.subheader("Вердикт")
            st.write(roast.get("verdict", ""))
            st.subheader(f"Общий балл: {roast.get('overall_score', 0)} / 10")
            st.progress(roast.get("overall_score", 0) / 10)
            
            # Оценки по разделам
            sections = roast.get("sections", [])
            if sections:
                st.subheader("Оценки по разделам")
                for sec in sections:
                    col1, col2 = st.columns([1, 4])
                    with col1:
                        st.metric(sec.get("name", ""), f"{sec.get('score', 0)}/10")
                    with col2:
                        st.caption(sec.get("comment", ""))
            
            # Сильные стороны и слабые
            col1, col2 = st.columns(2)
            with col1:
                st.subheader("💪 Топ-3 сильных сторон")
                for s in roast.get("top_3_strengths", []):
                    st.markdown(f"- {s}")
            with col2:
                st.subheader("⚠️ Топ-3 слабых мест")
                for w in roast.get("top_3_weaknesses", []):
                    st.markdown(f"- {w}")
            
            # План действий
            st.subheader("📋 План улучшения")
            for step in roast.get("action_plan", []):
                st.markdown(f"- {step}")
            
            # Ключевые слова
            st.subheader("🔑 Ключевые слова для добавления")
            kw = roast.get("keywords_to_add", [])
            if kw:
                st.markdown(" | ".join(kw))

# --- Вкладка Платформа ---
with tab2:
    st.header("⚙️ Автоправила")
    with st.form("rule_form"):
        name = st.text_input("Название")
        keywords = st.text_input("Ключевые слова")
        area = st.selectbox("Регион", [("РФ",113),("Москва",1),("СПб",2)])
        min_sal = st.number_input("Мин. зарплата (₽)", 0, 1_000_000, 0, 10000)
        interval = st.selectbox("Проверять каждые (дней)", [1,3,7,14,30])
        letters = st.checkbox("Генерировать письма", True)
        if st.form_submit_button("✅ Создать"):
            st.session_state.rules.append({
                "name": name, "keywords": keywords, "area": area[1],
                "min_salary": min_sal, "interval": interval, "letters": letters
            })
            st.success(f"Правило «{name}» добавлено")
    if st.session_state.rules:
        for i, rule in enumerate(st.session_state.rules):
            with st.expander(f"📌 {rule['name']}"):
                st.write(f"Ключевые слова: {rule['keywords']}")
                if st.button("🚀 Запустить проверку", key=f"run_{i}"):
                    with st.spinner("Ищем..."):
                        vacs = search_hh_vacancies(rule["keywords"], rule["area"], cookie=st.session_state.hh_cookie)
                        if vacs:
                            new_apps = []
                            for vac in vacs[:5]:
                                title = vac.get("name","")
                                emp = vac["employer"]["name"] if vac.get("employer") else ""
                                url = vac.get("alternate_url","")
                                desc = (vac.get("snippet",{}).get("requirement","") + " " + vac.get("snippet",{}).get("responsibility",""))
                                letter = ""
                                if rule["letters"] and st.session_state.resume_text:
                                    match = ai_analyze_match(st.session_state.resume_text, desc)
                                    letter = match.get("cover_letter","")
                                new_apps.append({
                                    "title": title, "employer": emp, "url": url,
                                    "description": desc[:300], "letter": letter,
                                    "status": "Новый", "rule": rule["name"],
                                    "date": datetime.date.today().isoformat()
                                })
                            st.session_state.applications.extend(new_apps)
                            st.success(f"+{len(new_apps)} вакансий")
                        else:
                            st.warning("Ничего не найдено")
                if st.button("🗑 Удалить", key=f"del_{i}"):
                    st.session_state.rules.pop(i)
                    st.experimental_rerun()

# --- Вкладка Отклики ---
with tab3:
    st.header("📨 Очередь откликов")
    if not st.session_state.applications:
        st.info("Пусто")
    else:
        for i, app in enumerate(st.session_state.applications):
            with st.expander(f"{app['title']} — {app['employer']} ({app['status']})"):
                st.write(app.get("description",""))
                if app.get("letter"):
                    st.code(app["letter"])
                st.markdown(f"[Открыть на hh.ru]({app['url']})")
                col1, col2, col3 = st.columns(3)
                with col1:
                    if st.button("✅ Отправил", key=f"sent_{i}"):
                        app["status"] = "Отправлен"
                        st.experimental_rerun()
                with col2:
                    if st.button("⏰ Повторить через 3 дня", key=f"rep_{i}"):
                        app["status"] = "Повтор"
                        st.experimental_rerun()
                with col3:
                    if st.button("❌ Пропустить", key=f"skip_{i}"):
                        app["status"] = "Пропущен"
                        st.experimental_rerun()

# --- Вкладка Анализ (с куками HH) ---
with tab4:
    st.header("Анализ вакансии и письма")
    
    # Авторизация через куки
    with st.expander("🔐 Вход в hh.ru (опционально)"):
        st.markdown("""
        Если вы залогинены на hh.ru, скопируйте куку `hh_session` из браузера (F12 → Application → Cookies → hh_session).
        Это позволит видеть персонализированные рекомендации.
        """)
        cookie = st.text_input("Вставьте значение куки hh_session", type="password")
        if cookie:
            st.session_state.hh_cookie = cookie
            st.success("Кука сохранена (только в этой сессии)")
    
    query = st.text_input("Ключевые слова вакансии")
    area_sel = st.selectbox("Регион", [("РФ",113),("Москва",1),("СПб",2)])
    if st.button("🔍 Найти"):
        if not query:
            st.warning("Введите запрос")
        else:
            with st.spinner("Поиск..."):
                vacs = search_hh_vacancies(query, area=area_sel[1], cookie=st.session_state.hh_cookie)
            if vacs:
                st.success(f"Найдено {len(vacs)}")
                for vac in vacs[:10]:
                    title = vac.get("name","")
                    emp = vac["employer"]["name"] if vac.get("employer") else ""
                    url = vac.get("alternate_url","")
                    desc = (vac.get("snippet",{}).get("requirement","") + " " + vac.get("snippet",{}).get("responsibility",""))
                    with st.expander(f"{title} — {emp}"):
                        st.write(desc[:300])
                        if st.session_state.resume_text:
                            if st.button("📊 Анализировать", key=vac["id"]):
                                analysis = ai_analyze_match(st.session_state.resume_text, desc)
                                st.metric("Соответствие", f"{analysis['score']}%")
                                st.code(analysis.get("cover_letter",""))
                                st.write("Недостающие навыки:", analysis.get("missing_skills"))
                                st.write("Советы:", analysis.get("tips"))
                                st.markdown(f"[Откликнуться на hh.ru]({url})")
                        else:
                            st.info("Загрузите резюме на вкладке «Резюме»")
            else:
                st.warning("Ничего не найдено")
