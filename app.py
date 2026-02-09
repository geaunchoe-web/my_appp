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


# =========================
# App config / constants
# =========================
st.set_page_config(page_title="AI 습관 트래커", page_icon="📊", layout="wide")

TODAY = datetime.now().date()
TODAY_STR = TODAY.isoformat()

CITIES = ["Seoul", "Busan", "Incheon", "Daegu", "Daejeon", "Gwangju", "Suwon", "Ulsan", "Jeju", "Sejong"]
COACHES = ["스파르타 코치", "따뜻한 멘토", "게임 마스터"]

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


# =========================
# APIs
# =========================
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
    params = {"q": city, "appid": api_key.strip(), "units": "metric", "lang": "kr"}
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


@st.cache_data(ttl=600)
def cached_weather(city, api_key):
    return get_weather(city, api_key)


@st.cache_data(ttl=600)
def cached_dog():
    return get_dog_image()


# =========================
# AI
# =========================
def generate_report(openai_key, coach_style, habits, mood, weather, dog, daily_note):
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
        "date": TODAY_STR,
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
        error_text = str(e)
        if "invalid_api_key" in error_text or "Incorrect API key" in error_text or "401" in error_text:
            return "❌ OpenAI API Key가 유효하지 않아요. 올바른 키로 다시 시도해 주세요."
        return f"❌ 리포트 생성 실패: {e}"


def generate_chat_reply(openai_key, coach_style, user_message):
    if OpenAI is None or not openai_key:
        tone = {"스파르타 코치": "짧고 단호하게", "따뜻한 멘토": "따뜻하게", "게임 마스터": "퀘스트처럼"}.get(
            coach_style, "따뜻하게"
        )
        return f"{tone} 답할게요. 오늘 할 수 있는 작은 행동 하나만 정해볼까요?"

    system = SYSTEM_PROMPTS.get(coach_style, SYSTEM_PROMPTS["따뜻한 멘토"])
    prompt = "너는 습관 코치다. 짧고 대화하듯 답하고, 질문 1개로 끝낸다.\n" f"사용자 메시지: {user_message}"
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
        error_text = str(e)
        if "invalid_api_key" in error_text or "Incorrect API key" in error_text or "401" in error_text:
            return "❌ OpenAI API Key가 유효하지 않아요. 올바른 키로 다시 시도해 주세요."
        return f"❌ 대화 생성 실패: {e}"


# =========================
# Utilities
# =========================
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


def init_state():
    defaults = {
        "history": [],  # 실제 저장은 체크인 완료 시에만
        "water_cups": 0,
        "exercise_minutes": 0,
        "exercise_type": "🚶 걷기",
        "exercise_intensity": "🙂 가벼움",
        "study_pomodoros": 0,
        "sleep_hours": "7",
        "sleep_regular": "⏰ 일정",
        "sleep_quality": "🙂 보통",
        "wake_success": True,
        "wake_time": "☀️ 7시대",
        "wake_routines": set(),
        "mood_score": 6,
        "daily_note": "",
        "checkin": {},  # {date: { ... }}
        "checkin_done_today": False,
        "last_report": None,
        "last_weather": None,
        "last_dog": None,
        "chat_messages": [],
    }
    for k, v in defaults.items():
        st.session_state.setdefault(k, v)

    # 날짜 바뀌면 오늘 체크인 상태 리셋(값들은 사용자가 원하면 유지해도 되지만, 여기선 완료여부만 리셋)
    if st.session_state.get("checkin_date") != TODAY_STR:
        st.session_state["checkin_date"] = TODAY_STR
        st.session_state["checkin_done_today"] = TODAY_STR in st.session_state["checkin"]


def compute_scores():
    water_goal = 8
    water_score = min(int(round(st.session_state.water_cups / water_goal * 20)), 20)
    exercise_score = min(int(round(st.session_state.exercise_minutes / 30 * 20)), 20)
    study_score = min(st.session_state.study_pomodoros * 5, 20)

    sleep_base = {"5↓": 5, "6": 10, "7": 20, "8": 20, "9+": 15}[st.session_state.sleep_hours]
    sleep_quality_bonus = {"😪 낮음": 0, "🙂 보통": 2, "😴 좋음": 4}[st.session_state.sleep_quality]
    sleep_score = min(sleep_base + sleep_quality_bonus, 20)

    wake_time_score = {"🌅 6시대": 20, "☀️ 7시대": 18, "☁️ 8시대": 12, "🌤️ 9시+": 8}[st.session_state.wake_time]
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

    per_scores = {"물": water_score, "운동": exercise_score, "공부": study_score, "수면": sleep_score, "기상": wake_score}
    return total_score, per_scores, completion


