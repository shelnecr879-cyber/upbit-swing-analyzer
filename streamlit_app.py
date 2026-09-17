import streamlit as st
import pandas as pd
from datetime import datetime
import upbit_swing
import pyupbit
import requests

st.set_page_config(page_title="업비트 스윙 분석기", page_icon="📈", layout="wide")
st.title("📈 업비트 5~14일 스윙 분석기")
st.caption("KRW 시장 · 24시간 거래대금 50억원 이상 · 사이트 접속 시 최신 데이터 갱신")

# 거래대금 기준: 50억원
MIN_TRADE_VALUE = 5_000_000_000

# -----------------------------
# 코인명: 한글명 (영어 티커)
# -----------------------------
COIN_NAMES = {
    "BTC":"비트코인", "ETH":"이더리움", "XRP":"리플", "DOGE":"도지코인",
    "SOL":"솔라나", "ADA":"에이다", "AVAX":"아발란체", "LINK":"체인링크",
    "DOT":"폴카닷", "TRX":"트론", "WLD":"월드코인",
    "PENDLE":"펜들", "KNC":"카이버네트워크", "SUI":"수이", "APT":"앱토스",
    "ARB":"아비트럼", "OP":"옵티미즘", "NEAR":"니어프로토콜", "ATOM":"코스모스",
    "ETC":"이더리움 클래식", "BCH":"비트코인캐시", "LTC":"라이트코인",
    "EOS":"이오스", "IMX":"이뮤터블엑스", "INJ":"인젝티브", "PEPE":"페페",
    "BONK":"봉크", "WIF":"도그위프햇", "SHIB":"시바이누", "HBAR":"헤데라",
    "ONDO":"온도파이낸스", "RENDER":"렌더토큰", "ZRX":"제로엑스", "GLM":"골렘",
    "HUNT":"헌트", "THETA":"쎄타토큰", "MLK":"밀크", "WAXP":"왁스",
    "ZORA":"조라", "GAS":"가스",
    "ARK":"아크", "CVC":"시빅", "WLFI":"월드 리버티 파이낸셜",
    "POWR":"파워렛저", "PLUME":"플룸", "IOST":"아이오에스티",
    "MTL":"메탈", "CHZ":"칠리즈", "ETHFI":"이더파이",
    "XPL":"플라즈마", "BERA":"베라체인", "POLYX":"폴리매쉬",
    "SC":"시아코인", "HIVE":"하이브", "STEEM":"스팀",
    "FLOCK":"플록", "USDT":"테더", "BLAST":"블라스트",
    "LSK":"리스크", "PUNDIX":"펀디엑스", "TREE":"트리",
    "XLM":"스텔라루멘", "SOPH":"소폰", "MET2":"메테오라",
    "VTHO":"비토르토큰", "RAY":"레이디움", "TRUMP":"오피셜트럼프",
    "B3":"비쓰리", "WAVES":"웨이브", "STORJ":"스토리지",
    "UP2":"업투", "NEO":"네오", "QTUM":"퀀텀", "AAVE":"에이브",
    "ALGO":"알고랜드", "SAND":"샌드박스", "MANA":"디센트럴랜드"
}

try:
    # pyupbit 실패 시에도 직접 Upbit 공개 API로 한글명을 보완
    response = requests.get(
        "https://api.upbit.com/v1/market/all",
        params={"isDetails": "false"},
        timeout=10,
    )
    response.raise_for_status()
    for item in response.json():
        market = str(item.get("market", ""))
        name = str(item.get("korean_name", "")).strip()
        if market.startswith("KRW-") and name:
            COIN_NAMES[market.replace("KRW-", "")] = name
except Exception:
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
def load_available_coins():
    """거래대금 필터가 실패해도 분석 화면이 빈 상태가 되지 않도록 안전하게 로드."""
    try:
        loader = getattr(upbit_swing, "get_liquid_krw_coins", None)
        if callable(loader):
            coins = loader(MIN_TRADE_VALUE) or []
            if coins:
                return list(dict.fromkeys(str(c) for c in coins))
    except Exception:
        pass

    # 보조 경로: pyupbit 공개 API로 KRW 마켓 티커를 가져옴
    try:
        tickers = pyupbit.get_tickers(fiat="KRW") or []
        if tickers:
            return list(dict.fromkeys(str(c) for c in tickers))
    except Exception:
        pass

    # 최종 보조 경로: 화면이 'No options'가 되지 않도록 기본 주요 코인 사용
    return [f"KRW-{code}" for code in list(COIN_NAMES.keys())[:30]]

