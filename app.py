# app.py
import os
import re
import json
from datetime import datetime, timedelta

import requests
import pandas as pd
import streamlit as st
import altair as alt

from openai import OpenAI


st.set_page_config(
    page_title="AI 습관 트래커",
    page_icon="📊",
    layout="wide"
)


def safe_get_json(url, timeout=10, params=None):
    try:
        r = requests.get(url, params=params, timeout=timeout)
        if r.status_code != 200:
            return None
        return r.json()
    except Exception:
        return None


def get_weather(city, api_key):
    if not api_key:
        return None

    url = "https://api.openweathermap.org/data/2.5/weather"
    params = {
        "q": city,
        "appid": api_key.strip(),
        "units": "metric",
        "lang": "kr",
    }
    data = safe_get_json(url, params=params)
    if not data:
        return None

    try:
        return {
            "city": city,
            "description": data["weather"][0]["description"],
            "temp_c": data["main"]["temp"],
            "feels_like_c": data["main"]["feels_like"],
            "humidity": data["main"]["humidity"],
            "wind_ms": data.get("wind", {}).get("speed", 0),
        }
    except Exception:
        return None


def get_dog_image():
    data = safe_get_json("https://dog.ceo/api/breeds/image/random")
    if not data or data.get("status") != "success":
        return None

    try:
        url = data["message"]
        m = re.search(r"/breeds/([^/]+)/", url)
        breed = m.group(1).replace("-", " ") if m else "unknown"
        return {"image_url": url, "breed": breed}
    except Exception:
        return None


SYSTEM_PROMPTS = {
    "스파르타 코치": "너는 엄격한 스파르타 코치다. 냉정하고 직설적으로 조언해라.",
    "따뜻한 멘토": "너는 따뜻한 멘토다. 공감과 응원을 중심으로 조언해라.",
    "게임 마스터": "너는 RPG 게임 마스터다. 퀘스트와 레벨업 표현을 사용해라.",
}


def generate_report(api_key, coach_style, habits, mood, weather, dog):
    if not api_key:
        return None

    client = OpenAI(api_key=api_key.strip())

    checked = [k for k, v in habits.items() if v]
    unchecked = [k for k, v in habits.items() if not v]

    payload = {
        "기분": mood,
        "완료 습관": checked,
        "미완료 습관": unchecked,
        "날씨": weather,
        "강아지": dog,
    }

    prompt = f"""
아래 정보를 바탕으로 오늘의 컨디션 리포트를 작성해줘.

형식:
- 컨디션 등급(S~D)
- 습관 분석
- 날씨 코멘트
- 내일 미션 3개
- 오늘의 한마디

데이터:
{json.dumps(payload, ensure_ascii=False, indent=2)}
"""

    try:
        res = client.responses.create(
            model="gpt-5-mini",
            input=[
                {"role": "system", "content": SYSTEM_PROMPTS[coach_style]},
                {"role": "user", "content": prompt},
            ],
        )
        return res.output_text
    except Exception:
        return None


HABITS = {
    "기상 미션": "⏰ 기상 미션",
    "물 마시기": "💧 물 마시기",
    "공부/독서": "📚 공부/독서",
    "운동하기": "🏃 운동하기",
    "수면": "😴 수면",
}

CITIES = [
    "Seoul", "Busan", "Incheon", "Daegu", "Daejeon",
    "Gwangju", "Suwon", "Ulsan", "Jeju", "Sejong"
]

COACHES = ["스파르타 코치", "따뜻한 멘토", "게임 마스터"]


if "history" not in st.session_state:
    st.session_state.history = []

st.sidebar.header("🔑 API Key")
openai_key = st.sidebar.text_input("OpenAI API Key", type="password")
weather_key = st.sidebar.text_input("OpenWeatherMap API Key", type="password")


st.title("📊 AI 습관 트래커")

city = st.selectbox("도시 선택", CITIES)
coach = st.radio("코치 스타일", COACHES, horizontal=True)

st.subheader("✅ 오늘의 습관")

col1, col2 = st.columns(2)
values = {}
for i, (k, label) in enumerate(HABITS.items()):
    with col1 if i < 3 else col2:
        values[k] = st.checkbox(label)

mood = st.slider("🙂 오늘 기분", 1, 10, 5)

done = sum(values.values())
achievement = int(done / len(values) * 100)

m1, m2, m3 = st.columns(3)
m1.metric("달성률", f"{achievement}%")
m2.metric("완료 습관", f"{done}/{len(values)}")
m3.metric("기분", mood)

today = datetime.now().strftime("%Y-%m-%d")
st.session_state.history.append({
    "date": today,
    "achievement": achievement
})

df = pd.DataFrame(st.session_state.history[-7:])
if not df.empty:
    chart = alt.Chart(df).mark_bar().encode(
        x="date",
        y="achievement"
    )
    st.altair_chart(chart, use_container_width=True)

if st.button("컨디션 리포트 생성"):
    weather = get_weather(city, weather_key)
    dog = get_dog_image()
    report = generate_report(openai_key, coach, values, mood, weather, dog)

    st.subheader("🌦️ 날씨")
    st.write(weather)

    st.subheader("🐶 오늘의 강아지")
    if dog:
        st.image(dog["image_url"])
        st.write(dog["breed"])

    st.subheader("🧠 AI 리포트")
    st.write(report)

