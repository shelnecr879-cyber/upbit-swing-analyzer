import pyupbit
import pandas as pd
import numpy as np
import time
import requests
from datetime import datetime

# ============================================================
# 업비트 스윙 분석기 - 최종 버전
#
# 전략:
#   4시간봉 : 큰 추세 확인
#   1시간봉 : 진입 타이밍 확인
#   MACD + RSI + 거래량 + 매물대
#   눌림매수 우선
#   추격매수 방지
#
# 대상: 업비트 KRW 전체 마켓 중 24시간 거래대금 기준 통과 코인
# 목표: 3~10일 보유 / 주 1~2회 정도의 선별 매매
#
# 주의:
#   이 프로그램은 자동매매가 아니라 기술적 분석 보조 도구입니다.
# ============================================================

# 업비트 KRW 전체 마켓 중 24시간 거래대금 기준으로 유동성 낮은 코인 제외
MIN_24H_TRADE_VALUE = 1_000_000_000  # 10억원
COINS = []

def get_liquid_krw_coins(min_trade_value=MIN_24H_TRADE_VALUE):
    """업비트 KRW 전체 마켓에서 24시간 거래대금 기준으로 코인을 선별."""
    try:
        markets = pyupbit.get_tickers(fiat="KRW")
        if not markets:
            return []
        result = []
        for i in range(0, len(markets), 100):
            batch = markets[i:i+100]
            response = requests.get(
                "https://api.upbit.com/v1/ticker",
                params={"markets": ",".join(batch)},
                timeout=15,
            )
            response.raise_for_status()
            for item in response.json():
                value = float(item.get("acc_trade_price_24h") or 0)
                if value >= min_trade_value:
                    result.append(item["market"].replace("KRW-", ""))
            time.sleep(0.12)
        return result
    except Exception as e:
        print(f"거래대금 기준 코인 목록 조회 실패: {e}")
        return []


CANDLE_4H = 200
CANDLE_1H = 300
CANDLE_DAILY = 220

# 추격매수 방지 기준
CHASE_WARN = 0.06
CHASE_BLOCK = 0.10

# 기본 손절/목표
DEFAULT_STOP = 0.06
TARGET1 = 0.08
TARGET2 = 0.15


# ============================================================
# 공통 함수
# ============================================================

def calculate_rsi(series, period=14):
    delta = series.diff()

    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(
        alpha=1 / period,
        min_periods=period,
        adjust=False
    ).mean()

    avg_loss = loss.ewm(
        alpha=1 / period,
        min_periods=period,
        adjust=False
    ).mean()

    rs = avg_gain / avg_loss

    return 100 - (100 / (1 + rs))


def calculate_macd(close):
    ema12 = close.ewm(
        span=12,
        adjust=False
    ).mean()

    ema26 = close.ewm(
        span=26,
        adjust=False
    ).mean()

    macd = ema12 - ema26

    signal = macd.ewm(
        span=9,
        adjust=False
    ).mean()

    histogram = macd - signal

    return macd, signal, histogram


def calculate_volume_profile(df, bins=20):
    """
    종가 구간별 거래량을 합산해서
    가장 거래가 많이 몰린 가격대를 찾는 간단한 매물대 계산.
    """

    prices = df["close"]

    if len(prices) < 20:
        return float(prices.min()), float(prices.max())

    low = float(prices.min())
    high = float(prices.max())

    if low == high:
        return low, high

    price_bins = pd.cut(prices, bins=bins)

    profile = (
        df.groupby(price_bins, observed=True)["volume"]
        .sum()
    )

    if profile.empty:
        return low, high

    strongest_zone = profile.idxmax()

    return float(strongest_zone.left), float(strongest_zone.right)


def krw(value):
    """가격을 보기 편한 원화 형식으로 표시."""

    value = float(value)

    if value >= 1000:
        return f"{value:,.0f}원"

    if value >= 1:
        return f"{value:,.2f}원"

    if value >= 0.01:
        return f"{value:,.4f}원"

    return f"{value:,.6f}원"


def pct(value):
    return f"{value:+.1f}%"


# ============================================================
# 시간봉 지표 계산
# ============================================================

