import streamlit as st
import pandas as pd
from datetime import datetime
import upbit_swing
import pyupbit

st.set_page_config(page_title="업비트 스윙 분석기", page_icon="📈", layout="wide")
st.title("📈 업비트 5~7일 스윙 분석기")
st.caption("KRW 시장 · 24시간 거래대금 50억원 이상 · 사이트 접속 시 최신 데이터 갱신")

# 거래대금 기준: 50억원
MIN_TRADE_VALUE = 5_000_000_000

# -----------------------------
# 코인명: 한글명 (영어 티커)
# -----------------------------
COIN_NAMES = {
    "BTC":"비트코인", "ETH":"이더리움", "XRP":"리플", "DOGE":"도지코인",
    "SOL":"솔라나", "ADA":"에이다", "AVAX":"아발란체", "LINK":"체인링크",
    "DOT":"폴카닷", "TRX":"트론", "WLD":"월드코인", "DOOD":"두들즈",
    "PENDLE":"펜들", "KNC":"카이버네트워크", "SUI":"수이", "APT":"앱토스",
    "ARB":"아비트럼", "OP":"옵티미즘", "NEAR":"니어프로토콜", "ATOM":"코스모스",
    "ETC":"이더리움 클래식", "BCH":"비트코인캐시", "LTC":"라이트코인",
    "EOS":"이오스", "IMX":"이뮤터블엑스", "INJ":"인젝티브", "PEPE":"페페",
    "BONK":"봉크", "WIF":"도그위프햇", "SHIB":"시바이누", "HBAR":"헤데라",
    "ONDO":"온도파이낸스", "RENDER":"렌더토큰", "ZRX":"제로엑스", "GLM":"골렘",
    "HUNT":"헌트", "THETA":"쎄타토큰", "MLK":"밀크", "WAXP":"왁스",
    "ZORA":"조라", "GAS":"가스"
}

try:
    for item in (pyupbit.get_market_all(fiat="KRW") or []):
        market = str(item.get("market", ""))
        name = str(item.get("korean_name", "")).strip()
        if market.startswith("KRW-") and name:
            COIN_NAMES[market.replace("KRW-", "")] = name
except Exception:
    pass

def coin_label(code):
    code = str(code).replace("KRW-", "").strip()
    if "(" in code:
        code = code.split("(")[-1].split(")")[0].strip()
    return f"{COIN_NAMES.get(code, code)} ({code})"

# -----------------------------
# 50억원 이상 KRW 마켓
# -----------------------------
with st.spinner("업비트 KRW 마켓과 거래대금을 확인하는 중입니다..."):
    AVAILABLE_COINS = upbit_swing.get_liquid_krw_coins(MIN_TRADE_VALUE)

if not AVAILABLE_COINS:
    st.error("거래대금 정보를 불러오지 못했습니다. 잠시 후 새로고침해 주세요.")
    st.stop()

upbit_swing.COINS = AVAILABLE_COINS
st.caption(f"분석 대상: 24시간 거래대금 {MIN_TRADE_VALUE:,}원 이상 · {len(AVAILABLE_COINS)}개")

# 메인 화면에 분석 코인 목록/선택창을 노출하지 않음

# -----------------------------
# 15분봉 보조지표
# -----------------------------
def safe_float(v, default=0.0):
    try:
        if v is None or pd.isna(v):
            return default
        return float(v)
    except Exception:
        return default

def add_15m_indicators(result):
    code = str(result.get("coin", "")).replace("KRW-", "").strip()
    market = f"KRW-{code}"
    try:
        df = pyupbit.get_ohlcv(market, interval="minute15", count=120)
        if df is None or len(df) < 40:
            return result
        close = df["close"]
        volume = df["volume"]
        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        macd = ema12 - ema26
        signal = macd.ewm(span=9, adjust=False).mean()
        delta = close.diff()
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = (-delta.clip(upper=0)).rolling(14).mean()
        rs = gain / loss.replace(0, pd.NA)
        rsi = (100 - (100 / (1 + rs))).fillna(50)
        ma20 = close.rolling(20).mean()
        std20 = close.rolling(20).std()
        upper = ma20 + 2 * std20
        lower = ma20 - 2 * std20
        last = -1
        result["rsi15"] = safe_float(rsi.iloc[last], 50)
        result["macd15"] = safe_float(macd.iloc[last])
        result["macd15_signal"] = safe_float(signal.iloc[last])
        result["bb15_position"] = safe_float((close.iloc[last] - lower.iloc[last]) / (upper.iloc[last] - lower.iloc[last]), 0.5)
        result["volume15_ratio"] = safe_float(volume.iloc[last] / volume.iloc[-21:-1].mean(), 1.0)
        result["trend15"] = "상승" if close.iloc[last] > ma20.iloc[last] and macd.iloc[last] > signal.iloc[last] else ("하락" if close.iloc[last] < ma20.iloc[last] and macd.iloc[last] < signal.iloc[last] else "중립")
    except Exception:
        result.update({"rsi15": 50.0, "macd15": 0.0, "macd15_signal": 0.0, "bb15_position": 0.5, "volume15_ratio": 1.0, "trend15": "확인불가"})
    return result

