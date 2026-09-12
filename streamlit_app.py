import streamlit as st
import pandas as pd
from datetime import datetime
import pyupbit
import upbit_swing

st.set_page_config(page_title='업비트 스윙 분석기', page_icon='📈', layout='wide')
st.title('📈 업비트 스윙 분석기')
st.caption('5~14일 스윙 · 사이트 접속/새로고침 시 최신 데이터 갱신')

MIN_TRADE_VALUE = 1_000_000_000
COIN_NAMES = {'BTC':'비트코인','ETH':'이더리움','XRP':'리플','DOGE':'도지코인','SOL':'솔라나','ADA':'에이다','DOOD':'두들즈','SUI':'수이','APT':'앱토스','WLD':'월드코인','PEPE':'페페','SHIB':'시바이누','TRX':'트론','LINK':'체인링크','AVAX':'아발란체'}
try:
    for item in (pyupbit.get_market_all(fiat='KRW') or []):
        m, n = str(item.get('market','')), str(item.get('korean_name','')).strip()
        if m.startswith('KRW-') and n: COIN_NAMES[m[4:]] = n
except Exception: pass

def label(code):
    code = str(code).replace('KRW-','')
    return f'{COIN_NAMES.get(code, code)} ({code})'

def level(decision):
    d = str(decision)
    if '매도 추천' in d or '매도추천' in d: return '매도추천'
    if '매도' in d: return '매도검토'
    if '매수 후보' in d or '매수추천' in d or '매수 추천' in d: return '매수추천'
    if '매수' in d or '관심' in d or '돌파 확인' in d: return '매수검토'
    return '관망'

def current_price(coin):
    try: return float(pyupbit.get_current_price(coin) or 0)
    except Exception: return 0

def btc_warning():
    try:
        df = pyupbit.get_ohlcv('KRW-BTC', interval='day', count=5)
        if df is None or len(df) < 3: return False, '비트코인 데이터 부족'
        change = (float(df['close'].iloc[-1]) / float(df['close'].iloc[-2]) - 1) * 100
        ma3 = df['close'].rolling(3).mean().iloc[-1]
        if change <= -5 or (float(df['close'].iloc[-1]) < float(ma3) and change < -2):
            return True, f'비트코인 일봉 급락/약세 감지 ({change:.1f}%)'
        return False, f'비트코인 최근 일봉 변동 {change:+.1f}%'
    except Exception as e: return False, f'비트코인 확인 실패: {e}'

with st.spinner('업비트 KRW 거래대금과 시세를 확인하는 중입니다...'):
    coins = upbit_swing.get_liquid_krw_coins(MIN_TRADE_VALUE)
if not coins:
    st.error('거래대금 정보를 불러오지 못했습니다. 새로고침해 주세요.'); st.stop()
upbit_swing.COINS = coins
warn, warn_text = btc_warning()
if warn: st.error('🚨 알트코인 전체 위험 경고: ' + warn_text + '. 신규 매수는 보수적으로 판단하세요.')
else: st.info('비트코인 시장 상태: ' + warn_text)

st.subheader('① 보유 코인 상태 추적')
st.caption('보유 중인 코인을 입력하면 매수가 대비 수익률, 보유일수별 상태, 손절/익절 판단을 계산합니다.')
if 'holdings' not in st.session_state:
    st.session_state.holdings = pd.DataFrame([{'코인':'DOOD','매수가':2.572,'보유일수':0,'수량':0.0}])
h = st.data_editor(st.session_state.holdings, num_rows='dynamic', use_container_width=True, key='holdings_editor')
st.session_state.holdings = h

with st.spinner('전체 코인 분석 중입니다...'):
    results = []
    for coin in coins:
        try:
            r = upbit_swing.analyze_coin(coin)
            if r: results.append(r)
        except Exception: pass
results = sorted(results, key=lambda x: x.get('total_score',0), reverse=True)
by_coin = {str(r['coin']).replace('KRW-',''): r for r in results}