def prepare_indicators(df):
    df = df.copy()

    close = df["close"]
    volume = df["volume"]

    df["ma20"] = close.rolling(20).mean()
    df["ma60"] = close.rolling(60).mean()
    df["ma120"] = close.rolling(120).mean()

    df["rsi"] = calculate_rsi(close)

    macd, signal, histogram = calculate_macd(close)

    df["macd"] = macd
    df["macd_signal"] = signal
    df["macd_hist"] = histogram

    df["volume_ma20"] = volume.rolling(20).mean()
    df["volume_ratio"] = volume / df["volume_ma20"]

    return df


# ============================================================
# 4시간봉 추세 분석
# ============================================================

def analyze_4h(df):
    df = prepare_indicators(df)

    last = df.iloc[-1]
    prev = df.iloc[-2]

    price = float(last["close"])

    ma20 = float(last["ma20"])
    ma60 = float(last["ma60"])
    ma120 = float(last["ma120"])

    rsi = float(last["rsi"])

    macd = float(last["macd"])
    macd_signal = float(last["macd_signal"])
    hist = float(last["macd_hist"])
    prev_hist = float(prev["macd_hist"])

    score = 0
    reasons = []

    # 4시간봉 큰 추세
    if price > ma60:
        score += 2
        reasons.append("4H 가격이 60선 위")

    if ma20 > ma60:
        score += 2
        reasons.append("4H 20>60 정배열")

    if ma60 > ma120:
        score += 1
        reasons.append("4H 60>120 상승 구조")

    # 4H MACD
    if macd > macd_signal:
        score += 1
        reasons.append("4H MACD 상승")

    if hist > prev_hist:
        score += 1
        reasons.append("4H MACD 모멘텀 개선")

    # 4H RSI
    if 45 <= rsi <= 68:
        score += 1
        reasons.append("4H RSI 양호")

    elif rsi > 75:
        score -= 2
        reasons.append("4H RSI 과열")

    elif rsi < 40:
        score -= 1
        reasons.append("4H RSI 약세")

    return {
        "score": score,
        "price": price,
        "ma20": ma20,
        "ma60": ma60,
        "ma120": ma120,
        "rsi": rsi,
        "macd": macd,
        "macd_signal": macd_signal,
        "hist": hist,
        "reasons": reasons
    }


# ============================================================
# 1시간봉 진입 분석
# ============================================================

def analyze_1h(df):
    df = prepare_indicators(df)

    last = df.iloc[-1]
    prev = df.iloc[-2]

    price = float(last["close"])

    ma20 = float(last["ma20"])
    ma60 = float(last["ma60"])

    rsi = float(last["rsi"])

    macd = float(last["macd"])
    macd_signal = float(last["macd_signal"])
    hist = float(last["macd_hist"])
    prev_hist = float(prev["macd_hist"])

    volume_ratio = float(last["volume_ratio"])

    recent_high = float(df["high"].tail(50).max())
    recent_low = float(df["low"].tail(50).min())

    zone_low, zone_high = calculate_volume_profile(
        df.tail(150)
    )

    zone_mid = (zone_low + zone_high) / 2

    score = 0
    reasons = []

    # --------------------------------------------------------
    # 1H 추세
    # --------------------------------------------------------

    if price > ma20:
        score += 1
        reasons.append("1H 20선 위")

    if ma20 > ma60:
        score += 1
        reasons.append("1H 20>60")

    # --------------------------------------------------------
    # MACD
    # --------------------------------------------------------

    if macd > macd_signal:
        score += 1
        reasons.append("1H MACD 상승")

    # MACD 히스토그램이 전봉보다 좋아지는지
    if hist > prev_hist:
        score += 1
        reasons.append("1H MACD 모멘텀 개선")

    # --------------------------------------------------------
    # RSI
    # --------------------------------------------------------

    if 45 <= rsi <= 65:
        score += 2
        reasons.append("1H RSI 눌림/상승 구간")

    elif 65 < rsi <= 70:
        score += 1
        reasons.append("1H RSI 강세")

    elif rsi > 75:
        score -= 2
        reasons.append("1H RSI 과열")

    elif rsi < 40:
        score -= 1
        reasons.append("1H RSI 약세")

    # --------------------------------------------------------
    # 거래량
    # --------------------------------------------------------

    if 1.2 <= volume_ratio <= 3.5:
        score += 2
        reasons.append("거래량 증가")

    elif volume_ratio > 5:
        score -= 1
        reasons.append("거래량 과열 주의")

    # --------------------------------------------------------
    # 매물대
    # --------------------------------------------------------

    if zone_low * 0.97 <= price <= zone_high * 1.05:
        score += 1
        reasons.append("주요 매물대 부근")

    # --------------------------------------------------------
    # 현재가가 20선에서 얼마나 떨어졌는지
    # --------------------------------------------------------

    distance_ma20 = price / ma20 - 1

    if distance_ma20 > CHASE_BLOCK:
        score -= 4
        reasons.append("20선 대비 과도한 상승")

    elif distance_ma20 > CHASE_WARN:
        score -= 2
        reasons.append("20선 대비 이격 - 추격매수 주의")

    return {
        "score": score,
        "price": price,
        "ma20": ma20,
        "ma60": ma60,
        "rsi": rsi,
        "macd": macd,
        "macd_signal": macd_signal,
        "hist": hist,
        "volume_ratio": volume_ratio,
        "recent_high": recent_high,
        "recent_low": recent_low,
        "zone_low": zone_low,
        "zone_high": zone_high,
        "zone_mid": zone_mid,
        "distance_ma20": distance_ma20,
        "reasons": reasons
    }



