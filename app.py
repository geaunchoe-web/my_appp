# app.py
import os
import re
import json
from datetime import datetime, timedelta

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


def generate_report(openai_key, coach_style, habits, mood, weather, dog, daily_note):
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
        "note": daily_note or "없음",
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


def build_ics_event(date_str, score, note):
    summary = f"습관 체크인 {score}/100"
    description = note or "메모 없음"
    dtstamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    return "\n".join(
        [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//AI Habit Tracker//KR",
            "BEGIN:VEVENT",
            f"UID:{date_str}-habit-checkin",
            f"DTSTAMP:{dtstamp}",
            f"DTSTART;VALUE=DATE:{date_str.replace('-', '')}",
            f"SUMMARY:{summary}",
            f"DESCRIPTION:{description}",
            "END:VEVENT",
            "END:VCALENDAR",
        ]
    )


def generate_chat_reply(openai_key, coach_style, user_message):
    if OpenAI is None or not openai_key:
        tone = {
            "스파르타 코치": "짧고 단호하게",
            "따뜻한 멘토": "따뜻하게",
            "게임 마스터": "퀘스트처럼",
        }.get(coach_style, "따뜻하게")
        return f"{tone} 답할게요. 오늘 할 수 있는 작은 행동 하나만 정해볼까요?"

    system = SYSTEM_PROMPTS.get(coach_style, SYSTEM_PROMPTS["따뜻한 멘토"])
    prompt = (
        "너는 습관 코치다. 짧고 대화하듯 답하고, 질문 1개로 끝낸다.\n"
        f"사용자 메시지: {user_message}"
    )
    try:
        client = OpenAI(api_key=openai_key.strip())
        resp = client.responses.create(
            model="gpt-5-mini",
            input=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        )
        return getattr(resp, "output_text", None) or "지금은 답변을 만들기 어려워요."
    except Exception as e:
        return f"❌ 대화 생성 실패: {e}"


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
if "water_cups" not in st.session_state:
    st.session_state.water_cups = 0
if "exercise_minutes" not in st.session_state:
    st.session_state.exercise_minutes = 0
if "exercise_type" not in st.session_state:
    st.session_state.exercise_type = "🚶 걷기"
if "exercise_intensity" not in st.session_state:
    st.session_state.exercise_intensity = "🙂 가벼움"
if "study_pomodoros" not in st.session_state:
    st.session_state.study_pomodoros = 0
if "sleep_hours" not in st.session_state:
    st.session_state.sleep_hours = "7"
if "sleep_regular" not in st.session_state:
    st.session_state.sleep_regular = "⏰ 일정"
if "sleep_quality" not in st.session_state:
    st.session_state.sleep_quality = "🙂 보통"
if "wake_success" not in st.session_state:
    st.session_state.wake_success = True
if "wake_time" not in st.session_state:
    st.session_state.wake_time = "☀️ 7시대"
if "wake_routines" not in st.session_state:
    st.session_state.wake_routines = set()
if "checkin_summary" not in st.session_state:
    st.session_state.checkin_summary = None
if "mood_score" not in st.session_state:
    st.session_state.mood_score = 6
if "daily_note" not in st.session_state:
    st.session_state.daily_note = ""
if "chat_messages" not in st.session_state:
    st.session_state.chat_messages = []


# Sidebar
st.sidebar.header("🔑 API Key")
openai_key = st.sidebar.text_input("OpenAI API Key", type="password", value=os.getenv("OPENAI_API_KEY", ""))
weather_key = st.sidebar.text_input("OpenWeatherMap API Key", type="password", value=os.getenv("OPENWEATHERMAP_API_KEY", ""))

st.title("📊 AI 습관 트래커")

# Top controls
city = st.selectbox("🌍 도시 선택", CITIES, index=0)
coach = st.radio("🎙️ 코치 스타일", COACHES, horizontal=True, index=1)

st.divider()

# Habit check-in (tab-based mini UI)
st.subheader("✅ 오늘의 습관 체크인")

tabs = st.tabs(["💧 물", "🏃 운동", "📚 공부", "😴 수면", "⏰ 기상"])

