import time
from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np

APP_VERSION = "3.4.1"
import pandas as pd
import pyupbit


# ============================================================
# 업비트 스윙 분석기 V3.4
# 목적: 3~10일 스윙 / 눌림 진입 / 추격매수 차단
#
# V3 핵심 변경
# 1) 고득점이어도 "지금 사기 좋은 자리"가 아니면 매수 금지
# 2) 최근 급등률 / MA20 이격 / ATR 과열 / 거래량 폭발을 별도 차단
# 3) 4H 추세 + 1H 구조 + 15m 진입 확인을 분리
# 4) 현재가 기준 목표가가 아니라 "권장 진입가" 기준으로 R:R 계산
# 5) KRW 상위 거래대금 코인을 자동 스캔하되 저유동성 종목은 제외
#
# 주의: 자동매매/주문 기능 없음. 기술적 분석 보조용.
# ============================================================

# 스캔 대상
MAX_SCAN_COINS = 40
MIN_TRADE_VALUE_24H = 1_000_000_000  # 24h 거래대금 10억원 이상

CANDLE_4H = 220
CANDLE_1H = 260
CANDLE_15M = 220

# 추격매수 차단
CHASE_WARN_MA20 = 0.05       # 1H 20선 대비 +5%
CHASE_BLOCK_MA20 = 0.08      # 1H 20선 대비 +8%
SURGE_1H_WARN = 0.07         # 최근 6개 1H봉(약 6시간) +7%
SURGE_1H_BLOCK = 0.12        # +12%
SURGE_4H_BLOCK = 0.18        # 최근 6개 4H봉 +18%

# 과열 거래량
VOLUME_SPIKE_BLOCK = 5.0
VOLUME_SPIKE_WARN = 3.0

# 손절/목표
DEFAULT_STOP_PCT = 0.06
TARGET1_PCT = 0.08
TARGET2_PCT = 0.15

# 최소 R:R
MIN_RR1 = 1.30
MIN_RR2 = 2.00

# 1H 눌림 진입 허용 범위
ENTRY_MIN_FROM_PRICE = 0.02
ENTRY_MAX_FROM_PRICE = 0.10


def krw(value):
    value = float(value)
    if value >= 1000:
        return f"{value:,.0f}원"
    if value >= 1:
        return f"{value:,.2f}원"
    if value >= 0.01:
        return f"{value:,.4f}원"
    return f"{value:,.6f}원"


def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def calculate_macd(close):
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    return macd, signal, macd - signal


def prepare_indicators(df):
    df = df.copy()
    close = df["close"]
    volume = df["volume"]

    df["ma20"] = close.rolling(20).mean()
    df["ma60"] = close.rolling(60).mean()
    df["ma120"] = close.rolling(120).mean()
    df["rsi"] = calculate_rsi(close)

    macd, signal, hist = calculate_macd(close)
    df["macd"] = macd
    df["macd_signal"] = signal
    df["macd_hist"] = hist

    df["volume_ma20"] = volume.rolling(20).mean()
    df["volume_ratio"] = volume / df["volume_ma20"].replace(0, np.nan)

    # ATR(14)
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    df["atr"] = tr.rolling(14).mean()
    df["atr_pct"] = df["atr"] / close

    return df


def calculate_volume_profile(df, bins=24):
    prices = df["close"]
    if len(prices) < 20:
        return float(prices.min()), float(prices.max())

    low = float(prices.min())
    high = float(prices.max())
    if low == high:
        return low, high

    try:
        price_bins = pd.cut(prices, bins=bins)
        profile = df.groupby(price_bins, observed=True)["volume"].sum()
        if profile.empty:
            return low, high
        zone = profile.idxmax()
        return float(zone.left), float(zone.right)
    except Exception:
        return low, high


def fetch_market_names():
    """업비트 KRW 시장의 한글/영문 종목명을 가져온다."""
    try:
        data = pyupbit.get_tickers(fiat="KRW", verbose=True)
        if not isinstance(data, list):
            return {}
        return {
            item.get("market", "").replace("KRW-", ""): {
                "korean": item.get("korean_name", ""),
                "english": item.get("english_name", ""),
            }
            for item in data
            if item.get("market", "").startswith("KRW-")
        }
    except Exception:
        return {}