with st.spinner("업비트 KRW 마켓과 거래대금을 확인하는 중입니다..."):
    AVAILABLE_COINS = load_available_coins()

upbit_swing.COINS = AVAILABLE_COINS
st.caption(f"분석 대상: {len(AVAILABLE_COINS)}개 · 거래대금 필터 우선 적용")

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



def pct(v):
    return f"{safe_float(v):.1f}%"

def price(v):
    return upbit_swing.krw(safe_float(v))

def trend_text(r):
    if r.get("daily_bullish", False):
        return "상승"
    if r.get("daily_bearish", False):
        return "하락"
    return "중립"

def make_review_comment(r):
    """상위 후보별 사람이 읽기 쉬운 검토 코멘트 생성."""
    p = safe_float(r.get("price"))
    support = safe_float(r.get("support"))
    resistance = safe_float(r.get("resistance"))
    entry_low = safe_float(r.get("entry_low"))
    entry_high = safe_float(r.get("entry_high"))
    stop = safe_float(r.get("stop"))
    target1 = safe_float(r.get("target1"))
    target2 = safe_float(r.get("target2"))
    decision = r.get("decision", "관망")
    daily = trend_text(r)
    one_hour = "상승" if r.get("one_hour_bullish", False) else ("하락" if r.get("one_hour_bearish", False) else "중립")
    trend15 = r.get("trend15", "확인불가")
    reasons = []
    risks = []

    if r.get("daily_breakout", False):
        if r.get("daily_support_confirmed", False):
            reasons.append("전고점 돌파 후 지지 확인")
        else:
            risks.append("전고점 돌파 후 지지 확인이 아직 부족")
    if r.get("daily_overextended", False):
        risks.append("최근 급등·고점 추격 위험")
    if r.get("one_hour_bullish", False):
        reasons.append("1시간봉 상승 구조")
    elif r.get("one_hour_bearish", False):
        risks.append("1시간봉 하락 구조")
    if trend15 == "상승":
        reasons.append("15분봉 단기 반등")
    elif trend15 == "하락":
        risks.append("15분봉 단기 약세")
    if safe_float(r.get("volume15_ratio"), 1) >= 1.2:
        reasons.append(f"단기 거래량 {safe_float(r.get('volume15_ratio')):.2f}배")
    if p > 0 and support > 0:
        dist = (p-support)/support*100
        if dist <= 3:
            reasons.append(f"지지선과 거리 약 {dist:.1f}%")
        elif dist >= 8:
            risks.append(f"지지선과 거리 약 {dist:.1f}%")
    if resistance > 0 and p > 0:
        rd = (resistance-p)/p*100
        if rd <= 3:
            risks.append(f"저항선까지 약 {rd:.1f}%로 여유가 적음")

    reason_text = " · ".join(reasons) if reasons else "뚜렷한 상승 확인 신호가 제한적"
    risk_text = " · ".join(risks) if risks else "특별히 확인되는 단기 위험 신호는 제한적"
    if decision == "매수추천":
        action = "조건 충족 시 분할 진입을 검토할 수 있으나, 손절선을 반드시 지켜야 합니다."
    elif decision == "매수검토":
        action = "현재가 즉시 추격매수보다 지지 확인 후 분할 진입을 검토하는 구간입니다."
    elif decision == "매도추천":
        action = "하락 구조가 확인되는 상태이므로 신규매수보다 리스크 관리가 우선입니다."
    elif decision == "매도검토":
        action = "지지선 이탈 여부를 우선 확인하고 보유 중이라면 비중 조절을 검토합니다."
    else:
        action = "현재는 확인 매매가 필요하며, 주요 지지선 또는 저항선 돌파 전 추격매수는 주의합니다."

    return f"""**판단: {decision}**

**차트 특징**
- 일봉 추세: {daily}
- 1시간봉: {one_hour}
- 15분봉: {trend15}
- 주요 확인사항: {reason_text}

**중요 가격**
- 지지선: {price(support)}
- 저항선: {price(resistance)}
- 진입 관심구간: {price(entry_low)} ~ {price(entry_high)}
- 손절선: {price(stop)}
- 1차 목표: {price(target1)} / 2차 목표: {price(target2)}

**검토 코멘트**
- {action}
- 주의사항: {risk_text}
- 손익비(R:R): {safe_float(r.get('rr1')):.2f}
"""


