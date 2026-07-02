"""Streamlit demo UI for travel-buddy — a stand-in for the Next.js frontend
in case there isn't time to build it. Talks to the FastAPI backend purely
over HTTP via `requests`, so it can run against any backend instance.

Run with: streamlit run demo/app.py

Assumed backend contract (update the paths below once the real routes land):
  POST {BACKEND_URL}/sessions/upload
      multipart file "file" -> {"session_id": int, "slots": [
          {"field": str, "value": str, "status": "confirmed"|"undecided"|"conflict",
           "confidence": float, "evidence_message_ids": [int]}, ...]}
  POST {BACKEND_URL}/sessions/{session_id}/itinerary
      json {"days": int} -> {
          "narrative": {"days": [{"day_index": int, "narrative": str, "items": [
              {"place_name": str, "time_period": str, "arrival_time_label": str,
               "reservation_badge": "필수"|"권장"|"불필요", "selection_reason": str|None}, ...]}]},
          "iterations_used": int,
          "violations": [{"type": str, "item_id": int, "description": str}, ...],
      }
  GET {BACKEND_URL}/evaluation
      -> {"<metric_name>": number, ...}   (e.g. {"extraction_f1": 0.87, "violation_count": 2})
"""

import os

import requests
import streamlit as st

BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8000")

st.set_page_config(page_title="travel-buddy 데모", layout="wide")

_SLOT_FIELD_LABELS = {
    "destination": "목적지",
    "date": "날짜",
    "budget": "예산",
    "headcount": "인원",
    "transport": "교통수단",
    "constraint": "제약",
    "wishlist": "먹킷리스트",
}

_SLOT_STATUS_BADGES = {
    "confirmed": ("확정", "#16a34a"),
    "undecided": ("미정", "#6b7280"),
    "conflict": ("충돌", "#dc2626"),
}

# narrator.py already renders reservation_needed as a Korean label
# ("필수"/"권장"/"불필요"), so the demo colors by that label directly
# rather than the underlying English enum value.
_RESERVATION_COLORS = {
    "필수": "#dc2626",
    "권장": "#d97706",
    "불필요": "#6b7280",
}


def _badge_html(label: str, color: str) -> str:
    return (
        f'<span style="background-color:{color};color:white;padding:2px 10px;'
        f'border-radius:12px;font-size:0.85em;font-weight:600;white-space:nowrap;">'
        f"{label}</span>"
    )


def _slot_status_badge(status: str) -> str:
    label, color = _SLOT_STATUS_BADGES.get(status, (status, "#6b7280"))
    return _badge_html(label, color)


def _reservation_badge(label: str) -> str:
    return _badge_html(label, _RESERVATION_COLORS.get(label, "#6b7280"))


def _call_backend(method: str, path: str, **kwargs) -> dict | None:
    try:
        response = requests.request(method, f"{BACKEND_URL}{path}", **kwargs)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as exc:
        st.error(f"백엔드 호출 실패 ({BACKEND_URL}{path}): {exc}")
        return None


st.title("✈️ travel-buddy 데모")
st.caption("Next.js 프론트엔드가 준비되기 전 백엔드 파이프라인을 확인하기 위한 임시 UI입니다.")

with st.sidebar:
    st.subheader("설정")
    st.write(f"백엔드: `{BACKEND_URL}`")
    if st.session_state.get("session_id") is not None:
        st.write(f"현재 세션: **#{st.session_state['session_id']}**")
    if st.button("세션 초기화"):
        st.session_state.clear()
        st.rerun()

tab_upload, tab_itinerary, tab_compare = st.tabs(["대화 업로드", "일정 생성", "비교"])


