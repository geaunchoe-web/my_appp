# app.py
import os
import re
import json
from datetime import datetime

import requests
import pandas as pd
import streamlit as st
import altair as alt

# ✅ openai 안전 import (패키지 없어도 앱이 죽지 않게)
try:
    from openai import OpenAI
except Exception:
    OpenAI = None


st.set_page_config(page_title="AI 습관 트래커", page_icon="📊", layout="wide")


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
    data = safe_get_json(url, timeout=10, params=params)
    if not data:
        return None

    try:
        return {
            "city": city,
            "description": data["weather"][0]["description"],
            "temp_c": float(data["main"]["temp"]),
            "feels_like_c": float(data["main"]["feels_like"]),
            "humidity": int(data["main"]["humidity"]),
            "wind_ms": float(data.get("wind", {}).get("speed", 0.0)),
        }
    except Exception:
        return None


def get_dog_image():
    data = safe_get_json("https://dog.ceo/api/breeds/image/random", timeout=10)
    if not data or data.get("status") != "success":
        return None

    try:
        url = data["message"]
        m = re.search(r"/breeds/([^/]+)/", url)
        breed = m.group(1).replace("-", " ").strip() if m else "unknown"
        return {"image_url": url, "breed": breed}
    except Exception:
        return None


SYSTEM_PROMPTS = {
    "스파르타 코치": (
        "너는 엄격하지만 공정한 '스파르타 코치'다. "
        "핑계는 차단하고, 행동 중심으로 짧고 날카롭게 피드백한다."
    ),
    "따뜻한 멘토": (
        "너는 따뜻하고 현실적인 '멘토'다. "
        "자책을 줄이고, 작은 성공을 강화하며, 다음 행동을 부드럽게 안내한다."
    ),
    "게임 마스터": (
        "너는 RPG 세계관의 '게임 마스터'다. "
        "사용자를 플레이어로 부르고, 퀘스트/보상/레벨업 언어를 쓴다."
    ),
}

FORMAT_RULES = """출력 형식(반드시 준수):
1) 컨디션 등급: S/A/B/C/D 중 하나
2) 습관 분석: 4~6줄
3) 날씨 코멘트: 2~3줄
4) 내일 미션: 3개 (번호 목록)
5) 오늘의 한마디: 한 줄
"""


def generate_report(openai_key, coach_style, habits, mood, weather, dog):
    # ✅ openai 패키지/키 없으면 안내만 하고 종료
    if OpenAI is None:
        return "⚠️ openai 패키지가 설치되지 않았어요. requirements.txt에 `openai`를 추가하고 재배포하세요."
    if not openai_key:
        return "⚠️ OpenAI API Key를 사이드바에 입력해 주세요."

    checked = [k for k, v in habits.items() if v]
    unchecked = [k for k, v in habits.items() if not v]

    weather_text = "날씨 정보 없음"
    if weather:
        weather_text = f"{weather['city']} / {weather['description']} / {weather['temp_c']:.1f}°C"

    dog_text = "강아지 정보 없음"
    if dog:
        dog_text = f"오늘의 강아지 품종: {dog.get('breed','unknown')}"

    payload = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "mood": mood,
        "habits_checked": checked,
        "habits_unchecked": unchecked,
        "weather": weather_text,
        "dog": dog_text,
    }

    system = SYSTEM_PROMPTS.get(coach_style, SYSTEM_PROMPTS["따뜻한 멘토"])
    prompt = FORMAT_RULES + "\n\n데이터:\n" + json.dumps(payload, ensure_ascii=False, indent=2)

    try:
        client = OpenAI(api_key=openai_key.strip())
        resp = client.responses.create(
            model="gpt-5-mini",
            input=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        )
        return getattr(resp, "output_text", None) or "⚠️ 리포트 텍스트를 가져오지 못했어요."
    except Exception as e:
        return f"❌ 리포트 생성 실패: {e}"


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
    # 데모 6일 + 오늘 합쳐서 7일 차트 만들 거라서, 여기서는 비워둬도 OK
    st.session_state.history = []


# Sidebar
st.sidebar.header("🔑 API Key")
openai_key = st.sidebar.text_input("OpenAI API Key", type="password", value=os.getenv("OPENAI_API_KEY", ""))
weather_key = st.sidebar.text_input("OpenWeatherMap API Key", type="password", value=os.getenv("OPENWEATHERMAP_API_KEY", ""))

st.title("📊 AI 습관 트래커")