# -----------------------------
# 내부 순위: 점수는 화면에 표시하지 않음
# 기존 분석 점수 + 15분봉 보정으로 순위 결정
# -----------------------------
def internal_rank_key(r):
    base = safe_float(r.get("total_score", 0))
    bonus = 0
    if r.get("trend15") == "상승": bonus += 3
    if safe_float(r.get("macd15")) > safe_float(r.get("macd15_signal")): bonus += 2
    if 45 <= safe_float(r.get("rsi15"), 50) <= 68: bonus += 2
    if 0.15 <= safe_float(r.get("bb15_position"), 0.5) <= 0.75: bonus += 1
    if safe_float(r.get("volume15_ratio"), 1) >= 1.2: bonus += 2
    if safe_float(r.get("rr1", 0)) >= 1.5: bonus += 2
    return base + bonus

def get_results(selected):
    results = []
    for coin in selected:
        try:
            r = upbit_swing.analyze_coin(coin)
            if r:
                r = add_15m_indicators(r)
                results.append(r)
        except Exception as e:
            st.warning(f"{coin_label(coin)} 분석 오류: {e}")
    return sorted(results, key=internal_rank_key, reverse=True)

with st.spinner("일봉 · 1시간봉 · 15분봉과 거래량/MACD/매물대/RSI/볼린저밴드/R:R를 분석하는 중입니다..."):
    results = get_results(tuple(AVAILABLE_COINS))

st.caption("분석시간: " + datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

if not results:
    st.error("데이터를 가져오지 못했습니다.")
    st.stop()

st.subheader("① 5~7일 스윙 상위 후보")
for r in results[:6]:
    st.write(f"**{coin_label(r.get('coin'))}** · {r.get('decision', '관망')} · 현재가 {upbit_swing.krw(r.get('price', 0))}")

st.divider()
st.subheader("② 신규 스윙 후보")
st.caption("순위는 거래량, MACD, 매물대/지지, RSI, 볼린저밴드, R:R와 일봉·1시간봉·15분봉 흐름을 종합해 산정합니다. 점수는 표시하지 않습니다.")

rows = []
for i, r in enumerate(results, 1):
    rows.append({
        "순위": i,
        "코인": coin_label(r.get("coin")),
        "추천": r.get("decision", "관망"),
        "일봉": "상승" if r.get("daily_bullish", False) else "하락/중립",
        "1시간봉": "상승" if r.get("one_hour_bullish", False) else ("하락" if r.get("one_hour_bearish", False) else "중립"),
        "15분봉": r.get("trend15", "확인불가"),
        "거래량": f"{safe_float(r.get('volume15_ratio', 1)):.2f}배",
        "MACD": "상승" if safe_float(r.get("macd15")) > safe_float(r.get("macd15_signal")) else "하락/중립",
        "RSI": f"{safe_float(r.get('rsi15'), 50):.1f}",
        "볼린저밴드": f"{safe_float(r.get('bb15_position'), .5) * 100:.0f}%",
        "매물대/지지": "확인" if r.get("daily_support_confirmed", False) else "대기",
        "R:R": f"{safe_float(r.get('rr1')):.2f}",
        "현재가": r.get("price", 0),
        "진입구간": f"{safe_float(r.get('entry_low')):.4g} ~ {safe_float(r.get('entry_high')):.4g}",
        "손절": r.get("stop", 0),
        "1차 목표": r.get("target1", 0),
        "2차 목표": r.get("target2", 0),
    })

st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

st.divider()
st.subheader("③ 코인별 상세 분석")
for r in results:
    with st.expander(f"{coin_label(r.get('coin'))} · {r.get('decision', '관망')}", expanded=False):
        a, b, c, d = st.columns(4)
        a.metric("현재가", upbit_swing.krw(r.get("price", 0)))
        b.metric("기준 진입가", upbit_swing.krw(r.get("entry_price", 0)))
        c.metric("손절", upbit_swing.krw(r.get("stop", 0)))
        d.metric("1차 R:R", f"{safe_float(r.get('rr1')):.2f}")
        st.write(f"**일봉:** {'상승' if r.get('daily_bullish', False) else '하락/중립'}")
        st.write(f"**1시간봉:** {'상승' if r.get('one_hour_bullish', False) else ('하락' if r.get('one_hour_bearish', False) else '중립')}")
        st.write(f"**15분봉:** {r.get('trend15', '확인불가')}")
        st.write(f"**15분봉 RSI:** {safe_float(r.get('rsi15'), 50):.1f}")
        st.write(f"**15분봉 MACD:** {safe_float(r.get('macd15')):.6g} / Signal {safe_float(r.get('macd15_signal')):.6g}")
        st.write(f"**15분봉 거래량:** {safe_float(r.get('volume15_ratio'), 1):.2f}배")
        st.write(f"**볼린저밴드 위치:** {safe_float(r.get('bb15_position'), .5) * 100:.0f}%")
        st.write(f"**전고점 돌파:** {'확인' if r.get('daily_breakout', False) else '없음'}")
        st.write(f"**돌파 후 지지:** {'확인' if r.get('daily_support_confirmed', False) else '대기'}")
        st.write(f"**진입 관심구간:** {upbit_swing.krw(r.get('entry_low', 0))} ~ {upbit_swing.krw(r.get('entry_high', 0))}")
        st.write(f"**목표:** 1차 {upbit_swing.krw(r.get('target1', 0))} / 2차 {upbit_swing.krw(r.get('target2', 0))}")

st.info("주의: 본 화면은 자동매매가 아닌 기술적 분석 보조 도구입니다. 급등 코인도 지표가 양호하면 후보에 포함될 수 있지만, 손절 기준을 반드시 확인하세요.")
