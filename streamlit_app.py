import streamlit as st
import pandas as pd
from datetime import datetime
import upbit_swing
import pyupbit

st.set_page_config(page_title="업비트 스윙 분석기", page_icon="📈", layout="wide")

st.title("📈 업비트 4H + 1H 스윙 분석기")
st.caption("목표: 3~10일 보유 / 주 1~2회 선별 · KRW 시장")

MIN_TRADE_VALUE = 1_000_000_000
with st.spinner("업비트 KRW 전체 마켓과 거래대금을 확인하는 중입니다..."):
    AVAILABLE_COINS = upbit_swing.get_liquid_krw_coins(MIN_TRADE_VALUE)
if not AVAILABLE_COINS:
    st.error("거래대금 정보를 불러오지 못했습니다. 잠시 후 새로고침해 주세요.")
    st.stop()
upbit_swing.COINS = AVAILABLE_COINS
st.caption(f"분석 대상: KRW 전체 마켓 중 24시간 거래대금 {MIN_TRADE_VALUE:,}원 이상 · {len(AVAILABLE_COINS)}개")

# 업비트 코인 코드와 한글명 매칭
# API 응답이 늦거나 한글명이 비어도 화면에 한글명이 나오도록 기본명을 함께 사용합니다.
COIN_NAMES = {
    "BTC": "비트코인",
    "ETH": "이더리움",
    "XRP": "리플",
    "DOGE": "도지코인",
    "SOL": "솔라나",
    "ADA": "에이다",
    "AVAX": "아발란체",
    "LINK": "체인링크",
    "DOT": "폴카닷",
    "TRX": "트론",
    "WLD": "월드코인",
    "QKC": "쿼크체인",
    "DOOD": "두들즈",
    "SOPH": "소폰",
    "MTL": "메탈",
    "STEEM": "스팀",
    "XEC": "이캐시",
    "AERO": "에어로",
    "PENDLE": "펜들",
    "KNC": "카이버네트워크",
    "VET": "비체인",
    "STX": "스택스",
    "SUI": "수이",
    "APT": "앱토스",
    "ARB": "아비트럼",
    "OP": "옵티미즘",
    "NEAR": "니어프로토콜",
    "ATOM": "코스모스",
    "ETC": "이더리움 클래식",
    "BCH": "비트코인캐시",
    "LTC": "라이트코인",
    "EOS": "이오스",
    "IMX": "이뮤터블엑스",
    "INJ": "인젝티브",
    "PEPE": "페페",
    "BONK": "봉크",
    "WIF": "도그위프햇",
    "SHIB": "시바이누",
    "HBAR": "헤데라",
    "ONDO": "온도파이낸스",
    "RENDER": "렌더토큰",
}

try:
    market_items = pyupbit.get_market_all(fiat="KRW")
    if market_items:
        for item in market_items:
            market = str(item.get("market", ""))
            korean_name = str(item.get("korean_name", "")).strip()
            if market.startswith("KRW-") and korean_name:
                code = market.replace("KRW-", "")
                COIN_NAMES[code] = korean_name
except Exception:
    pass

def coin_label(code):
    code = str(code).replace("KRW-", "").strip()
    return f"{COIN_NAMES.get(code, code)} ({code})"
coins = st.multiselect("분석 코인", AVAILABLE_COINS, default=AVAILABLE_COINS)
refresh = st.button("🔄 지금 분석")

def get_results(selected):
    results = []
    for coin in selected:
        try:
            r = upbit_swing.analyze_coin(coin)
            if r:
                results.append(r)
        except Exception as e:
            st.warning(f"{coin_label(coin)} 분석 오류: {e}")
    return sorted(results, key=lambda x: x["total_score"], reverse=True)