tracking = []
for _, row in h.iterrows():
    code = str(row.get('코인','')).upper().replace('KRW-','').strip()
    if not code or code == 'NAN': continue
    buy = float(row.get('매수가',0) or 0); days = int(row.get('보유일수',0) or 0); qty = float(row.get('수량',0) or 0)
    price = current_price('KRW-'+code)
    r = by_coin.get(code)
    if buy <= 0 or price <= 0: continue
    ret = (price/buy-1)*100
    status = '관망'
    action = '보유 유지'
    if r:
        stop = float(r.get('stop',0) or 0); t1 = float(r.get('target1',0) or 0); t2 = float(r.get('target2',0) or 0)
        support = float(r.get('daily_support',0) or r.get('support',0) or 0)
        if stop and price <= stop: status, action = '매도추천', '손절선 도달 · 즉시 대응 검토'
        elif support and price < support: status, action = '매도검토', '일봉 지지선 이탈'
        elif t2 and price >= t2: status, action = '매도검토', '2차 목표가 도달 · 잔량 익절 검토'
        elif t1 and price >= t1: status, action = '매도검토', '1차 목표가 도달 · 일부 익절 검토'
        elif days >= 14: status, action = '매도검토', '14일 도달 · 스윙 종료 검토'
        elif days >= 10: status, action = '관망', '10일차 · 수익 보호 우선'
        elif days >= 7: status, action = '관망', '7일차 · 추세 유지 여부 확인'
        elif days >= 5: status, action = '관망', '5일차 · 지지선/거래량 확인'
        else: status, action = level(r.get('decision','')), '초기 보유 구간'
    tracking.append({'코인':label(code),'현재가':upbit_swing.krw(price),'매수가':upbit_swing.krw(buy),'수익률':f'{ret:+.2f}%','보유일수':days,'5일': '도달' if days>=5 else '대기','7일':'도달' if days>=7 else '대기','10일':'도달' if days>=10 else '대기','14일':'도달' if days>=14 else '대기','상태':status,'행동':action})
if tracking: st.dataframe(pd.DataFrame(tracking), use_container_width=True, hide_index=True)
else: st.warning('보유 코인을 입력하면 여기에 상태가 표시됩니다.')

st.divider(); st.subheader('② 신규 스윙 후보')
st.caption(f'분석 대상: KRW 전체 마켓 중 24시간 거래대금 {MIN_TRADE_VALUE:,}원 이상 · {len(coins)}개')
rows=[]
for i,r in enumerate(results,1):
    rows.append({'순위':i,'코인':label(r['coin']),'추천':level(r['decision']),'일봉':'상승' if r.get('daily_bullish') else '하락/중립','전고점 돌파':'확인' if r.get('daily_breakout') else '없음','돌파 지지':'확인' if r.get('daily_support_confirmed') else '대기','고점 위험':'제외' if r.get('daily_overextended') else '정상','1H':'상승' if r.get('one_hour_bullish') else ('하락' if r.get('one_hour_bearish') else '중립')})
st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

st.subheader('③ 코인별 상세')
for r in results[:20]:
    with st.expander(f"{label(r['coin'])} · {level(r['decision'])}"):
        st.write('추천 상태:', level(r['decision']))
        st.write('진입 관심구간:', upbit_swing.krw(r.get('entry_low',0)), '~', upbit_swing.krw(r.get('entry_high',0)))
        st.write('손절선:', upbit_swing.krw(r.get('stop',0)))
        st.write('목표가:', upbit_swing.krw(r.get('target1',0)), '/', upbit_swing.krw(r.get('target2',0)))
        st.write('일봉 지지:', upbit_swing.krw(r.get('daily_support', r.get('support',0))))
        st.write('보유 기준: 5일 · 7일 · 10일 · 14일')

st.info('주의: 기술적 신호는 확률적 참고자료이며 수익을 보장하지 않습니다. 손절·익절 기준은 실제 주문 전 반드시 현재 호가와 시장 상황을 확인하세요.')
