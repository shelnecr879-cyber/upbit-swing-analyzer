import streamlit as st
import pandas as pd
from datetime import datetime
from zoneinfo import ZoneInfo
import upbit_swing

st.set_page_config(page_title="업비트 스윙 분석기", page_icon="📈", layout="wide")
st.title("📈 업비트 스윙 분석기 V3.4 — 오전 11시 / 5~14일 상승순위")
st.caption("오늘 매수한다고 가정했을 때 앞으로 5~14일의 상승 가능성을 기술적으로 비교 · 점수는 화면에 표시하지 않습니다.")

st.info("🕚 매일 오전 11시 기준 분석을 권장합니다. '매수추천'은 현재 진입 조건이 맞는 종목, '매수검토'는 좋은 후보지만 눌림/반등 확인이 필요한 종목입니다. '매도추천/매도검토'는 보유자 기준의 기술적 약세 신호입니다.")

col1, col2, col3 = st.columns([2, 1, 1])
with col1:
    max_coins = st.slider("먼저 분석할 상위 거래대금 종목 수", 20, 40, 40, 5)
with col2:
    display_count = st.slider("보여줄 종목 수", 10, 15, 15, 1)
with col3:
    refresh = st.button("🔄 오전 11시 추천 새로 분석", use_container_width=True)

@st.cache_data(ttl=300, show_spinner=False)
def get_results(limit):
    return upbit_swing.scan_market(limit)

if refresh:
    get_results.clear()

with st.spinner("업비트 데이터를 분석하는 중입니다..."):
    results, errors = get_results(max_coins)

now = datetime.now(ZoneInfo("Asia/Seoul"))
st.caption("분석시간(KST): " + now.strftime("%Y-%m-%d %H:%M:%S"))
if now.hour == 11:
    st.success("🕚 현재 오전 11시 분석 시간대입니다.")
else:
    st.info("🕚 권장 분석 시간은 매일 오전 11시입니다. 지금 분석하면 현재 시점 데이터로 다시 계산합니다.")

if errors:
    with st.expander(f"일부 분석 오류 {len(errors)}건"):
        st.write("\n".join(errors[:20]))

if not results:
    st.error("분석 결과를 가져오지 못했습니다.")
    st.stop()

buy_recommend = [r for r in results if r["decision"] == "매수추천"]
buy_review = [r for r in results if r["decision"] == "매수검토"]
sell_review = [r for r in results if r["decision"] == "매도검토"]
sell_recommend = [r for r in results if r["decision"] == "매도추천"]

m1, m2, m3, m4 = st.columns(4)
m1.metric("매수추천", f"{len(buy_recommend)}개")
m2.metric("매수검토", f"{len(buy_review)}개")
m3.metric("매도검토", f"{len(sell_review)}개")
m4.metric("매도추천", f"{len(sell_recommend)}개")

st.divider()
st.subheader(f"📊 오늘 매수 기준 5~14일 상승 가능성 TOP {display_count}")
st.caption("순위는 4H 추세, 1H 구조, 15분 반등, 눌림 위치, R:R, 최근 급등/변동성을 종합해 상대적으로 비교한 기술적 순위입니다. 미래 수익을 보장하는 예측값은 아닙니다.")

display_results = results[:display_count]
rows = []
for i, r in enumerate(display_results, 1):
    rows.append({
        "순위": i,
        "코인": f"{r['korean_name']} ({r['english_name']})",
        "판단": r["decision"],
        "현재가": upbit_swing.krw(r["price"]),
        "매수관심구간": f"{upbit_swing.krw(r['entry_low'])} ~ {upbit_swing.krw(r['entry_high'])}",
        "손절": upbit_swing.krw(r["stop"]),
        "1차목표": upbit_swing.krw(r["target1"]),
        "2차목표": upbit_swing.krw(r["target2"]),
        "예상보유": r["holding"],
        "5~14일": "상승 우선" if r["horizon_score"] >= 5 else "신중",
    })
st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