with tabs[0]:
    st.markdown("#### 🥛 물 마시기")
    water_goal = 8
    water_cols = st.columns([1, 1, 2])
    if water_cols[0].button("➖", key="water_minus"):
        st.session_state.water_cups = max(0, st.session_state.water_cups - 1)
    if water_cols[1].button("➕", key="water_plus"):
        st.session_state.water_cups = min(water_goal, st.session_state.water_cups + 1)
    water_cols[2].markdown(
        f"{'🥛' * st.session_state.water_cups}{'⬜' * (water_goal - st.session_state.water_cups)}"
    )
    st.write(f"현재 {st.session_state.water_cups}/{water_goal}컵")

with tabs[1]:
    st.markdown("#### 🏃 운동하기")
    st.session_state.exercise_type = st.radio(
        "종류", ["🚶 걷기", "🏋️ 근력", "🧘 스트레칭", "🏃 유산소", "🏀 기타"], horizontal=True
    )
    st.session_state.exercise_intensity = st.radio(
        "강도", ["🙂 가벼움", "😅 보통", "🥵 빡셈"], horizontal=True
    )
    ex_cols = st.columns([1, 1, 1, 2])
    if ex_cols[0].button("+5분", key="ex_plus_5"):
        st.session_state.exercise_minutes += 5
    if ex_cols[1].button("+10분", key="ex_plus_10"):
        st.session_state.exercise_minutes += 10
    if ex_cols[2].button("+20분", key="ex_plus_20"):
        st.session_state.exercise_minutes += 20
    if ex_cols[3].button("리셋", key="ex_reset"):
        st.session_state.exercise_minutes = 0
    st.write(f"누적 시간: {st.session_state.exercise_minutes}분")

with tabs[2]:
    st.markdown("#### 📚 공부/독서")
    study_cols = st.columns([1, 1, 2])
    if study_cols[0].button("➖", key="study_minus"):
        st.session_state.study_pomodoros = max(0, st.session_state.study_pomodoros - 1)
    if study_cols[1].button("➕", key="study_plus"):
        st.session_state.study_pomodoros += 1
    token = "🍅" * st.session_state.study_pomodoros
    study_cols[2].markdown(token or "⬜")
    total_minutes = st.session_state.study_pomodoros * 25
    st.write(f"🍅 x {st.session_state.study_pomodoros} = {total_minutes}분")
    if st.session_state.study_pomodoros >= 4:
        st.success("🔥 연속 집중 배지 획득!")

with tabs[3]:
    st.markdown("#### 😴 수면")
    st.session_state.sleep_hours = st.radio(
        "수면시간", ["5↓", "6", "7", "8", "9+"], horizontal=True
    )
    st.session_state.sleep_regular = st.radio(
        "규칙성", ["⏰ 일정", "😵 들쭉", "🌙 늦잠"], horizontal=True
    )
    st.session_state.sleep_quality = st.radio(
        "숙면감", ["😪 낮음", "🙂 보통", "😴 좋음"], horizontal=True
    )

with tabs[4]:
    st.markdown("#### ⏰ 기상 미션")
    st.session_state.wake_success = st.toggle("기상 성공", value=st.session_state.wake_success)
    st.session_state.wake_time = st.radio(
        "기상 시간대", ["🌅 6시대", "☀️ 7시대", "☁️ 8시대", "🌤️ 9시+"], horizontal=True
    )
    routine_cols = st.columns(3)
    routine_map = {"🧼 세수": "wash", "🛏️ 이불정리": "bed", "🧹 정리": "clean"}
    for idx, (label, key) in enumerate(routine_map.items()):
        if routine_cols[idx].button(label, key=f"routine_{key}"):
            if key in st.session_state.wake_routines:
                st.session_state.wake_routines.remove(key)
            else:
                st.session_state.wake_routines.add(key)
    if st.session_state.wake_routines:
        st.write(f"완료 루틴: {len(st.session_state.wake_routines)}개")
    else:
        st.write("완료 루틴: 0개")