# ============================================================
# 일봉 추세 / 거래량 돌파 / 돌파 후 지지 확인
# ============================================================

def analyze_daily(df):
    df = prepare_indicators(df)

    last = df.iloc[-1]
    prev = df.iloc[-2]

    price = float(last["close"])
    ma20 = float(last["ma20"])
    ma60 = float(last["ma60"])
    rsi = float(last["rsi"])
    volume_ratio = float(last["volume_ratio"])

    # 현재 봉을 제외한 최근 60일 전고점
    prior_high = float(df["high"].iloc[-61:-1].max())
    prior_low = float(df["low"].iloc[-61:-1].min())

    # 최근 20일 평균 거래량 대비 거래량
    breakout_volume = volume_ratio >= 1.5
    daily_bullish = (
        price > ma20
        and ma20 > ma60
        and ma60 >= float(df["ma60"].iloc[-6])
    )

    # 전고점 위에서 종가가 마감되고, 당일 저가가 전고점 부근을 재확인
    breakout = price > prior_high * 1.002 and breakout_volume
    support_confirmed = (
        breakout
        and float(last["low"]) <= prior_high * 1.025
        and price >= prior_high * 0.995
    )

    # 급등 직후 고점 추격 위험
    distance_ma20 = price / ma20 - 1 if ma20 > 0 else 0
    overextended = (
        distance_ma20 >= 0.12
        or rsi >= 78
        or price >= prior_high * 1.18
    )

    score = 0
    reasons = []

    if daily_bullish:
        score += 3
        reasons.append("일봉 상승 추세")
    else:
        score -= 3
        reasons.append("일봉 상승 추세 미확인")

    if breakout:
        score += 3
        reasons.append("거래량 동반 전고점 돌파")
    elif price > prior_high:
        score += 1
        reasons.append("전고점 위지만 거래량 확인 필요")

    if support_confirmed:
        score += 3
        reasons.append("돌파 후 전고점 지지 확인")
    elif breakout:
        reasons.append("돌파 후 지지 재확인 필요")

    if overextended:
        score -= 5
        reasons.append("급등 후 고점 추격 위험")

    return {
        "score": score,
        "price": price,
        "ma20": ma20,
        "ma60": ma60,
        "rsi": rsi,
        "volume_ratio": volume_ratio,
        "prior_high": prior_high,
        "prior_low": prior_low,
        "daily_bullish": daily_bullish,
        "breakout": breakout,
        "support_confirmed": support_confirmed,
        "overextended": overextended,
        "distance_ma20": distance_ma20,
        "reasons": reasons,
    }


# ============================================================
# 눌림 매수 구간 계산
# ============================================================