# -----------------------------
# 내부 분석 점수 (화면에는 표시하지 않음)
# -----------------------------
def analysis_score(r):
    """일봉·1시간봉·15분봉과 주요 지표를 종합한 10점 만점 점수."""
    score = 5.0

    # 추세: 일봉 2.0점, 1시간봉 1.5점, 15분봉 1.0점
    score += 1.0 if r.get("daily_bullish", False) else -1.0 if r.get("daily_bearish", False) else 0.0
    score += 0.75 if r.get("one_hour_bullish", False) else -0.75 if r.get("one_hour_bearish", False) else 0.0
    score += 0.5 if r.get("trend15") == "상승" else -0.5 if r.get("trend15") == "하락" else 0.0

    # MACD
    score += 0.5 if safe_float(r.get("macd15")) > safe_float(r.get("macd15_signal")) else -0.5
    # RSI: 45~68을 매수에 우호적으로 평가
    rsi = safe_float(r.get("rsi15"), 50)
    score += 0.5 if 45 <= rsi <= 68 else -0.5 if rsi < 35 or rsi > 75 else 0.0
    # 볼린저밴드: 중단~하단 반등 구간 선호, 상단 과열 감점
    bb = safe_float(r.get("bb15_position"), 0.5)
    score += 0.5 if 0.15 <= bb <= 0.75 else -0.5 if bb > 0.9 else 0.0
    # 거래량
    vol = safe_float(r.get("volume15_ratio"), 1.0)
    score += 0.5 if 1.2 <= vol <= 4.0 else -0.25 if vol < 0.5 else 0.0
    # 매물대/지지 및 돌파
    if r.get("daily_support_confirmed", False): score += 0.5
    if r.get("daily_breakout", False): score += 0.25
    # R:R
    rr = safe_float(r.get("rr1"), 0.0)
    score += 0.5 if rr >= 2.0 else 0.25 if rr >= 1.5 else -0.5 if rr < 1.0 else 0.0
    # 급등/고점 위험은 완전 제외하지 않고 감점만 적용
    if r.get("daily_overextended", False): score -= 0.5

    return round(max(0.0, min(10.0, score)), 1)

# -----------------------------
# 내부 순위: 점수는 화면에 표시하지 않음
# 기존 분석 점수 + 15분봉 보정으로 순위 결정
# -----------------------------
def internal_rank_key(r):
    # 내부 정렬용 점수이며 화면에는 표시하지 않음.
    return -analysis_score(r)

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
    return sorted(results, key=internal_rank_key)

with st.spinner("일봉 · 1시간봉 · 15분봉과 거래량/MACD/매물대/RSI/볼린저밴드/R:R를 분석하는 중입니다..."):
    results = get_results(tuple(AVAILABLE_COINS))

st.caption("분석시간: " + datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

if not results:
    st.error("데이터를 가져오지 못했습니다.")
    st.stop()

st.subheader("① 상위 5개 스윙 후보")
st.caption("내부 정렬 결과 상위 5개만 상세 결과와 검토 코멘트를 표시합니다.")
for i, r in enumerate(results[:5], 1):
    with st.expander(f"{i}위 · {coin_label(r.get('coin'))} · {r.get('decision', '관망')}", expanded=(i == 1)):
        st.markdown(make_review_comment(r))

st.divider()
st.subheader("② 신규 스윙 후보")
st.caption("4H·1H·15m·일봉·거래량·MACD·매물대/지지·RSI·볼린저밴드·R:R를 종합해 행동 기준을 표시합니다.")

rows = []
for i, r in enumerate(results[:5], 1):
    rows.append({
        "순위": i,
        "코인": coin_label(r.get("coin")),
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
st.subheader("③ 상위 5개 코인별 상세 분석")
for r in results[:5]:
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
