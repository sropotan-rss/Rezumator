import streamlit as st
import requests
import json
import os
from io import BytesIO
from PyPDF2 import PdfReader
import docx

st.set_page_config(page_title="JobTurbo AI", layout="wide")
st.title("🚀 Умный помощник для поиска работы")

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
if not GROQ_API_KEY:
    st.error("❌ Добавь GROQ_API_KEY в Secrets")
    st.stop()

MODEL = "llama-3.2-3b-preview"   # быстрая, бесплатная, понимает русский
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

def ask_ai(prompt: str) -> str:
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.7,
        "max_tokens": 800
    }
    try:
        r = requests.post(GROQ_URL, headers=headers, json=payload, timeout=30)
        if r.status_code == 200:
            return r.json()["choices"][0]["message"]["content"]
        else:
            return f"[Ошибка Groq {r.status_code}] {r.text}"
    except Exception as e:
        return f"[Сетевая ошибка] {e}"

def extract_text_from_pdf(file_bytes):
    pdf = PdfReader(BytesIO(file_bytes))
    text = ""
    for page in pdf.pages:
        text += page.extract_text() + "\n"
    return text

def extract_text_from_docx(file_bytes):
    doc = docx.Document(BytesIO(file_bytes))
    return "\n".join([p.text for p in doc.paragraphs])

def ai_rewrite_resume(resume_text, job_description="", style="professional"):
    prompt = f"""Ты — карьерный консультант. Улучши резюме, сохранив все фактические данные.
Стиль: {style}. Язык: русский.
{f'Вакансия: {job_description}' if job_description else ''}
Исходное резюме:
{resume_text}

Верни ТОЛЬКО JSON (без лишнего текста) с полями:
- rewritten: полный улучшенный текст
- changes_summary: список сделанных изменений
"""
    raw = ask_ai(prompt)
    if raw.startswith("[Ошибка") or raw.startswith("[Сетевая"):
        return {"rewritten": raw, "changes_summary": []}
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
Резюме:
{resume_text}
Вакансия:
{job_description}

Верни ТОЛЬКО JSON (без лишнего текста) с полями:
- score: число
- cover_letter: готовое сопроводительное письмо (макс. 500 символов)
- missing_skills: список недостающих навыков
- tips: советы по улучшению резюме
"""
    raw = ask_ai(prompt)
    if raw.startswith("[Ошибка") or raw.startswith("[Сетевая"):
        return {"score": 0, "cover_letter": raw, "missing_skills": [], "tips": []}
    try:
        if "{" in raw:
            start = raw.find('{')
            end = raw.rfind('}') + 1
            return json.loads(raw[start:end])
    except:
        pass
    return {"score": 0, "cover_letter": raw[:500], "missing_skills": [], "tips": []}

def search_hh_vacancies(text, area=113, per_page=10):
    url = "https://api.hh.ru/vacancies"
    params = {
        "text": text,
        "area": area,
        "per_page": per_page,
        "page": 0,
        "only_with_salary": False
    }
    headers = {"User-Agent": "JobTurboAI/1.0 (support@example.com)"}
    r = requests.get(url, params=params, headers=headers)
    if r.status_code == 200:
        return r.json().get("items", [])
    else:
        st.error("Ошибка при запросе к hh.ru")
        return []

# Интерфейс (без изменений)
tab1, tab2, tab3 = st.tabs(["📄 Резюме", "🔍 Вакансии", "📊 Анализ и письма"])

with tab1:
    st.header("Шаг 1: Загрузи резюме")
    uploaded_file = st.file_uploader("Выберите файл (PDF, DOCX, TXT)", type=["pdf", "docx", "txt"])
    resume_text = ""
    if uploaded_file is not None:
        file_bytes = uploaded_file.read()
        if uploaded_file.type == "application/pdf":
            resume_text = extract_text_from_pdf(file_bytes)
        elif uploaded_file.type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
            resume_text = extract_text_from_docx(file_bytes)
        else:
            resume_text = file_bytes.decode("utf-8")
        st.success("Резюме загружено!")
        st.text_area("Содержимое резюме", resume_text, height=250)

    st.header("Шаг 2: Улучши резюме с ИИ")
    style = st.selectbox("Стиль", ["professional", "creative", "minimal"], index=0)
    target_job_desc = st.text_area("Описание целевой вакансии (необязательно)", "", height=100)

    if st.button("✨ Улучшить резюме"):
        if not resume_text:
            st.warning("Сначала загрузите резюме.")
        else:
            with st.spinner("ИИ работает..."):
                result = ai_rewrite_resume(resume_text, target_job_desc, style)
            st.subheader("📝 Улучшенное резюме")
            st.text_area("Новый текст", result["rewritten"], height=300)
            st.subheader("✅ Что изменилось")
            for change in result["changes_summary"]:
                st.write(f"- {change}")

with tab2:
    st.header("Поиск вакансий на hh.ru")
    search_query = st.text_input("Ключевые слова")
    area = st.selectbox("Регион", [("Россия", 113), ("Москва", 1), ("Санкт-Петербург", 2)],
                         format_func=lambda x: x[0])
    if st.button("Искать вакансии"):
        if search_query:
            with st.spinner("Ищем..."):
                vacancies = search_hh_vacancies(search_query, area=area[1])
            if vacancies:
                st.success(f"Найдено {len(vacancies)} вакансий")
                for vac in vacancies:
                    title = vac.get("name")
                    employer = vac.get("employer", {}).get("name")
                    url = vac.get("alternate_url")
                    snippet = vac.get("snippet", {})
                    desc = snippet.get("requirement", "") + " " + snippet.get("responsibility", "")
                    with st.expander(f"{title} — {employer}"):
                        st.write(f"Описание: {desc[:300]}...")
                        st.markdown(f"[Открыть на hh.ru]({url})")
                        if st.button("Анализировать", key=vac["id"]):
                            st.session_state["selected_vacancy"] = {
                                "title": title,
                                "description": desc,
                                "url": url
                            }
            else:
                st.warning("Ничего не найдено.")
        else:
            st.warning("Введите ключевые слова")

with tab3:
    st.header("Сравнение резюме с вакансией")
    if "selected_vacancy" not in st.session_state:
        st.info("Сначала выберите вакансию на вкладке 'Вакансии'.")
    else:
        vac = st.session_state["selected_vacancy"]
        st.subheader(f"Вакансия: {vac['title']}")
        st.text_area("Описание", vac["description"][:1000], height=150)
        current_resume = st.text_area("Текущее резюме", st.session_state.get("resume_text", ""), height=200)
        if st.button("📈 Анализировать"):
            if not current_resume:
                st.warning("Введите текст резюме.")
            else:
                with st.spinner("Анализируем..."):
                    analysis = ai_analyze_match(current_resume, vac["description"])
                st.metric("Соответствие", f"{analysis['score']}%")
                st.subheader("📧 Сопроводительное письмо")
                st.code(analysis["cover_letter"])
                st.subheader("🔍 Недостающие навыки")
                for skill in analysis.get("missing_skills", []):
                    st.write(f"- {skill}")
                st.subheader("💡 Рекомендации")
                for tip in analysis.get("tips", []):
                    st.write(f"- {tip}")
                st.markdown(f"[👉 Откликнуться на hh.ru]({vac['url']})")