def fetch_top_krw_coins(limit=MAX_SCAN_COINS):
    """24시간 거래대금 기준으로 유동성이 높은 KRW 종목을 선별."""
    tickers = pyupbit.get_tickers(fiat="KRW")
    if not tickers:
        return []

    rows = []
    # get_current_price can accept many markets at once.
    data = pyupbit.get_current_price(tickers, verbose=True)
    if not isinstance(data, list):
        return []

    for item in data:
        try:
            trade_value = float(item.get("acc_trade_price_24h", 0))
            market = item.get("market", "")
            if market.startswith("KRW-") and trade_value >= MIN_TRADE_VALUE_24H:
                rows.append((market.replace("KRW-", ""), trade_value))
        except Exception:
            continue

    rows.sort(key=lambda x: x[1], reverse=True)
    return [coin for coin, _ in rows[:limit]]


def analyze_4h(df):
    df = prepare_indicators(df)
    last, prev = df.iloc[-1], df.iloc[-2]

    price = float(last["close"])
    ma20, ma60, ma120 = map(float, [last["ma20"], last["ma60"], last["ma120"]])
    rsi = float(last["rsi"])
    macd, signal = float(last["macd"]), float(last["macd_signal"])
    hist, prev_hist = float(last["macd_hist"]), float(prev["macd_hist"])

    score = 0
    reasons = []

    if price > ma60:
        score += 2
        reasons.append("4H 가격 > 60선")
    if ma20 > ma60:
        score += 2
        reasons.append("4H 20 > 60")
    if ma60 > ma120:
        score += 1
        reasons.append("4H 60 > 120")
    if macd > signal:
        score += 1
        reasons.append("4H MACD 상승")
    if hist > prev_hist:
        score += 1
        reasons.append("4H MACD 모멘텀 개선")

    if 45 <= rsi <= 68:
        score += 1
        reasons.append("4H RSI 양호")
    elif rsi > 75:
        score -= 2
        reasons.append("4H RSI 과열")
    elif rsi < 40:
        score -= 1
        reasons.append("4H RSI 약세")

    surge_4h = float(price / df["close"].iloc[-7] - 1)
    if surge_4h >= SURGE_4H_BLOCK:
        score -= 5
        reasons.append(f"최근 24H 급등 +{surge_4h*100:.1f}% → 추격 위험")

    return {
        "score": score,
        "price": price,
        "ma20": ma20,
        "ma60": ma60,
        "ma120": ma120,
        "rsi": rsi,
        "macd": macd,
        "macd_signal": signal,
        "hist": hist,
        "surge_4h": surge_4h,
        "reasons": reasons,
    }


