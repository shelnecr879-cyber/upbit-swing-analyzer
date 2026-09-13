import streamlit as st
import pandas as pd
from datetime import datetime
import upbit_swing

st.set_page_config(page_title="업비트 스윙 분석기", page_icon="📈", layout="wide")

st.title("📈 업비트 4H + 1H 스윙 분석기")
st.caption("목표: 3~10일 보유 / 주 1~2회 선별 · KRW 시장")
st.success("🔄 사이트 접속 또는 새로고침 때마다 업비트 최신 데이터로 재분석합니다. 예약 갱신 시간은 없습니다.")

DEFAULT_COINS = [
    "BTC", "ETH", "XRP", "DOGE", "SOL", "ADA", "AVAX", "LINK",
    "DOT", "TRX", "SUI", "APT", "ARB", "OP", "NEAR", "ATOM",
    "ETC", "BCH", "LTC", "EOS", "STX", "SEI", "IMX", "INJ",
    "PEPE", "BONK", "WIF", "SHIB", "HBAR", "ONDO", "RENDER"
]

AVAILABLE_COINS = list(getattr(upbit_swing, "COINS", DEFAULT_COINS))

coins = st.multiselect(
    "분석 코인",
    options=AVAILABLE_COINS,
    default=AVAILABLE_COINS
)
refresh = st.button("🔄 지금 분석")

# 접속/새로고침 때마다 최신 업비트 데이터를 가져오도록 캐시를 사용하지 않습니다.

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

# ===== V4.0 보강: 지지선/매물대/급등패턴/멀티타임프레임 보조 분석 =====
import numpy as np

def _safe_num(v, default=0.0):
    try: return float(v)
    except Exception: return default

def enrich_market_structure(r):
    """기존 upbit_swing 결과에 시장구조 보조지표를 붙입니다."""
    code = str(r.get('coin','')).replace('KRW-','')
    market = f'KRW-{code}'
    try:
        d = pyupbit.get_ohlcv(market, interval='day', count=70)
        h = pyupbit.get_ohlcv(market, interval='minute60', count=120)
        m = pyupbit.get_ohlcv(market, interval='minute15', count=160)
        if any(x is None or len(x) < 25 for x in (d,h,m)): return r
        price = float(d['close'].iloc[-1])
        def levels(df, n):
            recent = df.tail(n)
            return float(recent['low'].min()), float(recent['high'].max())
        s20, hi20 = levels(d,20); s60, hi60 = levels(d,60)
        # 거래량 가중 가격대(간이 Volume Profile)
        recent = d.tail(60).copy()
        bins = np.linspace(float(recent.low.min()), float(recent.high.max()), 25)
        typical = (recent.high + recent.low + recent.close) / 3
        idx = np.clip(np.digitize(typical, bins)-1, 0, len(bins)-2)
        vol = recent.volume.to_numpy()
        profile = np.bincount(idx, weights=vol, minlength=len(bins)-1)
        vp = float((bins[:-1] + bins[1:])[int(np.argmax(profile))] / 2)
        prev_high = float(d['high'].iloc[-21:-1].max())
        breakout = price > prev_high
        ret20 = price / float(d['close'].iloc[-21]) - 1
        vol_ratio = float(d['volume'].iloc[-1] / max(d['volume'].tail(20).mean(), 1e-12))
        support = max(s20, s60)
        distance = (price/support-1)*100 if support else 0
        support_break = price < support
        retest = bool(breakout and d['low'].iloc[-1] <= prev_high*1.015 and price >= prev_high*0.99)
        overheat = bool(ret20 >= 0.25 and price >= float(d['high'].tail(20).max())*0.97)
        pullback_hold = bool(ret20 > 0.08 and price < float(d['high'].tail(20).max())*0.95 and price >= support*1.01)
        volume_fade_break = bool(ret20 > 0.08 and vol_ratio < 0.7 and support_break)
        stop = _safe_num(r.get('stop'), price*0.95)
        r.update({
            'support20':s20,'support60':s60,'volume_profile':vp,
            'support_distance_pct':distance,'support_break':support_break,
            'breakout_retest':retest,'breakout':breakout,'volume_ratio_daily':vol_ratio,
            'overheat':overheat,'pullback_hold':pullback_hold,'volume_fade_break':volume_fade_break,
            'stop_support_gap_pct':(stop-support)/max(support,1e-12)*100,
            'structure_score':0.0,
        })
        score = 0
        score += 1.0 if price > s20 else -1.0
        score += 1.0 if price > s60 else -1.0
        score += 1.0 if price >= vp else -0.5
        score += 1.0 if retest else (0.5 if breakout else 0)
        score += 1.0 if distance >= 3 else (0.5 if distance >= 0 else -1)
        if overheat: score -= 1.0
        if pullback_hold: score += 0.8
        if volume_fade_break: score -= 1.5
        if support_break: score -= 1.5
        r['structure_score'] = score
        base = _safe_num(r.get('total_score'), 5)
        r['total_score'] = round(max(0,min(10,base + score*0.25)),1)
    except Exception:
        pass
    return r

# 기존 분석 결과를 시장구조 보정 후 점수순으로 재정렬
_old_get_results = get_results
def get_results(selected):
    enriched=[]
    for coin in selected:
        try:
            r=upbit_swing.analyze_coin(coin)
            if r: enriched.append(enrich_market_structure(r))
        except Exception as e:
            st.warning(f'{coin} 분석 오류: {e}')
    return sorted(enriched,key=lambda x:_safe_num(x.get('total_score')),reverse=True)


if True:
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