def make_entry_zone(price, ma20, zone_low, zone_high, recent_low):
    """
    현재가보다 비싼 가격을 진입구간으로 제시하지 않도록 함.

    우선순위:
      1) 1H 20시간선
      2) 주요 매물대
      3) 최근 저점

    너무 먼 가격은 제거하고,
    현재가의 아래쪽에서 현실적인 눌림 구간을 계산.
    """

    candidates = []

    # 20선
    if 0 < ma20 < price:
        candidates.append(ma20)

    # 매물대
    zone_mid = (zone_low + zone_high) / 2

    if 0 < zone_mid < price:
        candidates.append(zone_mid)

    # 최근 저점
    if 0 < recent_low < price:
        candidates.append(recent_low)

    # 후보가 하나도 없으면 현재가 아래 3~5%
    if not candidates:
        entry_center = price * 0.96
    else:
        # 현재가에 가장 가까운 주요 지지 후보
        entry_center = max(candidates)

    # 진입 중심가 기준 ±2%
    entry_low = entry_center * 0.98
    entry_high = entry_center * 1.02

    # 현재가보다 높아지지 않게 제한
    entry_high = min(entry_high, price * 0.995)

    # 너무 낮은 가격까지 벌어지는 것 방지
    entry_low = max(entry_low, price * 0.88)

    if entry_low >= entry_high:
        entry_low = price * 0.96
        entry_high = price * 0.985

    return entry_low, entry_high


# ============================================================
# 최종 코인 분석
# ============================================================

