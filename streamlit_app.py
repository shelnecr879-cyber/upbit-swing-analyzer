import streamlit as st
import pandas as pd
from datetime import datetime
import upbit_swing
import pyupbit
import requests

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
with st.spinner("업비트 KRW 마켓과 거래대금을 확인하는 중입니다..."):
    AVAILABLE_COINS = upbit_swing.get_liquid_krw_coins(MIN_TRADE_VALUE)

if not AVAILABLE_COINS:
    st.error("거래대금 정보를 불러오지 못했습니다. 잠시 후 새로고침해 주세요.")
    st.stop()

if "DOOD" not in AVAILABLE_COINS:
    AVAILABLE_COINS = list(AVAILABLE_COINS) + ["DOOD"]
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
# 보유 코인: 두들즈(DOOD)
# -----------------------------
HOLDING_COIN = "DOOD"
HOLDING_ENTRY = 2.57
HOLDING_QTY = 3_000_000

def holding_report(result):
    price = safe_float(result.get("price", 0))
    invested = HOLDING_ENTRY * HOLDING_QTY
    value = price * HOLDING_QTY
    pnl = value - invested
    pnl_pct = (price / HOLDING_ENTRY - 1) * 100 if HOLDING_ENTRY else 0
    stop = safe_float(result.get("stop", 0))
    target1 = safe_float(result.get("target1", 0))
    target2 = safe_float(result.get("target2", 0))
    support = safe_float(result.get("daily_prior_high", 0))
    return {
        "현재가": price, "매수금액": invested, "평가금액": value,
        "손익": pnl, "수익률": pnl_pct, "손절": stop,
        "1차목표": target1, "2차목표": target2, "지지참고": support
    }

# -----------------------------
# 10점 만점 종합 점수
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
    # 점수가 높은 순서. 점수는 화면에 표시함.
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

# 보유 중인 두들즈는 거래대금 필터와 관계없이 별도 진단
dood_result = next((x for x in results if str(x.get("coin", "")).replace("KRW-", "") == "DOOD"), None)
if dood_result is None:
    try:
        dood_result = upbit_swing.analyze_coin("DOOD")
        if dood_result:
            dood_result = add_15m_indicators(dood_result)
    except Exception as e:
        dood_result = None
        st.warning(f"두들즈 보유 진단 오류: {e}")

if dood_result:
    st.divider()
    st.subheader("🔎 현재 보유 코인 진단 · 두들즈 (DOOD)")
    st.caption("입력된 보유정보: 매수가 2.57원 · 수량 3,000,000개 · 매수금액 7,710,000원")
    h = holding_report(dood_result)
    a, b, c, d = st.columns(4)
    a.metric("현재 평가금액", upbit_swing.krw(h["평가금액"]))
    b.metric("평가 손익", upbit_swing.krw(h["손익"]), f"{h['수익률']:+.2f}%")
    c.metric("현재가", upbit_swing.krw(h["현재가"]))
    d.metric("종합점수", f"{analysis_score(dood_result):.1f} / 10점")
    st.write(f"**매수가:** {HOLDING_ENTRY:.2f}원 · **수량:** {HOLDING_QTY:,}개 · **매수금액:** {upbit_swing.krw(h['매수금액'])}")
    st.write(f"**손절 기준:** {upbit_swing.krw(h['손절'])} · **1차 목표:** {upbit_swing.krw(h['1차목표'])} · **2차 목표:** {upbit_swing.krw(h['2차목표'])}")
    st.write(f"**일봉:** {'상승' if dood_result.get('daily_bullish', False) else '하락/중립'} · **1시간봉:** {'상승' if dood_result.get('one_hour_bullish', False) else ('하락' if dood_result.get('one_hour_bearish', False) else '중립')} · **15분봉:** {dood_result.get('trend15', '확인불가')}")
    st.write(f"**RSI(15분):** {safe_float(dood_result.get('rsi15'), 50):.1f} · **거래량:** {safe_float(dood_result.get('volume15_ratio'), 1):.2f}배 · **R:R:** {safe_float(dood_result.get('rr1')):.2f}")
    if h["현재가"] <= h["손절"] and h["손절"] > 0:
        st.error("⚠️ 현재가가 분석 손절선 이하입니다. 매도/비중축소를 즉시 검토하세요.")
    elif h["수익률"] < -10:
        st.warning("⚠️ 보유 손실률이 -10%보다 큽니다. 반등 기대만으로 추가매수하지 말고 일봉 지지 이탈 여부를 확인하세요.")
    elif h["현재가"] >= h["1차목표"] and h["1차목표"] > 0:
        st.success("1차 목표 도달 구간입니다. 일부 익절을 검토할 수 있습니다.")
    else:
        st.info("현재 보유 진단은 실시간 가격과 일봉·1시간봉·15분봉 지표를 기준으로 갱신됩니다. '정확한 예측'이 아니라 조건 기반 위험 진단입니다.")

if not results:
    st.error("데이터를 가져오지 못했습니다.")
    st.stop()

st.subheader("① 5~7일 매수추천 우선 순위")
for r in results[:6]:
    st.write(f"**{coin_label(r.get('coin'))}** · **{analysis_score(r):.1f}점 / 10점** · 현재가 {upbit_swing.krw(r.get('price', 0))}")

st.divider()
st.subheader("② 신규 스윙 후보")
st.caption("10점 만점 종합점수(소수점 1자리)로 정렬합니다. 거래량·MACD·매물대/지지·RSI·볼린저밴드·R:R와 일봉·1시간봉·15분봉을 종합합니다.")

rows = []
for i, r in enumerate(results, 1):
    rows.append({
        "순위": i,
        "코인": coin_label(r.get("coin")),
        "점수(10점)": f"{analysis_score(r):.1f}",
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
    with st.expander(f"{coin_label(r.get('coin'))} · {analysis_score(r):.1f}점 / 10점", expanded=False):
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
