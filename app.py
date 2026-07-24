import streamlit as st
import requests
import json
import os
from io import BytesIO
from PyPDF2 import PdfReader
import docx
import time

st.set_page_config(page_title="JobTurbo AI", layout="wide")
st.title("🚀 Умный помощник для поиска работы")

HF_TOKEN = os.getenv("HF_TOKEN")
if not HF_TOKEN:
    st.error("❌ Не найден токен Hugging Face. Добавь его в Secrets (HF_TOKEN).")
    st.stop()

# Список моделей для автоперебора (проверенные бесплатные русскоязычные)
MODELS = [
    "mistralai/Mistral-7B-Instruct-v0.2",
    "google/flan-t5-large",
    "facebook/bart-large-mnli",
    "openchat/openchat-3.5-0106"
]
# Резервный вариант – использовать OpenRouter (платный, но дешёвый, если HF не работает)
OPENROUTER_FALLBACK = False  # можешь включить, добавив OPENROUTER_API_KEY в Secrets
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

def ask_ai(prompt: str) -> str:
    """Отправляет запрос к Hugging Face, при неудаче пробует другие модели."""
    for model in MODELS:
        try:
            response = requests.post(
                f"https://api-inference.huggingface.co/models/{model}",
                headers={"Authorization": f"Bearer {HF_TOKEN}"},
                json={"inputs": prompt, "parameters": {"max_new_tokens": 800, "temperature": 0.7}},
                timeout=30
            )
            if response.status_code == 200:
                data = response.json()
                if isinstance(data, list) and len(data) > 0:
                    return data[0]["generated_text"]
                elif isinstance(data, dict) and "generated_text" in data:
                    return data["generated_text"]
                else:
                    return str(data)
            # Если модель загружается – ждём 5 секунд и пробуем ещё раз
            elif response.status_code == 503 and "loading" in response.text.lower():
                time.sleep(5)
                continue
        except Exception:
            continue
    # Если ни одна модель HF не сработала, используем OpenRouter (если есть ключ)
    if OPENROUTER_FALLBACK and OPENROUTER_API_KEY:
        return ask_ai_openrouter(prompt)
    return "[Ошибка] Все модели временно недоступны. Попробуйте позже."

def ask_ai_openrouter(prompt: str) -> str:
    try:
        r = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}"},
            json={
                "model": "google/gemma-2-2b-it",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.7,
                "max_tokens": 800
            },
            timeout=30
        )
        if r.status_code == 200:
            return r.json()["choices"][0]["message"]["content"]
        else:
            return f"[Ошибка OpenRouter: {r.status_code}] {r.text}"
    except Exception as e:
        return f"[Ошибка OpenRouter] {e}"

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
    if raw.startswith("[Ошибка"):
        return {"rewritten": raw, "changes_summary": []}
    try:
        start = raw.find('{')
        end = raw.rfind('}') + 1
        if start != -1 and end != 0:
            return json.loads(raw[start:end])
    except:
        pass
    return {"rewritten": raw, "changes_summary": ["Ответ не в JSON, показан сырой текст."]}

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
    if raw.startswith("[Ошибка"):
        return {"score": 0, "cover_letter": raw, "missing_skills": [], "tips": []}
    try:
        start = raw.find('{')
        end = raw.rfind('}') + 1
        if start != -1 and end != 0:
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

# Интерфейс
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
        st.success("Резюме загружено! Вот текст:")
        st.text_area("Содержимое резюме", resume_text, height=250)

    st.header("Шаг 2: Улучши резюме с ИИ")
    style = st.selectbox("Стиль", ["professional", "creative", "minimal"], index=0)
    target_job_desc = st.text_area("Описание целевой вакансии (необязательно)", "", height=100)

    if st.button("✨ Улучшить резюме"):
        if not resume_text:
            st.warning("Сначала загрузите резюме.")
        else:
            with st.spinner("ИИ работает (до 30 сек)..."):
                result = ai_rewrite_resume(resume_text, target_job_desc, style)
            st.subheader("📝 Улучшенное резюме")
            st.text_area("Новый текст", result["rewritten"], height=300)
            st.subheader("✅ Что изменилось")
            for change in result["changes_summary"]:
                st.write(f"- {change}")

with tab2:
    st.header("Поиск вакансий на hh.ru")
    search_query = st.text_input("Ключевые слова (например: Python developer)")
    area = st.selectbox("Регион", [("Россия", 113), ("Москва", 1), ("Санкт-Петербург", 2)],
                         format_func=lambda x: x[0])
    if st.button("Искать вакансии"):
        if search_query:
            with st.spinner("Ищем на hh.ru..."):
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
                        st.write(f"**Описание:** {desc[:300]}...")
                        st.markdown(f"[Открыть вакансию на hh.ru]({url})", unsafe_allow_html=True)
                        if st.button(f"Анализировать эту вакансию", key=vac["id"]):
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
    st.header("Сравнение резюме с вакансией и генерация письма")
    if "selected_vacancy" not in st.session_state:
        st.info("Перейдите на вкладку 'Вакансии' и нажмите 'Анализировать эту вакансию'.")
    else:
        vac = st.session_state["selected_vacancy"]
        st.subheader(f"Вакансия: {vac['title']}")
        st.text_area("Описание вакансии", vac["description"][:1000], height=150)
        current_resume = st.text_area("Текущее резюме (можно отредактировать)", 
                                      st.session_state.get("resume_text", ""), height=200)
        if st.button("📈 Проанализировать и сгенерировать письмо"):
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
                st.markdown(f"[👉 Откликнуться на hh.ru]({vac['url']})", unsafe_allow_html=True)
