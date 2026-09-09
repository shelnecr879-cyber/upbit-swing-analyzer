import streamlit as st
import pandas as pd
from datetime import datetime
import upbit_swing

st.set_page_config(page_title="업비트 스윙 분석기", page_icon="📈", layout="wide")

st.title("📈 업비트 4H + 1H 스윙 분석기")
st.caption("목표: 3~10일 보유 / 주 1~2회 선별 · KRW 시장")

coins = st.multiselect("분석 코인", upbit_swing.COINS, default=upbit_swing.COINS)
refresh = st.button("🔄 지금 분석")

@st.cache_data(ttl=300, show_spinner=False)
def get_results(selected):
    results = []
    for coin in selected:
        try:
            r = upbit_swing.analyze_coin(coin)
            if r:
                results.append(r)
        except Exception as e:
            st.warning(f"{coin} 분석 오류: {e}")
    return sorted(results, key=lambda x: x["total_score"], reverse=True)

if refresh or True:
    with st.spinner("업비트 데이터를 분석하는 중입니다..."):
        results = get_results(tuple(coins))

    st.caption("분석시간: " + datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    if not results:
        st.error("데이터를 가져오지 못했습니다.")
        st.stop()

    # 요약 카드
    cols = st.columns(len(results))
    for col, r in zip(cols, results):
        col.metric(f"{r['coin']} · {r['total_score']}점", upbit_swing.krw(r['price']))
        col.write(r['decision'])

    st.divider()
    st.subheader("오늘의 스윙 후보")

    rows = []
    for i, r in enumerate(results, 1):
        rows.append({
            "순위": i,
            "코인": r["coin"],
            "점수": r["total_score"],
            "4H": r["score4"],
            "1H": r["score1"],
            "현재가": r["price"],
            "진입구간": f"{r['entry_low']:.4g} ~ {r['entry_high']:.4g}",
            "손절": r["stop"],
            "1차 목표": r["target1"],
            "2차 목표": r["target2"],
            "1H 추세": "상승 확인" if r["one_hour_bullish"] else ("하락 확인" if r["one_hour_bearish"] else "중립"),
            "추천": r["decision"],
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    for r in results:
        with st.expander(f"{r['coin']} · {r['decision']} · {r['total_score']}점", expanded=True):
            a, b, c, d = st.columns(4)
            a.metric("현재가", upbit_swing.krw(r["price"]))
            b.metric("기준 진입가", upbit_swing.krw(r["entry_price"]))
            c.metric("손절", upbit_swing.krw(r["stop"]), f"{r['risk_pct']:+.1f}%")
            d.metric("1H 거래량", f"{r['volume_ratio']:.2f}배")

            st.write(f"**진입 관심구간:** {upbit_swing.krw(r['entry_low'])} ~ {upbit_swing.krw(r['entry_high'])}")
            st.write(f"**목표:** 1차 {upbit_swing.krw(r['target1'])} / 2차 {upbit_swing.krw(r['target2'])}")
            st.write(f"**R:R:** 1차 {r['rr1']:.2f} / 2차 {r['rr2']:.2f}")

            st.markdown("### 1H 추세 확인")
            if r["one_hour_bullish"]:
                st.success("상승 추세 확인 — 매수 조건을 검토할 수 있습니다.")
            elif r["one_hour_bearish"]:
                st.error("하락 추세 확인 — 보유 중이면 매도/비중축소를 검토합니다.")
            else:
                st.warning("1H 상승 추세가 아직 확인되지 않았습니다. 신규 매수는 기다립니다.")

            st.markdown("### 4H / 1H 지표")
            ind = pd.DataFrame([
                {"항목":"RSI", "4H":r["rsi4"], "1H":r["rsi1"]},
                {"항목":"MA20", "4H":r["ma20_4"], "1H":r["ma20_1"]},
                {"항목":"MA60", "4H":r["ma60_4"], "1H":r["ma60_1"]},
                {"항목":"MACD", "4H":r["macd4"], "1H":r["macd1"]},
                {"항목":"MACD Signal", "4H":r["macd4_signal"], "1H":r["macd1_signal"]},
            ])
            st.dataframe(ind, use_container_width=True, hide_index=True)

st.info("주의: 이 도구는 자동매매가 아니라 기술적 분석 보조 도구입니다. 매수/매도 추천은 규칙 기반 신호입니다.")