def build_feedback(per_scores):
    sorted_scores = sorted(per_scores.items(), key=lambda item: item[1], reverse=True)
    top_two = sorted_scores[:2]
    bottom = sorted_scores[-1]

    missions = []
    if per_scores["물"] < 15:
        missions.append("🥛 물 6컵 이상 챙기기")
    if per_scores["운동"] < 15:
        missions.append("🏃 20분 이상 가볍게 움직이기")
    if per_scores["공부"] < 10:
        missions.append("🍅 포모도로 1회 달성")
    if per_scores["수면"] < 15:
        missions.append("😴 7~8시간 수면 시도")
    if per_scores["기상"] < 15:
        missions.append("⏰ 7시대 기상에 도전")
    missions = (missions + ["✅ 오늘 기록 간단 메모 남기기"])[:3]

    return top_two, bottom, missions


def update_history_if_needed(score, mood):
    # 체크인 완료 시에만 저장. 하루 1회 갱신.
    history = st.session_state.history
    existing_idx = next((i for i, x in enumerate(history) if x.get("date") == TODAY_STR), None)
    row = {"date": TODAY_STR, "achievement": score, "mood": mood}
    if existing_idx is None:
        history.append(row)
    else:
        history[existing_idx] = row
    st.session_state.history = history


def demo_last_6_days():
    demo = []
    pattern = [62, 74, 48, 85, 40, 70]
    moods = [6, 7, 5, 8, 4, 7]
    for i in range(6, 0, -1):
        d = TODAY - timedelta(days=i)
        idx = 6 - i
        demo.append({"date": d.isoformat(), "achievement": pattern[idx], "mood": moods[idx]})
    return demo


# =========================
# UI sections
# =========================
def render_sidebar():
    st.sidebar.header("🔑 API Key")
    openai_key = st.sidebar.text_input("OpenAI API Key", type="password", value=os.getenv("OPENAI_API_KEY", ""))
    weather_key = st.sidebar.text_input(
        "OpenWeatherMap API Key", type="password", value=os.getenv("OPENWEATHERMAP_API_KEY", "")
    )
    st.sidebar.caption("키는 세션에만 유지돼요.")
    return openai_key, weather_key


def render_header():
    st.title("📊 AI 습관 트래커")
    left, right = st.columns([1, 2])
    with left:
        city = st.selectbox("🌍 도시 선택", CITIES, index=0)
    with right:
        coach = st.radio("🎙️ 코치 스타일", COACHES, horizontal=True, index=1)
    return city, coach