def analyze_coin(coin):
    ticker = "KRW-" + coin

    df4 = pyupbit.get_ohlcv(
        ticker,
        interval="minute240",
        count=CANDLE_4H
    )

    df1 = pyupbit.get_ohlcv(
        ticker,
        interval="minute60",
        count=CANDLE_1H
    )

    dfD = pyupbit.get_ohlcv(
        ticker,
        interval="day",
        count=CANDLE_DAILY
    )

    if df4 is None or df1 is None or dfD is None:
        return None

    if len(df4) < 130 or len(df1) < 150 or len(dfD) < 80:
        return None

    a4 = analyze_4h(df4)
    a1 = analyze_1h(df1)
    aD = analyze_daily(dfD)

    price = a1["price"]

    total_score = a4["score"] + a1["score"] + aD["score"]

    # 일봉 하락 추세 / 급등 고점은 5~14일 스윙 추천에서 제외
    daily_blocked = (not aD["daily_bullish"]) or aD["overextended"]

    # --------------------------------------------------------
    # 추격매수 차단
    # --------------------------------------------------------

    chase_blocked = (
        a1["distance_ma20"] >= CHASE_BLOCK
    )

    chase_warning = (
        a1["distance_ma20"] >= CHASE_WARN
    )

    if chase_blocked:
        total_score -= 3

    # --------------------------------------------------------
    # 4H 추세가 나쁘면 강한 매수 후보 금지
    # --------------------------------------------------------

    four_hour_bullish = (
        a4["price"] > a4["ma60"]
        and a4["ma20"] > a4["ma60"]
    )

    # --------------------------------------------------------
    # 눌림 진입 구간
    # --------------------------------------------------------

    entry_low, entry_high = make_entry_zone(
        price,
        a1["ma20"],
        a1["zone_low"],
        a1["zone_high"],
        a1["recent_low"]
    )

    # --------------------------------------------------------
    # 지지/손절
    # --------------------------------------------------------

    support_candidates = [
        a1["recent_low"],
        a1["zone_low"],
        a1["ma60"]
    ]

    support_candidates = [
        x for x in support_candidates
        if x > 0 and x < price
    ]

    if support_candidates:
        support = max(support_candidates)
    else:
        support = price * 0.94

    # 손절은 "실제 기준 진입가"를 기준으로 계산.
    # 진입구간 중간값보다 반드시 아래에 위치하도록 함.
    entry_price = (entry_low + entry_high) / 2

    # 기술적 손절: 주요 지지선 아래 3%
    technical_stop = support * 0.97

    # 기본 최대 손실: 실제 진입가 기준 6%
    max_stop = entry_price * (1 - DEFAULT_STOP)

    # 더 보수적인(더 높은) 손절가를 사용하되,
    # 반드시 실제 진입가보다 낮게 유지.
    stop = max(technical_stop, max_stop)

    if stop >= entry_price:
        stop = max_stop

    # --------------------------------------------------------
    # 목표가
    # --------------------------------------------------------

    # 목표가도 현재가가 아니라 실제 기준 진입가에서 계산.
    target1 = entry_price * (1 + TARGET1)
    target2 = entry_price * (1 + TARGET2)

    # 최근 50봉 고점이 +8%보다 높으면 1차 목표로 참고
    recent_high = a1["recent_high"]

    if recent_high > target1 and recent_high < target2:
        target1 = recent_high

    # 항상 2차 목표 > 1차 목표가 되도록 보정
    if target2 <= target1:
        target2 = target1 * 1.05

    # --------------------------------------------------------
    # 리스크/보상
    # --------------------------------------------------------
    # 손절률/목표수익률은 실제 기준 진입가 기준.
    risk_pct = (entry_price - stop) / entry_price * 100

    reward1_pct = (target1 - entry_price) / entry_price * 100
    reward2_pct = (target2 - entry_price) / entry_price * 100

    # 손익비(R:R)
    risk_amount = entry_price - stop
    rr1 = ((target1 - entry_price) / risk_amount) if risk_amount > 0 else 0
    rr2 = ((target2 - entry_price) / risk_amount) if risk_amount > 0 else 0

    # --------------------------------------------------------
    # 1H 추세 확인
    # --------------------------------------------------------
    # 매수는 1H가 실제로 상승 구조인지 확인한 뒤에만 허용.
    one_hour_bullish = (
        a1["price"] >= a1["ma20"]
        and a1["ma20"] >= a1["ma60"]
        and a1["macd"] >= a1["macd_signal"]
        and 45 <= a1["rsi"] < 70
    )

    one_hour_bearish = (
        a1["price"] < a1["ma20"]
        and a1["ma20"] < a1["ma60"]
        and a1["macd"] < a1["macd_signal"]
        and a1["rsi"] < 45
    )

    # --------------------------------------------------------
    # 매수/매도 추천 조건
    # --------------------------------------------------------
    buy_confirmed = (
        four_hour_bullish
        and one_hour_bullish
        and aD["daily_bullish"]
        and not daily_blocked
        and total_score >= 16
        and not chase_blocked
        and entry_low <= price <= entry_high
        and (not aD["breakout"] or aD["support_confirmed"])
    )

    sell_confirmed = (
        one_hour_bearish
        and (not four_hour_bullish or total_score < 10)
    )

    # --------------------------------------------------------
    # 최종 상태
    # --------------------------------------------------------
    if sell_confirmed:
        decision = "매도 추천 - 1H 하락 확인"
    elif daily_blocked:
        decision = "추천 제외 - 일봉 하락/급등 고점"
    elif not four_hour_bullish:
        decision = "관망 - 4H 추세 확인 필요"
    elif chase_blocked:
        decision = "추격매수 금지 - 눌림 대기"
    elif aD["breakout"] and not aD["support_confirmed"]:
        decision = "돌파 확인 - 지지 재확인 대기"
    elif buy_confirmed:
        decision = "매수 후보 - 일봉·돌파·지지 확인"
    elif total_score >= 12:
        if not one_hour_bullish:
            decision = "관심 - 1H 확인 후 매수"
        else:
            decision = "관심 - 눌림 확인"
    elif total_score >= 8:
        decision = "관망"
    else:
        decision = "매수 금지"

    # --------------------------------------------------------
    # 현재가가 진입구간 안에 들어왔는지
    # --------------------------------------------------------

    if entry_low <= price <= entry_high:
        entry_status = "현재가가 눌림 구간"
    elif price > entry_high:
        entry_status = "아직 위 - 눌림 대기"
    else:
        entry_status = "진입구간 이탈 - 재평가"

    # --------------------------------------------------------
    # 예상 보유기간
    # --------------------------------------------------------

    if total_score >= 13:
        holding = "3~7일"
    elif total_score >= 10:
        holding = "4~10일"
    else:
        holding = "관망"

    return {
        "coin": coin,
        "price": price,
        "score4": a4["score"],
        "score1": a1["score"],
        "total_score": total_score,
        "decision": decision,
        "entry_status": entry_status,
        "holding": holding,

        "daily_score": aD["score"],
        "daily_bullish": aD["daily_bullish"],
        "daily_breakout": aD["breakout"],
        "daily_support_confirmed": aD["support_confirmed"],
        "daily_overextended": aD["overextended"],
        "daily_rsi": aD["rsi"],
        "daily_volume_ratio": aD["volume_ratio"],
        "daily_prior_high": aD["prior_high"],
        "daily_ma20": aD["ma20"],
        "daily_ma60": aD["ma60"],
        "daily_reasons": aD["reasons"],

        "rsi4": a4["rsi"],
        "rsi1": a1["rsi"],

        "macd4": a4["macd"],
        "macd4_signal": a4["macd_signal"],

        "macd1": a1["macd"],
        "macd1_signal": a1["macd_signal"],

        "volume_ratio": a1["volume_ratio"],

        "ma20_4": a4["ma20"],
        "ma60_4": a4["ma60"],
        "ma120_4": a4["ma120"],

        "ma20_1": a1["ma20"],
        "ma60_1": a1["ma60"],

        "support": support,
        "resistance": a1["recent_high"],

        "zone_low": a1["zone_low"],
        "zone_high": a1["zone_high"],

        "entry_low": entry_low,
        "entry_high": entry_high,
        "entry_price": entry_price,

        "stop": stop,
        "target1": target1,
        "target2": target2,

        "risk_pct": risk_pct,
        "reward1_pct": reward1_pct,
        "reward2_pct": reward2_pct,
        "rr1": rr1,
        "rr2": rr2,

        "distance_ma20": a1["distance_ma20"] * 100,

        "reasons4": a4["reasons"],
        "reasons1": a1["reasons"],
        "one_hour_bullish": one_hour_bullish,
        "one_hour_bearish": one_hour_bearish,
        "buy_confirmed": buy_confirmed,
        "sell_confirmed": sell_confirmed
    }