def analyze_1h(df):
    df = prepare_indicators(df)
    last, prev = df.iloc[-1], df.iloc[-2]

    price = float(last["close"])
    ma20, ma60 = float(last["ma20"]), float(last["ma60"])
    rsi = float(last["rsi"])
    macd, signal = float(last["macd"]), float(last["macd_signal"])
    hist, prev_hist = float(last["macd_hist"]), float(prev["macd_hist"])
    volume_ratio = float(last["volume_ratio"])
    atr_pct = float(last["atr_pct"])

    recent_high = float(df["high"].tail(50).max())
    recent_low = float(df["low"].tail(50).min())
    zone_low, zone_high = calculate_volume_profile(df.tail(150))

    distance_ma20 = price / ma20 - 1
    surge_6h = float(price / df["close"].iloc[-7] - 1)

    score = 0
    reasons = []

    if price > ma20:
        score += 1
        reasons.append("1H 20선 위")
    if ma20 > ma60:
        score += 1
        reasons.append("1H 20 > 60")
    if macd > signal:
        score += 1
        reasons.append("1H MACD 상승")
    if hist > prev_hist:
        score += 1
        reasons.append("1H MACD 모멘텀 개선")

    if 45 <= rsi <= 65:
        score += 2
        reasons.append("1H RSI 눌림/상승 구간")
    elif 65 < rsi <= 70:
        score += 1
        reasons.append("1H RSI 강세")
    elif rsi > 75:
        score -= 3
        reasons.append("1H RSI 과열")
    elif rsi < 40:
        score -= 1
        reasons.append("1H RSI 약세")

    if 1.2 <= volume_ratio <= 3.5:
        score += 2
        reasons.append("거래량 증가")
    elif volume_ratio > VOLUME_SPIKE_BLOCK:
        score -= 4
        reasons.append("거래량 폭발 → 급등 추격 위험")
    elif volume_ratio > VOLUME_SPIKE_WARN:
        score -= 2
        reasons.append("거래량 과열 주의")

    if zone_low * 0.97 <= price <= zone_high * 1.05:
        score += 1
        reasons.append("주요 매물대 부근")

    # MA20 이격
    if distance_ma20 > CHASE_BLOCK_MA20:
        score -= 6
        reasons.append(f"1H 20선 대비 +{distance_ma20*100:.1f}% → 매수 차단")
    elif distance_ma20 > CHASE_WARN_MA20:
        score -= 3
        reasons.append(f"1H 20선 대비 +{distance_ma20*100:.1f}% → 추격 주의")

    # 단기 급등
    if surge_6h >= SURGE_1H_BLOCK:
        score -= 7
        reasons.append(f"최근 6시간 +{surge_6h*100:.1f}% → 추격매수 차단")
    elif surge_6h >= SURGE_1H_WARN:
        score -= 3
        reasons.append(f"최근 6시간 +{surge_6h*100:.1f}% → 급등 주의")

    # ATR이 지나치게 큰 경우
    if atr_pct > 0.08:
        score -= 3
        reasons.append(f"ATR 변동성 {atr_pct*100:.1f}% → 위험")

    return {
        "score": score,
        "price": price,
        "ma20": ma20,
        "ma60": ma60,
        "rsi": rsi,
        "macd": macd,
        "macd_signal": signal,
        "hist": hist,
        "volume_ratio": volume_ratio,
        "atr_pct": atr_pct,
        "recent_high": recent_high,
        "recent_low": recent_low,
        "zone_low": zone_low,
        "zone_high": zone_high,
        "zone_mid": (zone_low + zone_high) / 2,
        "distance_ma20": distance_ma20,
        "surge_6h": surge_6h,
        "reasons": reasons,
    }


def analyze_15m(df):
    df = prepare_indicators(df)
    last, prev = df.iloc[-1], df.iloc[-2]
    price = float(last["close"])
    ma20, ma60 = float(last["ma20"]), float(last["ma60"])
    rsi = float(last["rsi"])
    hist, prev_hist = float(last["macd_hist"]), float(prev["macd_hist"])

    # 15m은 '사도 된다'가 아니라 '반등이 시작됐는지' 확인
    bullish = price > ma20 and ma20 >= ma60 and hist >= prev_hist and 45 <= rsi <= 72
    bearish = price < ma20 and ma20 < ma60

    return {
        "bullish": bullish,
        "bearish": bearish,
        "price": price,
        "rsi": rsi,
        "ma20": ma20,
        "ma60": ma60,
    }


def make_entry_zone(price, ma20, zone_low, zone_high, recent_low):
    """현재가 아래의 지지 후보를 이용해 눌림 구간을 만든다."""
    candidates = []
    for value in [ma20, (zone_low + zone_high) / 2, recent_low]:
        if 0 < value < price:
            distance = (price - value) / price
            if ENTRY_MIN_FROM_PRICE <= distance <= ENTRY_MAX_FROM_PRICE:
                candidates.append(value)

    if candidates:
        center = max(candidates)
    else:
        center = price * 0.96

    low = center * 0.985
    high = center * 1.015

    # 현재가보다 높은 진입구간 금지
    high = min(high, price * 0.995)
    low = max(low, price * (1 - ENTRY_MAX_FROM_PRICE))

    if low >= high:
        return price * 0.96, price * 0.985
    return low, high