# Top controls
city = st.selectbox("🌍 도시 선택", CITIES, index=0)
coach = st.radio("🎙️ 코치 스타일", COACHES, horizontal=True, index=1)

st.divider()

# Habit check-in (2 columns)
st.subheader("✅ 오늘의 습관 체크인")

c1, c2 = st.columns(2)
keys = list(HABITS.keys())

with c1:
    v0 = st.checkbox(HABITS[keys[0]])
    v1 = st.checkbox(HABITS[keys[1]])
    v2 = st.checkbox(HABITS[keys[2]])
with c2:
    v3 = st.checkbox(HABITS[keys[3]])
    v4 = st.checkbox(HABITS[keys[4]])

habits = {
    keys[0]: v0,
    keys[1]: v1,
    keys[2]: v2,
    keys[3]: v3,
    keys[4]: v4,
}

mood = st.slider("🙂 오늘 기분은?", 1, 10, 6)

done = sum(1 for v in habits.values() if v)
total = len(habits)
achievement = int(round((done / total) * 100))

# Metrics
m1, m2, m3 = st.columns(3)
m1.metric("달성률", f"{achievement}%")
m2.metric("달성 습관", f"{done}/{total}")
m3.metric("기분", f"{mood}/10")

st.divider()

# 7-day chart (6 demo + today)
today = datetime.now().date()
demo = []
pattern = [3, 4, 2, 5, 1, 4]  # 6일 샘플(달성 개수)
moods =   [6, 7, 5, 8, 4, 7]
for i in range(6, 0, -1):
    d = today - timedelta(days=i)
    idx = 6 - i
    demo.append({"date": d.isoformat(), "achievement": int(round(pattern[idx] / total * 100)), "mood": moods[idx]})

demo.append({"date": today.isoformat(), "achievement": achievement, "mood": mood})
df = pd.DataFrame(demo)

st.subheader("📈 최근 7일 달성률")
chart = alt.Chart(df).mark_bar().encode(
    x=alt.X("date:N", title="날짜"),
    y=alt.Y("achievement:Q", title="달성률(%)", scale=alt.Scale(domain=[0, 100])),
    tooltip=["date", "achievement", "mood"]
).properties(height=260)
st.altair_chart(chart, use_container_width=True)

st.divider()

# Generate report
st.subheader("🧠 AI 코치 리포트")
if st.button("컨디션 리포트 생성", type="primary"):
    with st.spinner("날씨/강아지 불러오는 중..."):
        weather = get_weather(city, weather_key)
        dog = get_dog_image()
    with st.spinner("AI 리포트 생성 중..."):
        report = generate_report(openai_key, coach, habits, mood, weather, dog)

    left, right = st.columns(2)

    with left:
        st.markdown("#### 🌦️ 날씨")
        if weather:
            st.write(f"{weather['city']} · {weather['description']}")
            st.write(f"🌡️ {weather['temp_c']:.1f}°C (체감 {weather['feels_like_c']:.1f}°C)")
            st.write(f"💧 습도 {weather['humidity']}% · 🌬️ {weather['wind_ms']:.1f}m/s")
        else:
            st.info("날씨 정보를 불러오지 못했어요.")

    with right:
        st.markdown("#### 🐶 오늘의 강아지")
        if dog:
            st.write(f"품종: {dog.get('breed','unknown')}")
            st.image(dog["image_url"], use_container_width=True)
        else:
            st.info("강아지 정보를 불러오지 못했어요.")

    st.markdown("#### 📝 리포트")
    st.markdown(report)

    share = [
        f"📊 AI 습관 트래커 ({today.isoformat()})",
        f"도시: {city} | 코치: {coach}",
        f"달성률: {achievement}% ({done}/{total}) | 기분: {mood}/10",
        f"날씨: {weather['description']} {weather['temp_c']:.1f}°C" if weather else "날씨: (없음)",
        f"강아지: {dog.get('breed','unknown')}" if dog else "강아지: (없음)",
        "",
        "🧠 리포트",
        report,
    ]
    st.markdown("#### 📣 공유용 텍스트")
    st.code("\n".join(share), language="text")

with st.expander("🔎 API 안내"):
    st.markdown(
        """
- OpenAI API Key: 사이드바에 입력(또는 환경변수 `OPENAI_API_KEY`)
- OpenWeatherMap API Key: 사이드바에 입력(또는 환경변수 `OPENWEATHERMAP_API_KEY`)
- Dog CEO API는 키 없이 사용됩니다.
"""
    )