# ---------------------------------------------------------------------------
# Tab 1: 대화 업로드
# ---------------------------------------------------------------------------
with tab_upload:
    st.header("카카오톡 대화 업로드")
    uploaded_file = st.file_uploader("카카오톡 대화 내보내기 (.txt)", type=["txt"])

    if uploaded_file is not None and st.button("업로드 및 슬롯 추출", type="primary"):
        with st.spinner("대화를 파싱하고 여행 슬롯을 추출하는 중..."):
            data = _call_backend(
                "POST",
                "/sessions/upload",
                files={"file": (uploaded_file.name, uploaded_file.getvalue(), "text/plain")},
                timeout=120,
            )
        if data is not None:
            st.session_state["session_id"] = data["session_id"]
            st.session_state["slots"] = data["slots"]
            st.success(f"세션 #{data['session_id']} 생성 완료 — 슬롯 {len(data['slots'])}개 추출됨")

    slots = st.session_state.get("slots")
    if slots:
        st.subheader("추출된 슬롯")
        header = st.columns([2, 4, 2])
        header[0].markdown("**항목**")
        header[1].markdown("**값**")
        header[2].markdown("**상태**")
        for slot in slots:
            cols = st.columns([2, 4, 2])
            cols[0].write(_SLOT_FIELD_LABELS.get(slot["field"], slot["field"]))
            cols[1].write(slot["value"])
            cols[2].markdown(_slot_status_badge(slot["status"]), unsafe_allow_html=True)
    else:
        st.info("아직 업로드된 대화가 없습니다. 위에서 .txt 파일을 업로드하세요.")


# ---------------------------------------------------------------------------
# Tab 2: 일정 생성
# ---------------------------------------------------------------------------
with tab_itinerary:
    st.header("일정 생성")

    session_id = st.session_state.get("session_id")
    if session_id is None:
        st.warning("먼저 '대화 업로드' 탭에서 대화를 업로드하세요.")
    else:
        days = st.number_input("여행 일수", min_value=1, max_value=14, value=2, step=1)

        if st.button("일정 생성", type="primary"):
            with st.spinner("장소 검색 → 검증 → 서사화까지 실행 중입니다 (몇 분 걸릴 수 있습니다)..."):
                result = _call_backend(
                    "POST",
                    f"/sessions/{session_id}/itinerary",
                    json={"days": int(days)},
                    timeout=300,
                )
            if result is not None:
                st.session_state["itinerary_result"] = result

    result = st.session_state.get("itinerary_result")
    if result:
        iterations_used = result.get("iterations_used", 0)
        violations = result.get("violations", [])

        if violations:
            st.warning(f"AI 검증 {iterations_used}회 수정 — 아직 {len(violations)}건의 위반이 남아있습니다.")
            with st.expander("남은 위반 내역 보기"):
                for v in violations:
                    st.write(f"- [{v.get('type')}] {v.get('description')}")
        else:
            st.success(f"AI 검증 {iterations_used}회 수정 — 모든 위반이 해결되었습니다.")

        days_data = result.get("narrative", {}).get("days", [])
        if not days_data:
            st.info("표시할 일정이 없습니다.")
        for day in days_data:
            with st.expander(f"{day['day_index'] + 1}일차", expanded=True):
                if day.get("narrative"):
                    st.write(day["narrative"])
                for item in day.get("items", []):
                    cols = st.columns([3, 2, 2, 4])
                    cols[0].markdown(
                        f"**{item.get('time_period', '')} {item.get('arrival_time_label', '')}** "
                        f"{item.get('place_name', '')}"
                    )
                    cols[1].markdown(
                        _reservation_badge(item.get("reservation_badge", "")), unsafe_allow_html=True
                    )
                    reason = item.get("selection_reason")
                    cols[3].write(reason or "—")
    elif session_id is not None:
        st.info("아직 생성된 일정이 없습니다. '일정 생성' 버튼을 눌러주세요.")


# ---------------------------------------------------------------------------
# Tab 3: 비교
# ---------------------------------------------------------------------------
with tab_compare:
    st.header("골드셋 대비 지표")

    if st.button("지표 불러오기", type="primary"):
        with st.spinner("골드셋과 비교하는 중..."):
            metrics = _call_backend("GET", "/evaluation", timeout=60)
        if metrics is not None:
            st.session_state["metrics"] = metrics

    metrics = st.session_state.get("metrics")
    if metrics:
        metric_cols = st.columns(min(len(metrics), 4) or 1)
        for i, (name, value) in enumerate(metrics.items()):
            display_value = f"{value:.2f}" if isinstance(value, float) else str(value)
            metric_cols[i % len(metric_cols)].metric(label=name, value=display_value)
    else:
        st.info("아직 불러온 지표가 없습니다. 위 버튼을 눌러 골드셋과 비교하세요.")