def render_checkin_tabs():
    st.subheader("✅ 오늘의 습관 체크인")
    tabs = st.tabs(["💧 물", "🏃 운동", "📚 공부", "😴 수면", "⏰ 기상"])

    # 물
    with tabs[0]:
        st.markdown("#### 🥛 물 마시기")
        water_goal = 8
        c1, c2, c3 = st.columns([1, 1, 3])
        if c1.button("➖", key="water_minus"):
            st.session_state.water_cups = max(0, st.session_state.water_cups - 1)
        if c2.button("➕", key="water_plus"):
            st.session_state.water_cups = min(water_goal, st.session_state.water_cups + 1)
        c3.markdown(f"{'🥛' * st.session_state.water_cups}{'⬜' * (water_goal - st.session_state.water_cups)}")
        st.caption(f"현재 {st.session_state.water_cups}/{water_goal}컵")

    # 운동
    with tabs[1]:
        st.markdown("#### 🏃 운동하기")
        st.session_state.exercise_type = st.radio("종류", ["🚶 걷기", "🏋️ 근력", "🧘 스트레칭", "🏃 유산소", "🏀 기타"], horizontal=True)
        st.session_state.exercise_intensity = st.radio("강도", ["🙂 가벼움", "😅 보통", "🥵 빡셈"], horizontal=True)
        a, b, c, d = st.columns([1, 1, 1, 1])
        if a.button("+5분", key="ex_plus_5"):
            st.session_state.exercise_minutes += 5
        if b.button("+10분", key="ex_plus_10"):
            st.session_state.exercise_minutes += 10
        if c.button("+20분", key="ex_plus_20"):
            st.session_state.exercise_minutes += 20
        if d.button("리셋", key="ex_reset"):
            st.session_state.exercise_minutes = 0
        st.caption(f"누적 시간: {st.session_state.exercise_minutes}분")

    # 공부
    with tabs[2]:
        st.markdown("#### 📚 공부/독서")
        a, b, c = st.columns([1, 1, 3])
        if a.button("➖", key="study_minus"):
            st.session_state.study_pomodoros = max(0, st.session_state.study_pomodoros - 1)
        if b.button("➕", key="study_plus"):
            st.session_state.study_pomodoros += 1
        token = "🍅" * st.session_state.study_pomodoros
        c.markdown(token or "⬜")
        total_minutes = st.session_state.study_pomodoros * 25
        st.caption(f"🍅 x {st.session_state.study_pomodoros} = {total_minutes}분")
        if st.session_state.study_pomodoros >= 4:
            st.success("🔥 연속 집중 배지 획득!")

    # 수면
    with tabs[3]:
        st.markdown("#### 😴 수면")
        st.session_state.sleep_hours = st.radio("수면시간", ["5↓", "6", "7", "8", "9+"], horizontal=True)
        st.session_state.sleep_regular = st.radio("규칙성", ["⏰ 일정", "😵 들쭉", "🌙 늦잠"], horizontal=True)
        st.session_state.sleep_quality = st.radio("숙면감", ["😪 낮음", "🙂 보통", "😴 좋음"], horizontal=True)

    # 기상
    with tabs[4]:
        st.markdown("#### ⏰ 기상 미션")
        st.session_state.wake_success = st.toggle("기상 성공", value=st.session_state.wake_success)
        st.session_state.wake_time = st.radio("기상 시간대", ["🌅 6시대", "☀️ 7시대", "☁️ 8시대", "🌤️ 9시+"], horizontal=True)

        routine_cols = st.columns(3)
        routine_map = {"🧼 세수": "wash", "🛏️ 이불정리": "bed", "🧹 정리": "clean"}
        for idx, (label, key) in enumerate(routine_map.items()):
            if routine_cols[idx].button(label, key=f"routine_{key}"):
                if key in st.session_state.wake_routines:
                    st.session_state.wake_routines.remove(key)
                else:
                    st.session_state.wake_routines.add(key)
        st.caption(f"완료 루틴: {len(st.session_state.wake_routines)}개")


def render_mood_and_note():
    st.markdown("### 🙂 오늘 기분")
    mood_options = [("😵", 2, "매우 낮음"), ("😕", 4, "낮음"), ("🙂", 6, "보통"), ("😄", 8, "좋음"), ("🤩", 10, "매우 좋음")]
    cols = st.columns(len(mood_options))
    for idx, (emoji, score, label) in enumerate(mood_options):
        if cols[idx].button(f"{emoji}\n{label}", key=f"mood_{score}"):
            st.session_state.mood_score = score
    st.caption(f"선택된 기분: {st.session_state.mood_score}/10")

    st.markdown("### 📝 오늘 한마디")
    st.session_state.daily_note = st.text_input("짧게 남기기", value=st.session_state.daily_note, placeholder="예) 오늘은 집중이 잘 됐다.")


def render_metrics(total_score, completion):
    done = sum(1 for v in completion.values() if v)
    total = len(completion)
    m1, m2, m3 = st.columns(3)
    m1.metric("오늘 점수", f"{total_score}/100")
    m2.metric("완료 미션", f"{done}/{total}")
    m3.metric("기분", f"{st.session_state.mood_score}/10")
    return done, total