# ============================================================
# 전체 분석
# ============================================================

def run_analysis():
    global COINS
    COINS = get_liquid_krw_coins()
    print("\n")
    print("=" * 78)
    print("        업비트 4H + 1H 스윙 분석기")
    print("        목표 : 3~10일 보유 / 주 1~2회 선별")
    print("=" * 78)

    now = datetime.now()
    print(
        "분석시간 : "
        + now.strftime("%Y-%m-%d %H:%M:%S")
    )

    results = []

    for coin in COINS:
        try:
            result = analyze_coin(coin)

            if result is not None:
                results.append(result)

        except Exception as e:
            print(f"\n{coin} 분석 오류 : {e}")

    if not results:
        print("\n데이터를 가져오지 못했습니다.")
        return

    # 점수순 정렬
    results.sort(
        key=lambda x: x["total_score"],
        reverse=True
    )

    # ========================================================
    # 순위
    # ========================================================

    print("\n★ 오늘의 스윙 후보 순위")
    print("-" * 78)

    for i, r in enumerate(results, 1):
        print(
            f"{i}위 {r['coin']:5s} "
            f"{r['total_score']:2d}점 "
            f"(4H {r['score4']:+d} / 1H {r['score1']:+d}) "
            f"{r['decision']}"
        )

    # ========================================================
    # 상세
    # ========================================================

    for r in results:
        print("\n")
        print("=" * 78)
        print(
            f"[{r['coin']}] "
            f"{r['decision']}"
        )
        print("=" * 78)

        print(f"현재가              : {krw(r['price'])}")
        print(
            f"종합점수            : "
            f"{r['total_score']}점 "
            f"(4H {r['score4']} / 1H {r['score1']})"
        )
        print(f"1H 추세 확인       : {'상승 확인' if r['one_hour_bullish'] else '하락/중립'}")
        print(f"매수 조건 충족     : {'YES' if r['buy_confirmed'] else 'NO'}")
        print(f"매도 조건 충족     : {'YES' if r['sell_confirmed'] else 'NO'}")

        print("\n[4시간봉 - 큰 추세]")
        print(f"RSI                 : {r['rsi4']:.1f}")
        print(f"20시간봉 MA         : {krw(r['ma20_4'])}")
        print(f"60시간봉 MA         : {krw(r['ma60_4'])}")
        print(f"120시간봉 MA        : {krw(r['ma120_4'])}")
        print(
            f"MACD                : "
            f"{r['macd4']:.6f} / "
            f"Signal {r['macd4_signal']:.6f}"
        )

        print("\n[1시간봉 - 진입 타이밍]")
        print(f"RSI                 : {r['rsi1']:.1f}")
        print(f"20시간봉 MA         : {krw(r['ma20_1'])}")
        print(f"60시간봉 MA         : {krw(r['ma60_1'])}")
        print(
            f"MACD                : "
            f"{r['macd1']:.6f} / "
            f"Signal {r['macd1_signal']:.6f}"
        )
        print(
            f"거래량              : "
            f"20봉 평균 대비 {r['volume_ratio']:.2f}배"
        )

        print("\n[매물대 / 가격]")
        print(
            f"주요 매물대         : "
            f"{krw(r['zone_low'])} ~ "
            f"{krw(r['zone_high'])}"
        )
        print(f"주요 지지           : {krw(r['support'])}")
        print(f"최근 저항           : {krw(r['resistance'])}")

        print("\n[눌림매수 전략]")
        print(
            f"진입 관심구간       : "
            f"{krw(r['entry_low'])} ~ "
            f"{krw(r['entry_high'])}"
        )
        print(
            f"현재 위치           : "
            f"{r['entry_status']}"
        )

        print(
            f"20선 이격           : "
            f"{r['distance_ma20']:+.1f}%"
        )

        print(
            f"기준 진입가         : "
            f"{krw(r['entry_price'])}"
        )

        print(
            f"손절                : "
            f"{krw(r['stop'])} "
            f"(진입가 기준 -{r['risk_pct']:.1f}%)"
        )

        print(
            f"1차 목표            : "
            f"{krw(r['target1'])} "
            f"(진입가 기준 +{r['reward1_pct']:.1f}%) "
            f"R:R {r['rr1']:.2f}"
        )

        print(
            f"2차 목표            : "
            f"{krw(r['target2'])} "
            f"(진입가 기준 +{r['reward2_pct']:.1f}%) "
            f"R:R {r['rr2']:.2f}"
        )

        print(
            f"예상 보유기간       : "
            f"{r['holding']}"
        )

        print("\n[4H 판단 근거]")
        for reason in r["reasons4"]:
            print(f"  • {reason}")

        print("\n[1H 판단 근거]")
        for reason in r["reasons1"]:
            print(f"  • {reason}")

        if r["distance_ma20"] >= CHASE_BLOCK * 100:
            print(
                "\n⚠ 추격매수 차단"
                " → 현재가에서 따라붙지 말고 눌림을 기다리세요."
            )

        elif r["distance_ma20"] >= CHASE_WARN * 100:
            print(
                "\n⚠ 추격매수 주의"
                " → 현재가보다 낮은 진입구간을 우선 확인하세요."
            )

    # ========================================================
    # 최종 결론
    # ========================================================

    print("\n")
    print("=" * 78)
    print("★ 최종 결론")
    print("=" * 78)

    # "매수 후보"만 별도로 찾음
    candidates = [
        r for r in results
        if r["decision"] == "매수 후보"
    ]

    if candidates:
        best = candidates[0]

        print(
            f"오늘의 1순위 스윙 후보 : "
            f"{best['coin']}"
        )

        print(
            f"현재가 : {krw(best['price'])}"
        )

        print(
            f"진입 관심구간 : "
            f"{krw(best['entry_low'])} ~ "
            f"{krw(best['entry_high'])}"
        )

        print(
            f"기준 진입가 : {krw(best['entry_price'])}"
        )

        print(
            f"손절 : {krw(best['stop'])} "
            f"(진입가 기준 -{best['risk_pct']:.1f}%)"
        )

        print(
            f"1차 목표 : {krw(best['target1'])} "
            f"(진입가 기준 +{best['reward1_pct']:.1f}%, "
            f"R:R {best['rr1']:.2f})"
        )

        print(
            f"2차 목표 : {krw(best['target2'])} "
            f"(진입가 기준 +{best['reward2_pct']:.1f}%, "
            f"R:R {best['rr2']:.2f})"
        )

        print(
            "\n→ 4H 추세와 1H 조건이 모두 맞는 후보입니다."
        )

    else:
        print(
            "오늘은 신규 진입을 서두를 만한 "
            "확실한 후보가 없습니다."
        )

        print(
            "→ 관망하고 눌림 또는 조건 개선을 기다리세요."
        )

    print("\n")
    print("다음 분석까지 1시간 대기합니다.")
    print("=" * 78)


# ============================================================
# 실행
# ============================================================

if __name__ == "__main__":

    while True:

        try:
            run_analysis()

        except KeyboardInterrupt:
            print("\n프로그램을 종료합니다.")
            break

        except Exception as e:
            print("\n전체 분석 오류:")
            print(e)

        time.sleep(3600)