def analyze_coin(coin, include_15m=True):
    ticker = "KRW-" + coin

    df4 = pyupbit.get_ohlcv(ticker, interval="minute240", count=CANDLE_4H)
    time.sleep(0.12)
    df1 = pyupbit.get_ohlcv(ticker, interval="minute60", count=CANDLE_1H)

    if df4 is None or df1 is None:
        return None
    if len(df4) < 150 or len(df1) < 180:
        return None

    a4 = analyze_4h(df4)
    a1 = analyze_1h(df1)

    a15 = None
    if include_15m:
        time.sleep(0.12)
        df15 = pyupbit.get_ohlcv(ticker, interval="minute15", count=CANDLE_15M)
        if df15 is not None and len(df15) >= 100:
            a15 = analyze_15m(df15)

    price = a1["price"]
    total_score = a4["score"] + a1["score"]

    # 구조적 차단 조건
    chase_blocked = (
        a1["distance_ma20"] >= CHASE_BLOCK_MA20
        or a1["surge_6h"] >= SURGE_1H_BLOCK
        or a4["surge_4h"] >= SURGE_4H_BLOCK
        or a1["volume_ratio"] >= VOLUME_SPIKE_BLOCK
        or a1["rsi"] >= 78
    )

    chase_warning = (
        a1["distance_ma20"] >= CHASE_WARN_MA20
        or a1["surge_6h"] >= SURGE_1H_WARN
        or a1["volume_ratio"] >= VOLUME_SPIKE_WARN
    )

    four_hour_bullish = (
        a4["price"] > a4["ma60"]
        and a4["ma20"] > a4["ma60"]
        and a4["ma60"] > a4["ma120"]
    )

    one_hour_bullish = (
        a1["price"] > a1["ma20"]
        and a1["ma20"] > a1["ma60"]
        and 42 <= a1["rsi"] <= 72
    )

    one_hour_bearish = (
        a1["price"] < a1["ma20"]
        and a1["ma20"] < a1["ma60"]
    )

    # 눌림 진입 구간
    entry_low, entry_high = make_entry_zone(
        price,
        a1["ma20"],
        a1["zone_low"],
        a1["zone_high"],
        a1["recent_low"],
    )
    entry_price = (entry_low + entry_high) / 2

    # 지지선: 현재 진행 중인 캔들은 제외하고 최근 지지 후보를 계산한다.
    # 이렇게 해야 "잠깐 저가를 찍은 것"과 "확정 이탈"을 구분하기 쉽다.
    prior1 = df1.iloc[:-2] if len(df1) >= 52 else df1.iloc[:-1]
    prior_recent_low = float(prior1["low"].tail(50).min()) if not prior1.empty else a1["recent_low"]
    prior_zone_low, _ = calculate_volume_profile(prior1.tail(150)) if len(prior1) >= 20 else (a1["zone_low"], a1["zone_high"])
    support_candidates = [prior_recent_low, prior_zone_low, a1["ma60"]]
    support_candidates = [x for x in support_candidates if 0 < x < price]
    support = max(support_candidates) if support_candidates else price * 0.94

    # "2.15원 이탈" 같은 상황을 자동 감지하기 위한 확인 신호.
    # 마지막 완성 1H/4H 봉의 종가가 지지 아래에 있고 거래량이 증가했을 때만 강한 이탈로 본다.
    c1 = df1.iloc[-2]
    c1_prev = df1.iloc[-3]
    vol_ma1 = float(df1["volume"].rolling(20).mean().iloc[-2])
    closed_1h_volume_ratio = float(c1["volume"] / vol_ma1) if vol_ma1 > 0 else 0.0
    support_break_1h = (
        float(c1["close"]) < support * 0.995
        and float(c1["low"]) < support * 0.99
        and closed_1h_volume_ratio >= 1.5
    )
    false_break_1h = (
        float(c1["low"]) < support * 0.995
        and float(c1["close"]) >= support
    )

    df4_prior = df4.iloc[:-2] if len(df4) >= 52 else df4.iloc[:-1]
    support4_candidates = [
        float(df4_prior["low"].tail(30).min()) if not df4_prior.empty else a4["price"] * 0.94,
        float(a4["ma60"]),
    ]
    support4_candidates = [x for x in support4_candidates if 0 < x < a4["price"]]
    support4 = max(support4_candidates) if support4_candidates else a4["price"] * 0.94
    c4 = df4.iloc[-2]
    vol_ma4 = float(df4["volume"].rolling(20).mean().iloc[-2])
    closed_4h_volume_ratio = float(c4["volume"] / vol_ma4) if vol_ma4 > 0 else 0.0
    support_break_4h = (
        float(c4["close"]) < support4 * 0.995
        and float(c4["low"]) < support4 * 0.99
        and closed_4h_volume_ratio >= 1.3
    )

    technical_stop = support * 0.97
    max_stop = entry_price * (1 - DEFAULT_STOP_PCT)
    stop = min(technical_stop, max_stop)
    if stop <= 0 or stop >= entry_price:
        stop = entry_price * (1 - DEFAULT_STOP_PCT)

    target1 = entry_price * (1 + TARGET1_PCT)
    target2 = entry_price * (1 + TARGET2_PCT)

    # 최근 고점이 목표 범위에 있으면 1차 목표로 활용
    recent_high = a1["recent_high"]
    if entry_price < recent_high < target2:
        target1 = max(entry_price * 1.03, recent_high)

    risk = entry_price - stop
    rr1 = (target1 - entry_price) / risk if risk > 0 else 0
    rr2 = (target2 - entry_price) / risk if risk > 0 else 0

    entry_status = (
        "현재가가 눌림구간" if entry_low <= price <= entry_high
        else "눌림 대기" if price > entry_high
        else "재평가 필요"
    )

    # 5~14일 상승 가능성 순위용 내부 점수
    horizon_score = 0.0
    horizon_score += 3.0 if four_hour_bullish else -3.0
    horizon_score += 2.0 if one_hour_bullish else -2.0
    horizon_score += 1.5 if (a15 is not None and a15["bullish"]) else 0.0
    horizon_score += min(max(total_score, 0), 16) * 0.35
    horizon_score -= max(0.0, a1["distance_ma20"] - 0.03) * 20
    horizon_score -= max(0.0, a1["surge_6h"] - 0.05) * 12
    horizon_score -= max(0.0, a1["atr_pct"] - 0.06) * 10
    if false_break_1h:
        horizon_score += 0.8
    if support_break_1h:
        horizon_score -= 3.0
    if support_break_4h:
        horizon_score -= 5.0
    if rr1 >= MIN_RR1 and rr2 >= MIN_RR2:
        horizon_score += 1.5

    # 눈에 띄는 4단계 판단 + 관망.
    # 지지선 이탈은 가격만이 아니라 "완성 봉 종가 + 거래량"을 함께 확인한다.
    # 매도 판단은 보유자 기준의 기술적 약세 신호이며 자동매도 기능은 없다.
    if support_break_4h:
        decision = "매도추천"
    elif support_break_1h and not false_break_1h:
        decision = "매도검토"
    elif one_hour_bearish and not four_hour_bullish:
        decision = "매도추천"
    elif (one_hour_bearish or a1["rsi"] >= 75 or
          (a1["macd"] < a1["macd_signal"] and a1["hist"] < 0)):
        decision = "매도검토"
    elif false_break_1h or (price <= support * 1.02 and not support_break_1h and not support_break_4h):
        decision = "반등대기"
    elif four_hour_bullish and one_hour_bullish and not chase_blocked and rr1 >= MIN_RR1 and rr2 >= MIN_RR2:
        if entry_low <= price <= entry_high and (a15 is None or a15["bullish"]):
            decision = "매수추천"
        else:
            decision = "매수검토"
    elif four_hour_bullish and one_hour_bullish:
        decision = "매수검토"
    else:
        decision = "관망"

    # 급등 추격 상태에서는 매수추천을 허용하지 않는다.
    if chase_blocked and decision in ("매수추천", "매수검토"):
        decision = "매수검토"
        horizon_score -= 3

    holding = "5~14일" if horizon_score >= 5 else "관망"

    return {
        "coin": coin,
        "korean_name": coin,
        "english_name": coin,
        "price": price,
        "horizon_score": horizon_score,
        "score4": a4["score"],
        "score1": a1["score"],
        "total_score": total_score,
        "decision": decision,
        "entry_status": entry_status,
        "holding": holding,
        "rsi4": a4["rsi"],
        "rsi1": a1["rsi"],
        "rsi15": a15["rsi"] if a15 else np.nan,
        "ma20_4": a4["ma20"],
        "ma60_4": a4["ma60"],
        "ma120_4": a4["ma120"],
        "ma20_1": a1["ma20"],
        "ma60_1": a1["ma60"],
        "macd4": a4["macd"],
        "macd4_signal": a4["macd_signal"],
        "macd1": a1["macd"],
        "macd1_signal": a1["macd_signal"],
        "volume_ratio": a1["volume_ratio"],
        "atr_pct": a1["atr_pct"] * 100,
        "support": support,
        "support4": support4,
        "resistance": recent_high,
        "closed_1h_volume_ratio": closed_1h_volume_ratio,
        "closed_4h_volume_ratio": closed_4h_volume_ratio,
        "support_break_1h": support_break_1h,
        "support_break_4h": support_break_4h,
        "false_break_1h": false_break_1h,
        "zone_low": a1["zone_low"],
        "zone_high": a1["zone_high"],
        "entry_low": entry_low,
        "entry_high": entry_high,
        "entry_price": entry_price,
        "stop": stop,
        "target1": target1,
        "target2": target2,
        "risk_pct": (entry_price - stop) / entry_price * 100,
        "reward1_pct": (target1 - entry_price) / entry_price * 100,
        "reward2_pct": (target2 - entry_price) / entry_price * 100,
        "rr1": rr1,
        "rr2": rr2,
        "distance_ma20": a1["distance_ma20"] * 100,
        "surge_6h": a1["surge_6h"] * 100,
        "surge_4h": a4["surge_4h"] * 100,
        "chase_blocked": chase_blocked,
        "chase_warning": chase_warning,
        "one_hour_bullish": one_hour_bullish,
        "one_hour_bearish": one_hour_bearish,
        "four_hour_bullish": four_hour_bullish,
        "15m_bullish": a15["bullish"] if a15 else False,
        "reasons4": a4["reasons"],
        "reasons1": a1["reasons"],
    }