st.markdown("### 🙂 오늘 기분")
mood_options = [
    ("😵", 2, "매우 낮음"),
    ("😕", 4, "낮음"),
    ("🙂", 6, "보통"),
    ("😄", 8, "좋음"),
    ("🤩", 10, "매우 좋음"),
]
mood_cols = st.columns(len(mood_options))
for idx, (emoji, score, label) in enumerate(mood_options):
    if mood_cols[idx].button(f"{emoji}\n{label}", key=f"mood_{score}"):
        st.session_state.mood_score = score
st.write(f"선택된 기분: {st.session_state.mood_score}/10")

st.markdown("### 📝 오늘 한마디")
st.session_state.daily_note = st.text_input(
    "짧게 남기기", value=st.session_state.daily_note, placeholder="예) 오늘은 집중이 잘 됐다."
)

water_goal = 8
water_score = min(int(round(st.session_state.water_cups / water_goal * 20)), 20)
exercise_score = min(int(round(st.session_state.exercise_minutes / 30 * 20)), 20)
study_score = min(st.session_state.study_pomodoros * 5, 20)
sleep_base = {"5↓": 5, "6": 10, "7": 20, "8": 20, "9+": 15}[st.session_state.sleep_hours]
sleep_quality_bonus = {"😪 낮음": 0, "🙂 보통": 2, "😴 좋음": 4}[st.session_state.sleep_quality]
sleep_score = min(sleep_base + sleep_quality_bonus, 20)
wake_time_score = {"🌅 6시대": 20, "☀️ 7시대": 18, "☁️ 8시대": 12, "🌤️ 9시+": 8}[
    st.session_state.wake_time
]
wake_score = 0
if st.session_state.wake_success:
    wake_score = min(wake_time_score + len(st.session_state.wake_routines), 20)

total_score = water_score + exercise_score + study_score + sleep_score + wake_score
completion = {
    "물 마시기": st.session_state.water_cups >= water_goal,
    "운동하기": st.session_state.exercise_minutes >= 20,
    "공부/독서": st.session_state.study_pomodoros >= 1,
    "수면": sleep_score >= 15,
    "기상 미션": st.session_state.wake_success,
}
done = sum(1 for v in completion.values() if v)
total = len(completion)
achievement = int(round((total_score / 100) * 100))

# Metrics
m1, m2, m3 = st.columns(3)
m1.metric("오늘 점수", f"{total_score}/100")
m2.metric("완료 미션", f"{done}/{total}")
m3.metric("기분", f"{st.session_state.mood_score}/10")

habits = {
    "기상 미션": completion["기상 미션"],
    "물 마시기": completion["물 마시기"],
    "공부/독서": completion["공부/독서"],
    "운동하기": completion["운동하기"],
    "수면": completion["수면"],
}

st.markdown("### ✅ 오늘 체크인 완료")
if st.button("오늘 체크인 완료", type="primary"):
    scores = {
        "물": water_score,
        "운동": exercise_score,
        "공부": study_score,
        "수면": sleep_score,
        "기상": wake_score,
    }
    sorted_scores = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    top_two = sorted_scores[:2]
    bottom = sorted_scores[-1]
    missions = []
    if water_score < 15:
        missions.append("🥛 물 6컵 이상 챙기기")
    if exercise_score < 15:
        missions.append("🏃 20분 이상 가볍게 움직이기")
    if study_score < 10:
        missions.append("🍅 포모도로 1회 달성")
    if sleep_score < 15:
        missions.append("😴 7~8시간 수면 시도")
    if wake_score < 15:
        missions.append("⏰ 7시대 기상에 도전")
    missions = (missions + ["✅ 오늘 기록 간단 메모 남기기"])[:3]

    st.session_state.checkin_summary = {
        "score": total_score,
        "top_two": top_two,
        "bottom": bottom,
        "missions": missions,
        "note": st.session_state.daily_note,
    }