if refresh or True:
    with st.spinner("업비트 데이터를 분석하는 중입니다..."):
        results = get_results(tuple(coins))

    st.caption("분석시간: " + datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    if not results:
        st.error("데이터를 가져오지 못했습니다.")
        st.stop()

    # 요약 카드
    # 전체 코인을 가로로 펼치면 화면이 깨지므로 상위 6개만 카드로 표시합니다.
    st.subheader("상위 스윙 후보")
    top_results = results[:6]
    cols = st.columns(min(len(top_results), 3))
    for i, r in enumerate(top_results):
        col = cols[i % len(cols)]
        with col:
            st.metric(
                f"{coin_label(r['coin'])} · {r['total_score']}점",
                upbit_swing.krw(r['price'])
            )
            st.caption(r["decision"])

    st.divider()
    st.subheader("전체 분석 결과")

    rows = []
    for i, r in enumerate(results, 1):
        rows.append({
            "순위": i,
            "코인": coin_label(r["coin"]),
            "점수": r["total_score"],
            "4H": r["score4"],
            "1H": r["score1"],
            "일봉": r["daily_score"],
            "현재가": r["price"],
            "진입구간": f"{r['entry_low']:.4g} ~ {r['entry_high']:.4g}",
            "손절": r["stop"],
            "1차 목표": r["target1"],
            "2차 목표": r["target2"],
            "일봉 추세": "상승" if r["daily_bullish"] else "하락/중립",
            "전고점 돌파": "확인" if r["daily_breakout"] else "없음",
            "지지 확인": "확인" if r["daily_support_confirmed"] else "대기",
            "고점 추격 위험": "제외" if r["daily_overextended"] else "정상",
            "1H 추세": "상승 확인" if r["one_hour_bullish"] else ("하락 확인" if r["one_hour_bearish"] else "중립"),
            "추천": r["decision"],
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    for r in results:
        with st.expander(f"{coin_label(r['coin'])} · {r['decision']} · {r['total_score']}점", expanded=True):
            a, b, c, d = st.columns(4)
            a.metric("현재가", upbit_swing.krw(r["price"]))
            b.metric("기준 진입가", upbit_swing.krw(r["entry_price"]))
            c.metric("손절", upbit_swing.krw(r["stop"]), f"{r['risk_pct']:+.1f}%")
            d.metric("1H 거래량", f"{r['volume_ratio']:.2f}배")

            st.write(f"**진입 관심구간:** {upbit_swing.krw(r['entry_low'])} ~ {upbit_swing.krw(r['entry_high'])}")
            st.write(f"**목표:** 1차 {upbit_swing.krw(r['target1'])} / 2차 {upbit_swing.krw(r['target2'])}")
            st.write(f"**R:R:** 1차 {r['rr1']:.2f} / 2차 {r['rr2']:.2f}")
            st.markdown("### 일봉 필터")
            st.write(f"**일봉 추세:** {'상승' if r['daily_bullish'] else '하락/중립'}")
            st.write(f"**거래량 동반 전고점 돌파:** {'확인' if r['daily_breakout'] else '없음'}")
            st.write(f"**돌파 후 지지 확인:** {'확인' if r['daily_support_confirmed'] else '대기'}")
            st.write(f"**급등 후 고점 추격 위험:** {'추천 제외' if r['daily_overextended'] else '없음'}")
            st.write(f"**일봉 거래량:** {r['daily_volume_ratio']:.2f}배")
            st.write(f"**전고점 기준:** {upbit_swing.krw(r['daily_prior_high'])}")

            st.markdown("### 1H 추세 확인")
            if r["one_hour_bullish"]:
                st.success("상승 추세 확인 — 매수 조건을 검토할 수 있습니다.")
            elif r["one_hour_bearish"]:
                st.error("하락 추세 확인 — 보유 중이면 매도/비중축소를 검토합니다.")
            else:
                st.warning("1H 상승 추세가 아직 확인되지 않았습니다. 신규 매수는 기다립니다.")

            st.markdown("### 4H / 1H / 일봉 지표")
            ind = pd.DataFrame([
                {"항목":"RSI", "4H":r["rsi4"], "1H":r["rsi1"]},
                {"항목":"MA20", "4H":r["ma20_4"], "1H":r["ma20_1"]},
                {"항목":"MA60", "4H":r["ma60_4"], "1H":r["ma60_1"]},
                {"항목":"MACD", "4H":r["macd4"], "1H":r["macd1"]},
                {"항목":"MACD Signal", "4H":r["macd4_signal"], "1H":r["macd1_signal"]},
                {"항목":"일봉 MA20", "4H":"", "1H":r["daily_ma20"]},
                {"항목":"일봉 MA60", "4H":"", "1H":r["daily_ma60"]},
                {"항목":"일봉 RSI", "4H":"", "1H":r["daily_rsi"]},
            ])
            st.dataframe(ind, use_container_width=True, hide_index=True)

st.info("주의: 이 도구는 자동매매가 아니라 기술적 분석 보조 도구입니다. 매수/매도 추천은 규칙 기반 신호입니다.")