def scan_market(max_coins=MAX_SCAN_COINS):
    coins = fetch_top_krw_coins(max_coins)
    names = fetch_market_names()
    results = []
    errors = []

    for coin in coins:
        try:
            result = analyze_coin(coin)
            if result:
                name = names.get(coin, {})
                result["korean_name"] = name.get("korean") or coin
                result["english_name"] = name.get("english") or coin
                results.append(result)
        except Exception as exc:
            errors.append(f"{coin}: {exc}")

    # 5~14일 상승 가능성 순으로 정렬하되, 매도 신호는 아래로 보낸다.
    decision_priority = {"매수추천": 0, "매수검토": 1, "반등대기": 2, "관망": 3, "매도검토": 4, "매도추천": 5}
    results.sort(key=lambda r: (decision_priority.get(r["decision"], 9), -r["horizon_score"]))
    return results, errors


def run_analysis():
    print("=" * 90)
    print("업비트 스윙 분석기 V3.2")
    print("목표: 오늘 매수 기준 5~14일 상승 가능성 순위 / 눌림 진입 / 급등 추격매수 차단")
    print(datetime.now(ZoneInfo("Asia/Seoul")).strftime("분석시간(KST): %Y-%m-%d %H:%M:%S"))
    print("=" * 90)

    results, errors = scan_market()

    if not results:
        print("분석 결과가 없습니다.")
        return

    print("\n★ 오늘의 우선 후보")
    for i, r in enumerate(results[:10], 1):
        print(
            f"{i:>2}. {r['korean_name']}({r['english_name']}) "
            f"{r['decision']:<8} "
            f"현재 {krw(r['price'])}  "
            f"진입 {krw(r['entry_low'])}~{krw(r['entry_high'])}"
        )

    if errors:
        print(f"\n일부 종목 오류 {len(errors)}건")

    best = next((r for r in results if r["decision"] == "매수 후보"), None)
    if best:
        print("\n★ 1순위 매수 후보")
        print(best["coin"], best["decision"])
        print("진입:", krw(best["entry_low"]), "~", krw(best["entry_high"]))
        print("손절:", krw(best["stop"]))
        print("1차:", krw(best["target1"]), "R:R", f"{best['rr1']:.2f}")
        print("2차:", krw(best["target2"]), "R:R", f"{best['rr2']:.2f}")
    else:
        print("\n★ 결론: 지금 당장 따라붙을 만한 확실한 매수 후보가 없습니다.")
        print("→ 눌림 또는 15분 반등 확인을 기다리는 쪽으로 설계되었습니다.")


if __name__ == "__main__":
    run_analysis()
