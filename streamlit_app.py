import streamlit as st
import pandas as pd
from datetime import datetime
import upbit_swing

st.set_page_config(
    page_title="업비트 스윙 분석기 V3",
    page_icon="📈",
    layout="wide",
)

st.title("📈 업비트 스윙 분석기 V3.2 — 오전 11시 추천")
st.caption("매일 오전 11시 기준 · 10~15개 상위 후보 · 눌림 진입 우선 · 급등 추격매수 강력 차단")

st.info(
    "V3는 점수가 높아도 급등·과열·R:R 부족이면 신규 매수를 막습니다. "
    "추천이 없으면 '추천할 코인이 없는 것'이 정상입니다."
)

col1, col2, col3 = st.columns([2, 1, 1])
with col1:
    max_coins = st.slider(
        "전체 시장에서 먼저 분석할 상위 거래대금 코인 수",
        min_value=20,
        max_value=40,
        value=40,
        step=5,
    )
with col2:
    display_count = st.slider(
        "화면에 보여줄 후보 수",
        min_value=10,
        max_value=15,
        value=15,
        step=1,
    )
with col3:
    refresh = st.button("🔄 오전 11시 추천 새로 분석", use_container_width=True)

@st.cache_data(ttl=300, show_spinner=False)
def get_results(limit):
    return upbit_swing.scan_market(limit)

if refresh:
    get_results.clear()

with st.spinner("업비트 데이터를 분석하는 중입니다..."):
    results, errors = get_results(max_coins)

now = datetime.now()
st.caption("분석시간: " + now.strftime("%Y-%m-%d %H:%M:%S"))
if now.hour == 11:
    st.success("🕚 현재 오전 11시 분석 시간대입니다. 아래 결과를 오늘의 우선 후보로 확인하세요.")
else:
    st.info("🕚 권장 분석 시간은 매일 오전 11시입니다. 지금 분석 버튼을 누르면 현재 시점 데이터로 다시 계산합니다.")

if errors:
    with st.expander(f"일부 분석 오류 {len(errors)}건"):
        st.write("\n".join(errors[:20]))

if not results:
    st.error("분석 결과를 가져오지 못했습니다.")
    st.stop()

# -------------------------------
# 추천 후보
# -------------------------------
buy_candidates = [r for r in results if r["decision"] == "매수 후보"]
waiting = [
    r for r in results
    if r["decision"] in [
        "매수 대기 - 눌림 필요",
        "관심 - 눌림 확인",
        "관심 - 15분 반등 확인 대기",
    ]
]

a, b, c, d = st.columns(4)
a.metric("분석 종목", f"{len(results)}개")
b.metric("매수 후보", f"{len(buy_candidates)}개")
c.metric("눌림/확인 대기", f"{len(waiting)}개")
d.metric("추격 차단", f"{sum(r['chase_blocked'] for r in results)}개")

if buy_candidates:
    best = buy_candidates[0]
    st.success(
        f"★ 1순위: {best['coin']} | {best['decision']} | "
        f"점수 {best['total_score']}점"
    )
else:
    st.warning("현재는 신규 진입을 서두를 확실한 후보가 없습니다.")

st.divider()

# -------------------------------
# 상위 10~15개 후보
# -------------------------------
display_results = results[:display_count]
st.subheader(f"오늘의 스윙 후보 TOP {len(display_results)}")
st.caption("주의: 후보 수를 채우기 위해 매수 금지 종목을 좋은 종목처럼 추천하지 않습니다. 실제 매수 후보와 눌림 대기 종목을 구분해서 보세요.")

rows = []
for i, r in enumerate(display_results, 1):
    rows.append({
        "순위": i,
        "코인": r["coin"],
        "상태": r["decision"],
        "점수": r["total_score"],
        "4H": r["score4"],
        "1H": r["score1"],
        "현재가": r["price"],
        "진입구간": f"{r['entry_low']:.6g} ~ {r['entry_high']:.6g}",
        "손절": r["stop"],
        "1차": r["target1"],
        "2차": r["target2"],
        "R:R": f"{r['rr1']:.2f} / {r['rr2']:.2f}",
        "20선이격": f"{r['distance_ma20']:+.1f}%",
        "6시간상승": f"{r['surge_6h']:+.1f}%",
        "거래량": f"{r['volume_ratio']:.1f}배",
        "15m": "확인" if r["15m_bullish"] else "대기",
    })

st.dataframe(
    pd.DataFrame(rows),
    use_container_width=True,
    hide_index=True,
)

# -------------------------------
# 상세
# -------------------------------
st.subheader("종목별 상세 판단")

for r in display_results:
    with st.expander(
        f"{r['coin']} · {r['decision']} · {r['total_score']}점",
        expanded=(r in buy_candidates[:2]),
    ):
        x1, x2, x3, x4 = st.columns(4)
        x1.metric("현재가", upbit_swing.krw(r["price"]))
        x2.metric("권장 진입가", upbit_swing.krw(r["entry_price"]))
        x3.metric("손절", upbit_swing.krw(r["stop"]))
        x4.metric("1H 거래량", f"{r['volume_ratio']:.2f}배")

        st.write(
            f"**진입 관심구간:** "
            f"{upbit_swing.krw(r['entry_low'])} ~ {upbit_swing.krw(r['entry_high'])}"
        )
        st.write(
            f"**목표:** 1차 {upbit_swing.krw(r['target1'])} / "
            f"2차 {upbit_swing.krw(r['target2'])}"
        )
        st.write(
            f"**R:R:** 1차 {r['rr1']:.2f} / 2차 {r['rr2']:.2f} · "
            f"**20선 이격:** {r['distance_ma20']:+.1f}% · "
            f"**최근 6시간:** {r['surge_6h']:+.1f}%"
        )

        if r["chase_blocked"]:
            st.error("🚫 추격매수 차단: 현재 가격을 따라가서 매수하지 않도록 설계됨.")
        elif r["chase_warning"]:
            st.warning("⚠️ 추격매수 주의: 눌림 진입을 우선 확인하세요.")

        if r["four_hour_bullish"]:
            st.success("4H: 상승 구조")
        else:
            st.warning("4H: 상승 구조 미확인")

        if r["one_hour_bearish"]:
            st.error("1H: 하락 구조")
        elif r["one_hour_bullish"]:
            st.success("1H: 상승 구조")
        else:
            st.warning("1H: 방향 확인 필요")

        if r["15m_bullish"]:
            st.success("15m: 단기 반등 확인")
        else:
            st.info("15m: 아직 반등 확인 전")

        ind = pd.DataFrame([
            {"항목": "RSI", "4H": r["rsi4"], "1H": r["rsi1"], "15m": r["rsi15"]},
            {"항목": "MA20", "4H": r["ma20_4"], "1H": r["ma20_1"], "15m": None},
            {"항목": "MA60", "4H": r["ma60_4"], "1H": r["ma60_1"], "15m": None},
            {"항목": "MACD", "4H": r["macd4"], "1H": r["macd1"], "15m": None},
        ])
        st.dataframe(ind, use_container_width=True, hide_index=True)

        st.markdown("**판단 근거 — 4H**")
        for reason in r["reasons4"]:
            st.write("• " + reason)

        st.markdown("**판단 근거 — 1H**")
        for reason in r["reasons1"]:
            st.write("• " + reason)

st.warning(
    "주의: 이 프로그램은 자동매매가 아닌 기술적 분석 보조 도구입니다. "
    "매수/매도 판단을 보장하지 않으며, 손실 가능성이 있습니다."
)