summary = st.session_state.checkin_summary
if summary:
    st.success(f"오늘 총점: {summary['score']}/100")
    st.write(
        f"잘한 점 Top 2: {summary['top_two'][0][0]} {summary['top_two'][0][1]}점, "
        f"{summary['top_two'][1][0]} {summary['top_two'][1][1]}점"
    )
    st.write(f"아쉬운 점: {summary['bottom'][0]} {summary['bottom'][1]}점")
    st.markdown("**내일 미션 3개**")
    for idx, mission in enumerate(summary["missions"], start=1):
        st.write(f"{idx}. {mission}")
    if summary.get("note"):
        st.write(f"📝 한마디: {summary['note']}")

    ics_content = build_ics_event(today.isoformat(), summary["score"], summary.get("note", ""))
    st.download_button(
        "📅 캘린더에 추가(ICS)",
        data=ics_content,
        file_name=f"habit-checkin-{today.isoformat()}.ics",
        mime="text/calendar",
    )

st.divider()

# 7-day chart (6 demo + today)
today = datetime.now().date()
demo = []
pattern = [62, 74, 48, 85, 40, 70]  # 6일 샘플(총점)
moods = [6, 7, 5, 8, 4, 7]
for i in range(6, 0, -1):
    d = today - timedelta(days=i)
    idx = 6 - i
    demo.append({"date": d.isoformat(), "achievement": pattern[idx], "mood": moods[idx]})

demo.append({"date": today.isoformat(), "achievement": achievement, "mood": st.session_state.mood_score})
df = pd.DataFrame(demo)

st.subheader("📈 최근 7일 달성률")
bar = alt.Chart(df).mark_bar(color="#6C8CF5").encode(
    x=alt.X("date:N", title="날짜"),
    y=alt.Y("achievement:Q", title="달성률(%)", scale=alt.Scale(domain=[0, 100])),
    tooltip=["date", "achievement", "mood"]
).properties(height=260)
line = alt.Chart(df).mark_line(color="#FF8A65").encode(
    x="date:N",
    y=alt.Y("mood:Q", scale=alt.Scale(domain=[0, 10])),
    tooltip=["date", "achievement", "mood"],
)
points = alt.Chart(df).mark_point(color="#FF8A65", size=60).encode(
    x="date:N",
    y="mood:Q",
    tooltip=["date", "achievement", "mood"],
)
chart = alt.layer(bar, line, points).resolve_scale(y="independent")
st.altair_chart(chart, use_container_width=True)

st.divider()

# Generate report
st.subheader("🧠 AI 코치 리포트")
if st.button("컨디션 리포트 생성", type="primary"):
    with st.spinner("날씨/강아지 불러오는 중..."):
        weather = get_weather(city, weather_key)
        dog = get_dog_image()
    with st.spinner("AI 리포트 생성 중..."):
        report = generate_report(
            openai_key,
            coach,
            habits,
            st.session_state.mood_score,
            weather,
            dog,
            st.session_state.daily_note,
        )

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
        f"달성률: {achievement}% ({done}/{total}) | 기분: {st.session_state.mood_score}/10",
        f"날씨: {weather['description']} {weather['temp_c']:.1f}°C" if weather else "날씨: (없음)",
        f"강아지: {dog.get('breed','unknown')}" if dog else "강아지: (없음)",
        f"한마디: {st.session_state.daily_note}" if st.session_state.daily_note else "한마디: (없음)",
        "",
        "🧠 리포트",
        report,
    ]
    st.markdown("#### 📣 공유용 텍스트")
    st.code("\n".join(share), language="text")

st.divider()

st.subheader("💬 멘토와 대화")
for message in st.session_state.chat_messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

prompt = st.chat_input("오늘 체크인에 대해 한 줄로 이야기해볼까요?")
if prompt:
    st.session_state.chat_messages.append({"role": "user", "content": prompt})
    reply = generate_chat_reply(openai_key, coach, prompt)
    st.session_state.chat_messages.append({"role": "assistant", "content": reply})
    with st.chat_message("user"):
        st.markdown(prompt)
    with st.chat_message("assistant"):
        st.markdown(reply)

with st.expander("🔎 API 안내"):
    st.markdown(
        """
- OpenAI API Key: 사이드바에 입력(또는 환경변수 `OPENAI_API_KEY`)
- OpenWeatherMap API Key: 사이드바에 입력(또는 환경변수 `OPENWEATHERMAP_API_KEY`)
- Dog CEO API는 키 없이 사용됩니다.
"""
    )