# 매수추천을 별도로 눈에 띄게
if buy_recommend:
    st.success("🟢 오늘의 매수추천")
    for i, r in enumerate(buy_recommend[:5], 1):
        st.write(f"**{i}. {r['korean_name']} ({r['english_name']})** — 현재 {upbit_swing.krw(r['price'])} · 매수관심구간 {upbit_swing.krw(r['entry_low'])} ~ {upbit_swing.krw(r['entry_high'])} · 5~14일 관점")
else:
    st.warning("오늘은 현재 조건에 맞는 '매수추천' 종목이 없습니다. 매수검토 종목의 눌림/반등을 기다리는 것이 우선입니다.")

st.divider()
st.subheader("종목별 상세 판단")
for r in display_results:
    title = f"{r['korean_name']} ({r['english_name']}) · {r['decision']}"
    with st.expander(title, expanded=(r["decision"] == "매수추천")):
        x1, x2, x3, x4 = st.columns(4)
        x1.metric("현재가", upbit_swing.krw(r["price"]))
        x2.metric("권장 진입가", upbit_swing.krw(r["entry_price"]))
        x3.metric("손절", upbit_swing.krw(r["stop"]))
        x4.metric("예상 보유", r["holding"])

        st.write(f"**판단:** {r['decision']}")
        st.write(f"**5~14일 상승순위:** {display_results.index(r)+1}위")
        st.write(f"**매수 관심구간:** {upbit_swing.krw(r['entry_low'])} ~ {upbit_swing.krw(r['entry_high'])}")
        st.write(f"**목표:** 1차 {upbit_swing.krw(r['target1'])} / 2차 {upbit_swing.krw(r['target2'])}")
        st.write(f"**R:R:** 1차 {r['rr1']:.2f} / 2차 {r['rr2']:.2f}")

        if r["decision"] in ("매도추천", "매도검토"):
            st.error("📉 보유 중인 경우 매도/비중축소를 검토할 수 있는 기술적 약세 신호입니다. 자동매도는 하지 않습니다.")
        elif r["chase_blocked"]:
            st.warning("🚫 현재 가격 추격매수는 차단합니다. 눌림 진입을 우선하세요.")
        elif r["chase_warning"]:
            st.warning("⚠️ 급등 추격 주의: 눌림 후 진입을 우선하세요.")

        if r.get("support_break_4h"):
            st.error(f"🔴 4H 지지선 {upbit_swing.krw(r['support4'])} 이탈 + 거래량 증가: 강한 하락 신호")
        elif r.get("support_break_1h"):
            st.warning(f"🟠 1H 지지선 {upbit_swing.krw(r['support'])} 이탈 + 거래량 증가: 매도검토")
        elif r.get("false_break_1h"):
            st.success(f"🟢 지지선 {upbit_swing.krw(r['support'])} 하회 후 회복: 가짜 이탈 가능성, 반등 확인")
        else:
            st.info(f"지지선: 1H {upbit_swing.krw(r['support'])} / 4H {upbit_swing.krw(r['support4'])}")

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
            st.info("15m: 반등 확인 전")

        ind = pd.DataFrame([
            {"항목": "RSI", "4H": r["rsi4"], "1H": r["rsi1"], "15m": r["rsi15"]},
            {"항목": "MA20", "4H": r["ma20_4"], "1H": r["ma20_1"], "15m": None},
            {"항목": "MA60", "4H": r["ma60_4"], "1H": r["ma60_1"], "15m": None},
        ])
        st.dataframe(ind, use_container_width=True, hide_index=True)

        st.markdown("**판단 근거 — 4H**")
        for reason in r["reasons4"]:
            st.write("• " + reason)
        st.markdown("**판단 근거 — 1H**")
        for reason in r["reasons1"]:
            st.write("• " + reason)

st.warning("주의: 이 프로그램은 자동매매가 아닌 기술적 분석 보조 도구입니다. '5~14일 상승순위'는 기술적 조건을 이용한 상대 순위이며 수익을 보장하지 않습니다.")