def render_checkin_actions(total_score, per_scores, completion):
    st.markdown("### ✅ 오늘 체크인 완료")

    if st.session_state.checkin_done_today:
        st.info("오늘 체크인은 이미 완료했어요. 아래 요약과 리포트를 확인해 주세요.")
        return

    if st.button("오늘 체크인 완료", type="primary"):
        top_two, bottom, missions = build_feedback(per_scores)
        # 저장(오늘 1회)
        st.session_state.checkin[TODAY_STR] = {
            "date": TODAY_STR,
            "score": total_score,
            "per_scores": per_scores,
            "completion": completion,
            "mood": st.session_state.mood_score,
            "note": st.session_state.daily_note,
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
        st.session_state.checkin_done_today = True
        update_history_if_needed(total_score, st.session_state.mood_score)

        st.session_state.checkin_summary = {
            "score": total_score,
            "top_two": top_two,
            "bottom": bottom,
            "missions": missions,
            "note": st.session_state.daily_note,
        }
        st.rerun()


def render_summary():
    summary = st.session_state.get("checkin_summary")
    if not summary:
        # 체크인 완료된 경우에도 summary가 없다면 기록에서 생성
        if st.session_state.checkin_done_today and TODAY_STR in st.session_state.checkin:
            rec = st.session_state.checkin[TODAY_STR]
            top_two, bottom, missions = build_feedback(rec["per_scores"])
            summary = {
                "score": rec["score"],
                "top_two": top_two,
                "bottom": bottom,
                "missions": missions,
                "note": rec.get("note", ""),
            }
            st.session_state.checkin_summary = summary
        else:
            return

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

    ics_content = build_ics_event(TODAY_STR, summary["score"], summary.get("note", ""))
    st.download_button(
        "📅 캘린더에 추가(ICS)",
        data=ics_content,
        file_name=f"habit-checkin-{TODAY_STR}.ics",
        mime="text/calendar",
        use_container_width=True,
    )


def render_chart():
    st.subheader("📈 최근 7일 (점수/기분)")

    # demo 6일 + (오늘은 체크인 완료했으면 실제 history 사용, 아니면 미리보기로 현재 값 반영)
    demo = demo_last_6_days()

    # 오늘 값: 체크인 완료면 history, 아니면 현재 계산 값
    if st.session_state.checkin_done_today and st.session_state.history:
        today_row = next((x for x in st.session_state.history if x.get("date") == TODAY_STR), None)
        if not today_row:
            # 혹시 없으면 체크인 기록 기반으로 생성
            rec = st.session_state.checkin.get(TODAY_STR)
            if rec:
                today_row = {"date": TODAY_STR, "achievement": rec["score"], "mood": rec["mood"]}
    else:
        total_score, _, _ = compute_scores()
        today_row = {"date": TODAY_STR, "achievement": total_score, "mood": st.session_state.mood_score}

    rows = demo + [today_row]
    df = pd.DataFrame(rows)

    bar = alt.Chart(df).mark_bar().encode(
        x=alt.X("date:N", title="날짜"),
        y=alt.Y("achievement:Q", title="오늘 점수(0~100)", scale=alt.Scale(domain=[0, 100])),
        tooltip=["date", "achievement", "mood"],
    ).properties(height=260)

    line = alt.Chart(df).mark_line().encode(
        x="date:N",
        y=alt.Y("mood:Q", title="기분(0~10)", scale=alt.Scale(domain=[0, 10])),
        tooltip=["date", "achievement", "mood"],
    )
    points = alt.Chart(df).mark_point(size=60).encode(x="date:N", y="mood:Q", tooltip=["date", "achievement", "mood"])

    chart = alt.layer(bar, line, points).resolve_scale(y="independent")
    st.altair_chart(chart, use_container_width=True)


def render_ai_report(openai_key, weather_key, city, coach):
    st.subheader("🧠 AI 코치 리포트")

    if not st.session_state.checkin_done_today:
        st.info("리포트는 **'오늘 체크인 완료'** 후에 생성할 수 있어요.")
        return

    if st.button("컨디션 리포트 생성", type="primary"):
        with st.spinner("날씨/강아지 불러오는 중..."):
            weather = cached_weather(city, weather_key) if weather_key else None
            dog = cached_dog()
        st.session_state.last_weather = weather
        st.session_state.last_dog = dog

        # 체크인 완료 기록 기반 habits
        rec = st.session_state.checkin.get(TODAY_STR, {})
        completion = rec.get("completion", {})
        habits = {
            "기상 미션": bool(completion.get("기상 미션")),
            "물 마시기": bool(completion.get("물 마시기")),
            "공부/독서": bool(completion.get("공부/독서")),
            "운동하기": bool(completion.get("운동하기")),
            "수면": bool(completion.get("수면")),
        }

        with st.spinner("AI 리포트 생성 중..."):
            report = generate_report(
                openai_key=openai_key,
                coach_style=coach,
                habits=habits,
                mood=rec.get("mood", st.session_state.mood_score),
                weather=weather,
                dog=dog,
                daily_note=rec.get("note", st.session_state.daily_note),
            )
        st.session_state.last_report = report

    weather = st.session_state.get("last_weather")
    dog = st.session_state.get("last_dog")
    report = st.session_state.get("last_report")

    left, right = st.columns(2)
    with left:
        st.markdown("#### 🌦️ 날씨")
        if weather:
            st.write(f"{weather['city']} · {weather['description']}")
            st.write(f"🌡️ {weather['temp_c']:.1f}°C (체감 {weather['feels_like_c']:.1f}°C)")
            st.write(f"💧 습도 {weather['humidity']}% · 🌬️ {weather['wind_ms']:.1f}m/s")
        else:
            st.caption("날씨 정보 없음 (키 미입력/호출 실패)")

    with right:
        st.markdown("#### 🐶 오늘의 강아지")
        if dog:
            st.write(f"품종: {dog.get('breed', 'unknown')}")
            st.image(dog["image_url"], use_container_width=True)
        else:
            st.caption("강아지 정보 없음")

    st.markdown("#### 📝 리포트")
    if report:
        st.markdown(report)
    else:
        st.caption("아직 리포트를 생성하지 않았어요.")

    # 공유 텍스트
    if st.session_state.checkin_done_today and TODAY_STR in st.session_state.checkin:
        rec = st.session_state.checkin[TODAY_STR]
        score = rec.get("score", 0)
        mood = rec.get("mood", st.session_state.mood_score)
        note = rec.get("note", "")
        share = [
            f"📊 AI 습관 트래커 ({TODAY_STR})",
            f"도시: {city} | 코치: {coach}",
            f"오늘 점수: {score}/100 | 기분: {mood}/10",
            f"날씨: {weather['description']} {weather['temp_c']:.1f}°C" if weather else "날씨: (없음)",
            f"강아지: {dog.get('breed','unknown')}" if dog else "강아지: (없음)",
            f"한마디: {note}" if note else "한마디: (없음)",
            "",
            "🧠 리포트",
            report or "(리포트 없음)",
        ]
        st.markdown("#### 📣 공유용 텍스트")
        st.code("\n".join(share), language="text")


def render_chat(openai_key, coach):
    st.subheader("💬 멘토와 대화")

    for message in st.session_state.chat_messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    prompt = st.chat_input("오늘 체크인에 대해 한 줄로 이야기해볼까요?")
    if prompt:
        st.session_state.chat_messages.append({"role": "user", "content": prompt})
        reply = generate_chat_reply(openai_key, coach, prompt)
        st.session_state.chat_messages.append({"role": "assistant", "content": reply})
        st.rerun()


def render_api_info():
    with st.expander("🔎 API 안내"):
        st.markdown(
            """
- OpenAI API Key: 사이드바에 입력(또는 환경변수 `OPENAI_API_KEY`)
- OpenWeatherMap API Key: 사이드바에 입력(또는 환경변수 `OPENWEATHERMAP_API_KEY`)
- Dog CEO API는 키 없이 사용됩니다.
"""
        )


# =========================
# Main
# =========================
init_state()
openai_key, weather_key = render_sidebar()
city, coach = render_header()

st.divider()

# 1) 체크인 영역
if not st.session_state.checkin_done_today:
    render_checkin_tabs()
    render_mood_and_note()

total_score, per_scores, completion = compute_scores()
done, total = render_metrics(total_score, completion)
render_checkin_actions(total_score, per_scores, completion)

# 2) 요약(완료 후 상단에 고정 느낌)
render_summary()

st.divider()

# 3) 차트
render_chart()

st.divider()

# 4) 리포트
render_ai_report(openai_key, weather_key, city, coach)

st.divider()

# 5) 대화
render_chat(openai_key, coach)

# 6) 안내
render_api_info()



