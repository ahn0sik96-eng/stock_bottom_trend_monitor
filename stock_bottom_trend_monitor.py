# -*- coding: utf-8 -*-
"""
개별종목 바닥확인 → 상승추세 모니터 v1.0
========================================

국내 개별종목을 다음 5단계로 자동 분류한다.

  1) 하락 진행
  2) 바닥 형성 관찰
  3) 바닥 확인
  4) 상승추세
  5) 추세 훼손

판정 축:
  - 바닥 형성: 신저가 중단, RSI 반등, 단기선 회복, 거래량 소진,
               외국인+기관 수급, KOSPI 대비 상대강도
  - 바닥 확인: MA20 2일 회복, 높아진 저점, MACD 양전환,
               RSI 45 상회, OBV 개선
  - 상승추세: 정배열, MA20·MA60 기울기, 20일 고점 접근,
               상대강도, 외국인+기관 수급
  - 추세 훼손: MA20 이탈, MA60 이탈, 20일 저점 이탈

KRX 인증키는 코드에 넣지 않는다.
Streamlit Cloud → Settings → Secrets:

    KRX_AUTH_KEY = "발급받은 인증키"
    WATCHLIST = "005930,000660,005380,000270"

실행:
    streamlit run stock_bottom_trend_monitor.py
"""

import datetime as dt
import os
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import pandas as pd
import requests
import streamlit as st


# ──────────────────────────────────────────────────────────────
# 0. 설정
# ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="개별종목 바닥·상승추세 모니터",
    page_icon="📈",
    layout="wide",
)

KST = dt.timezone(dt.timedelta(hours=9))
TODAY = dt.datetime.now(KST).date()
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
KRX_API_BASE = "https://data-dbg.krx.co.kr/svc/apis"

STAGE_ICON = {
    "하락 진행": "🔴",
    "바닥 형성 관찰": "🟡",
    "바닥 확인": "🟢",
    "상승추세": "🔵",
    "추세 훼손": "⛔",
}

STAGE_RANK = {
    "추세 훼손": 0,
    "바닥 확인": 1,
    "바닥 형성 관찰": 2,
    "상승추세": 3,
    "하락 진행": 4,
}


def _secret(name: str, default: str = ""):
    env_value = os.getenv(name, "").strip()
    if env_value:
        return env_value
    try:
        return str(st.secrets.get(name, default)).strip()
    except Exception:
        return default


def fnum(value, default=np.nan):
    try:
        cleaned = str(value).replace(",", "").replace("%", "").strip()
        return float(cleaned)
    except (TypeError, ValueError):
        return default


def optional_number(value):
    parsed = fnum(value)
    return None if np.isnan(parsed) else parsed


def parse_codes(raw: str):
    codes = []
    for token in raw.replace("\n", ",").split(","):
        code = "".join(ch for ch in token.strip() if ch.isdigit())
        if len(code) == 6 and code not in codes:
            codes.append(code)
    return codes[:20]


# ──────────────────────────────────────────────────────────────
# 1. 데이터 수집
# ──────────────────────────────────────────────────────────────
@st.cache_data(ttl=300, show_spinner=False)
def search_stocks(query: str):
    """종목명 또는 6자리 코드로 KOSPI·KOSDAQ 보통주를 검색한다."""
    query = query.strip()
    if not query:
        return []
    r = requests.get(
        "https://m.stock.naver.com/front-api/search/autoComplete",
        params={
            "query": query,
            "target": "stock,index,marketindicator,coin,ipo",
        },
        headers=UA,
        timeout=12,
    )
    r.raise_for_status()
    items = r.json().get("result", {}).get("items", [])
    results = []
    for item in items:
        code = str(item.get("code", "")).strip()
        if (
            item.get("category") == "stock"
            and item.get("typeCode") in ("KOSPI", "KOSDAQ")
            and len(code) == 6
            and code.isdigit()
        ):
            results.append({
                "code": code,
                "name": item.get("name", code),
                "market": item.get("typeName", item.get("typeCode", "")),
            })
        if len(results) >= 10:
            break
    return results


@st.cache_data(ttl=30, show_spinner=False)
def fetch_basic(code: str):
    r = requests.get(
        f"https://m.stock.naver.com/api/stock/{code}/basic",
        headers=UA,
        timeout=12,
    )
    r.raise_for_status()
    d = r.json()
    if not d.get("stockName"):
        raise ValueError("종목 기본정보 없음")
    return {
        "code": code,
        "name": d.get("stockName", code),
        "price": optional_number(d.get("closePrice")),
        "change_pct": optional_number(d.get("fluctuationsRatio")),
        "traded_at": d.get("localTradedAt", ""),
        "market_status": d.get("marketStatus", ""),
        "exchange": d.get("stockExchangeName", ""),
        "sosok": str(d.get("sosok", "")),
    }


@st.cache_data(ttl=300, show_spinner=False)
def fetch_price_history(code: str):
    r = requests.get(
        f"https://api.stock.naver.com/chart/domestic/item/{code}",
        params={"periodType": "dayCandle", "count": 260},
        headers=UA,
        timeout=15,
    )
    r.raise_for_status()
    rows = r.json().get("priceInfos", [])
    if len(rows) < 80:
        raise ValueError(f"일봉 표본 부족 ({len(rows)}일)")

    df = pd.DataFrame(rows)
    df.index = pd.to_datetime(df["localDate"], format="%Y%m%d")
    df = df.rename(columns={
        "openPrice": "open",
        "highPrice": "high",
        "lowPrice": "low",
        "closePrice": "close",
        "accumulatedTradingVolume": "volume",
    })
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return (
        df[["open", "high", "low", "close", "volume"]]
        .dropna()
        .sort_index()
        .drop_duplicates()
    )


@st.cache_data(ttl=300, show_spinner=False)
def fetch_investor_trend(code: str):
    r = requests.get(
        f"https://m.stock.naver.com/api/stock/{code}/trend",
        headers=UA,
        timeout=12,
    )
    r.raise_for_status()
    rows = r.json()
    if not isinstance(rows, list) or not rows:
        return pd.DataFrame(columns=["foreign", "institution", "individual"])

    parsed = []
    for row in rows:
        try:
            parsed.append({
                "date": pd.to_datetime(row["bizdate"], format="%Y%m%d"),
                "foreign": fnum(row.get("foreignerPureBuyQuant"), 0),
                "institution": fnum(row.get("organPureBuyQuant"), 0),
                "individual": fnum(row.get("individualPureBuyQuant"), 0),
            })
        except (KeyError, TypeError, ValueError):
            continue
    if not parsed:
        return pd.DataFrame(columns=["foreign", "institution", "individual"])
    return (
        pd.DataFrame(parsed)
        .drop_duplicates("date")
        .set_index("date")
        .sort_index()
    )


@st.cache_data(ttl=300, show_spinner=False)
def fetch_kospi_history():
    r = requests.get(
        "https://api.stock.naver.com/chart/domestic/index/KOSPI",
        params={"periodType": "dayCandle"},
        headers=UA,
        timeout=15,
    )
    r.raise_for_status()
    rows = r.json().get("priceInfos", [])
    df = pd.DataFrame(rows)
    if df.empty:
        raise ValueError("KOSPI 일봉 없음")
    df.index = pd.to_datetime(df["localDate"], format="%Y%m%d")
    df["close"] = pd.to_numeric(df["closePrice"], errors="coerce")
    return df[["close"]].dropna().sort_index()


def fetch_bundle(code: str):
    """한 종목의 기본정보·일봉·수급을 묶는다."""
    basic = fetch_basic(code)
    history = fetch_price_history(code)
    try:
        investor = fetch_investor_trend(code)
    except Exception:
        investor = pd.DataFrame(columns=["foreign", "institution", "individual"])
    return basic, history, investor


class KRXAPIError(RuntimeError):
    pass


def _krx_rows(auth_key: str, endpoint: str, base_date: dt.date):
    r = requests.get(
        f"{KRX_API_BASE}/{endpoint}",
        params={"basDd": base_date.strftime("%Y%m%d")},
        headers={"AUTH_KEY": auth_key.strip(), "Accept": "application/json"},
        timeout=20,
    )
    if r.status_code == 401:
        raise KRXAPIError("401 권한 없음")
    if r.status_code == 429:
        raise KRXAPIError("429 호출 한도 초과")
    r.raise_for_status()
    payload = r.json()
    rows = payload.get("OutBlock_1", [])
    return rows if isinstance(rows, list) else []


def _krx_stock_row(rows, code: str):
    for row in rows:
        raw_code = str(row.get("ISU_SRT_CD") or row.get("ISU_CD") or "")
        digits = "".join(ch for ch in raw_code if ch.isdigit())
        if digits == code or digits.endswith(code) or code in digits:
            return row
    return None


def _previous_weekdays(count=10):
    dates, cursor = [], TODAY
    while len(dates) < count:
        if cursor.weekday() < 5:
            dates.append(cursor)
        cursor -= dt.timedelta(days=1)
    return dates


@st.cache_data(ttl=21600, show_spinner=False)
def fetch_krx_confirmation(auth_key: str, code: str, sosok: str):
    if not auth_key:
        return {"status": "인증키 미설정"}

    preferred = (
        ["sto/stk_bydd_trd", "sto/ksq_bydd_trd"]
        if sosok == "0"
        else ["sto/ksq_bydd_trd", "sto/stk_bydd_trd"]
    )
    errors = []
    for endpoint in preferred:
        for base_date in _previous_weekdays(8):
            try:
                row = _krx_stock_row(_krx_rows(auth_key, endpoint, base_date), code)
                if row:
                    return {
                        "status": "정상",
                        "date": base_date,
                        "close": optional_number(row.get("TDD_CLSPRC")),
                        "change_pct": optional_number(row.get("FLUC_RT")),
                        "value": optional_number(row.get("ACC_TRDVAL")),
                        "market_cap": optional_number(row.get("MKTCAP")),
                    }
            except KRXAPIError as exc:
                errors.append(str(exc))
                break
            except Exception as exc:
                errors.append(type(exc).__name__)
                break
    return {"status": " / ".join(dict.fromkeys(errors)) or "최근 확정치 없음"}


# ──────────────────────────────────────────────────────────────
# 2. 지표·상태 판정
# ──────────────────────────────────────────────────────────────
def add_indicators(df: pd.DataFrame):
    out = df.copy()
    out["return"] = out["close"].pct_change()
    for window in (5, 20, 60):
        out[f"ma{window}"] = out["close"].rolling(window).mean()

    delta = out["close"].diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    out["rsi14"] = 100 - 100 / (1 + rs)

    ema12 = out["close"].ewm(span=12, adjust=False).mean()
    ema26 = out["close"].ewm(span=26, adjust=False).mean()
    out["macd"] = ema12 - ema26
    out["macd_signal"] = out["macd"].ewm(span=9, adjust=False).mean()
    out["macd_hist"] = out["macd"] - out["macd_signal"]

    previous_close = out["close"].shift(1)
    true_range = pd.concat([
        out["high"] - out["low"],
        (out["high"] - previous_close).abs(),
        (out["low"] - previous_close).abs(),
    ], axis=1).max(axis=1)
    out["atr14"] = true_range.rolling(14).mean()

    direction = np.sign(out["close"].diff()).fillna(0)
    out["obv"] = (direction * out["volume"]).cumsum()
    return out


def relative_strength(stock: pd.DataFrame, kospi: pd.DataFrame, window: int):
    aligned = pd.concat(
        [stock["close"].rename("stock"), kospi["close"].rename("kospi")],
        axis=1,
        join="inner",
    ).dropna()
    if len(aligned) <= window:
        return np.nan
    stock_return = aligned["stock"].iloc[-1] / aligned["stock"].iloc[-window - 1] - 1
    kospi_return = aligned["kospi"].iloc[-1] / aligned["kospi"].iloc[-window - 1] - 1
    return (stock_return - kospi_return) * 100


def _signal(label, passed, detail):
    return {"label": label, "passed": bool(passed), "detail": detail}


def evaluate_stock(
    basic: dict,
    raw_history: pd.DataFrame,
    investor: pd.DataFrame,
    kospi: pd.DataFrame,
):
    df = add_indicators(raw_history)
    if len(df) < 80:
        raise ValueError("기술지표 계산 표본 부족")

    last = df.iloc[-1]
    close = float(last["close"])
    rsi = float(last["rsi14"])
    rs10 = relative_strength(df, kospi, 10)
    rs20 = relative_strength(df, kospi, 20)

    recent60 = df.tail(60)
    low60_date = recent60["low"].idxmin()
    days_since_low = len(df.loc[low60_date:]) - 1
    no_new_low = days_since_low >= 3

    rsi_rebound = (
        (rsi >= 35 and rsi <= 60 and rsi > df["rsi14"].iloc[-4])
        or ((df["rsi14"].tail(10).min() < 30) and rsi > 30)
    )
    ma5_recovery = close > last["ma5"] and last["ma5"] > df["ma5"].iloc[-4]

    down_volume_recent = df.loc[df["return"] < 0, "volume"].tail(5).mean()
    down_volume_prior = df.loc[df["return"] < 0, "volume"].iloc[-25:-5].mean()
    volume_exhaustion = (
        pd.notna(down_volume_recent)
        and pd.notna(down_volume_prior)
        and down_volume_recent < down_volume_prior * 0.85
    )
    avg20_volume = df["volume"].rolling(20).mean()
    reversal_position = (
        (df["close"] - df["low"])
        / (df["high"] - df["low"]).replace(0, np.nan)
    )
    capitulation_reversal = bool(
        ((df["volume"] > avg20_volume * 1.8) & (reversal_position > 0.65))
        .tail(10)
        .fillna(False)
        .any()
    )
    volume_signal = volume_exhaustion or capitulation_reversal

    flow_available = not investor.empty
    if flow_available:
        smart_flow = investor["foreign"] + investor["institution"]
        flow5 = float(smart_flow.tail(5).sum())
        flow10 = float(smart_flow.tail(10).sum())
    else:
        flow5 = np.nan
        flow10 = np.nan
    flow5_positive = flow_available and flow5 > 0

    formation = [
        _signal(
            "신저가 중단",
            no_new_low,
            f"60일 저점 이후 {days_since_low}거래일",
        ),
        _signal(
            "RSI 과매도 반등",
            rsi_rebound,
            f"RSI14 {rsi:.1f}",
        ),
        _signal(
            "5일선 회복",
            ma5_recovery,
            f"종가 {close:,.0f} / MA5 {last['ma5']:,.0f}",
        ),
        _signal(
            "매도 거래량 소진·투매반전",
            volume_signal,
            "최근 하락 거래량 감소" if volume_exhaustion else
            "최근 10일 투매 후 종가회복" if capitulation_reversal else
            "거래량 소진 미확인",
        ),
        _signal(
            "외국인+기관 5일 수급",
            flow5_positive,
            f"{flow5:+,.0f}주" if flow_available else "수급 데이터 없음",
        ),
        _signal(
            "KOSPI 대비 10일 상대강도",
            pd.notna(rs10) and rs10 > 0,
            f"{rs10:+.2f}%p" if pd.notna(rs10) else "계산불가",
        ),
    ]

    above_ma20_two_days = bool((df["close"].tail(2) > df["ma20"].tail(2)).all())
    recent_low = df["low"].iloc[-10:].min()
    prior_low = df["low"].iloc[-20:-10].min()
    higher_low = pd.notna(prior_low) and recent_low > prior_low
    macd_positive = last["macd_hist"] > 0
    rsi_confirmed = rsi > 45
    obv_improving = last["obv"] > df["obv"].iloc[-6]

    confirmation = [
        _signal(
            "MA20 2일 연속 회복",
            above_ma20_two_days,
            f"종가 {close:,.0f} / MA20 {last['ma20']:,.0f}",
        ),
        _signal(
            "높아진 저점",
            higher_low,
            f"직전10일 저점 {prior_low:,.0f} → 최근10일 {recent_low:,.0f}",
        ),
        _signal(
            "MACD 모멘텀 양전환",
            macd_positive,
            f"히스토그램 {last['macd_hist']:+,.2f}",
        ),
        _signal("RSI 45 상회", rsi_confirmed, f"RSI14 {rsi:.1f}"),
        _signal(
            "OBV 5일 개선",
            obv_improving,
            f"5일 변화 {(last['obv'] - df['obv'].iloc[-6]):+,.0f}",
        ),
    ]

    ordered = close > last["ma20"] > last["ma60"]
    slopes_up = (
        last["ma20"] > df["ma20"].iloc[-6]
        and last["ma60"] >= df["ma60"].iloc[-11]
    )
    prior20_high = df["high"].iloc[-21:-1].max()
    near_high = close >= prior20_high * 0.95
    rs20_positive = pd.notna(rs20) and rs20 > 0
    flow10_positive = flow_available and flow10 > 0

    uptrend = [
        _signal(
            "종가 > MA20 > MA60",
            ordered,
            f"{close:,.0f} > {last['ma20']:,.0f} > {last['ma60']:,.0f}",
        ),
        _signal(
            "중기선 기울기 상승",
            slopes_up,
            f"MA20 5일 {(last['ma20'] / df['ma20'].iloc[-6] - 1)*100:+.2f}% / "
            f"MA60 10일 {(last['ma60'] / df['ma60'].iloc[-11] - 1)*100:+.2f}%",
        ),
        _signal(
            "20일 고점 접근·돌파",
            near_high,
            f"종가 {close:,.0f} / 직전20일 고점 {prior20_high:,.0f}",
        ),
        _signal(
            "KOSPI 대비 20일 상대강도",
            rs20_positive,
            f"{rs20:+.2f}%p" if pd.notna(rs20) else "계산불가",
        ),
        _signal(
            "외국인+기관 10일 수급",
            flow10_positive,
            f"{flow10:+,.0f}주" if flow_available else "수급 데이터 없음",
        ),
    ]

    below_ma20_two_days = bool((df["close"].tail(2) < df["ma20"].tail(2)).all())
    ma20_falling = last["ma20"] < df["ma20"].iloc[-6]
    below_ma60 = close < last["ma60"]
    prior20_low = df["low"].iloc[-21:-1].min()
    broke_20d_low = close < prior20_low
    breakdown = [
        _signal(
            "MA20 2일 이탈+기울기 하락",
            below_ma20_two_days and ma20_falling,
            f"종가 {close:,.0f} / MA20 {last['ma20']:,.0f}",
        ),
        _signal(
            "MA60 이탈",
            below_ma60,
            f"종가 {close:,.0f} / MA60 {last['ma60']:,.0f}",
        ),
        _signal(
            "직전 20일 저점 이탈",
            broke_20d_low,
            f"종가 {close:,.0f} / 직전20일 저점 {prior20_low:,.0f}",
        ),
    ]

    formation_score = sum(x["passed"] for x in formation)
    confirmation_score = sum(x["passed"] for x in confirmation)
    uptrend_score = sum(x["passed"] for x in uptrend)
    breakdown_score = sum(x["passed"] for x in breakdown)

    historical_uptrend = (
        (df["close"] > df["ma20"])
        & (df["ma20"] > df["ma60"])
        & (df["ma20"] > df["ma20"].shift(5))
    ).tail(20).fillna(False).any()

    if historical_uptrend and breakdown_score >= 2:
        stage = "추세 훼손"
        action = "기존 상승추세가 훼손됨. 신규진입보다 위험 재평가 우선"
    elif uptrend_score >= 3 and close > last["ma20"]:
        stage = "상승추세"
        action = "추세 유지 여부 관찰. 과열이면 추격 금지"
    elif confirmation_score >= 3 and above_ma20_two_days:
        stage = "바닥 확인"
        action = "바닥 후보가 가격으로 확인되는 단계. 종가 기준 재확인"
    elif formation_score >= 3:
        stage = "바닥 형성 관찰"
        action = "아직 바닥 확정 아님. MA20 회복과 높아진 저점 대기"
    else:
        stage = "하락 진행"
        action = "저점 예측 금지. 신저가 중단 신호부터 대기"

    overheat_reasons = []
    if rsi > 75:
        overheat_reasons.append(f"RSI {rsi:.1f}")
    if pd.notna(last["atr14"]) and close > last["ma20"] + 2 * last["atr14"]:
        overheat_reasons.append("MA20 대비 2ATR 초과")
    return5 = (close / df["close"].iloc[-6] - 1) * 100
    if return5 > 20:
        overheat_reasons.append(f"5일 +{return5:.1f}%")

    drawdown60 = (close / df["high"].tail(60).max() - 1) * 100
    result = {
        "basic": basic,
        "history": df,
        "investor": investor,
        "stage": stage,
        "action": action,
        "formation": formation,
        "confirmation": confirmation,
        "uptrend": uptrend,
        "breakdown": breakdown,
        "formation_score": formation_score,
        "confirmation_score": confirmation_score,
        "uptrend_score": uptrend_score,
        "breakdown_score": breakdown_score,
        "rsi": rsi,
        "rs20": rs20,
        "drawdown60": drawdown60,
        "overheat": overheat_reasons,
        "flow5": flow5,
        "flow10": flow10,
    }
    return result


# ──────────────────────────────────────────────────────────────
# 3. 화면
# ──────────────────────────────────────────────────────────────
st.title("📈 개별종목 바닥확인 → 상승추세 모니터")
st.caption(
    "종목별 하락 진행·바닥 형성·바닥 확인·상승추세·추세 훼손을 자동 분류합니다. "
    "상태 판정은 매수·매도 지시가 아닙니다."
)

default_watchlist = _secret(
    "WATCHLIST",
    "005930,000660,005380,000270,035420,035720",
)
krx_auth_key = _secret("KRX_AUTH_KEY")

query_watchlist = parse_codes(st.query_params.get("stocks", ""))
if "watchlist_codes" not in st.session_state:
    st.session_state["watchlist_codes"] = (
        query_watchlist or parse_codes(default_watchlist)
    )
if "stock_labels" not in st.session_state:
    st.session_state["stock_labels"] = {}


def sync_watchlist_url():
    current = st.session_state["watchlist_codes"]
    if current:
        st.query_params["stocks"] = ",".join(current)
    elif "stocks" in st.query_params:
        del st.query_params["stocks"]


with st.sidebar:
    st.header("🔎 종목 검색")
    search_query = st.text_input(
        "종목명 또는 종목코드",
        placeholder="예: 삼성전자, 하이닉스, 005930",
    )
    search_results = []
    if search_query.strip():
        try:
            search_results = search_stocks(search_query)
        except Exception as exc:
            st.warning(f"종목 검색 실패: {exc}")

    if search_results:
        result_map = {item["code"]: item for item in search_results}
        selected_search_code = st.selectbox(
            "검색 결과",
            list(result_map),
            format_func=lambda code: (
                f"{result_map[code]['name']} ({code}) · "
                f"{result_map[code]['market']}"
            ),
        )
        if st.button("➕ 감시목록에 추가", type="primary"):
            current = st.session_state["watchlist_codes"]
            if selected_search_code in current:
                st.info("이미 감시 중인 종목입니다.")
            elif len(current) >= 20:
                st.warning("감시종목은 최대 20개입니다.")
            else:
                current.append(selected_search_code)
                selected_item = result_map[selected_search_code]
                st.session_state["stock_labels"][selected_search_code] = (
                    selected_item["name"]
                )
                sync_watchlist_url()
                st.rerun()
    elif search_query.strip():
        st.info("KOSPI·KOSDAQ 종목 검색 결과가 없습니다.")

    st.divider()
    st.subheader("현재 감시목록")
    current_codes = st.session_state["watchlist_codes"]
    if current_codes:
        remove_codes = st.multiselect(
            "삭제할 종목 선택",
            current_codes,
            format_func=lambda code: (
                f"{st.session_state['stock_labels'].get(code, code)} ({code})"
                if code in st.session_state["stock_labels"]
                else code
            ),
        )
        if st.button("🗑️ 선택 종목 삭제", disabled=not remove_codes):
            st.session_state["watchlist_codes"] = [
                code for code in current_codes if code not in remove_codes
            ]
            sync_watchlist_url()
            st.rerun()
        st.caption(f"{len(current_codes)}개 / 최대 20개")
    else:
        st.info("검색 후 종목을 추가하세요.")

    st.divider()
    if krx_auth_key:
        st.success("KRX Open API 인증키 설정됨")
    else:
        st.info("KRX 키 미설정 · 네이버 자동수집만 사용")
    if st.button("🔄 데이터 새로고침"):
        st.cache_data.clear()
        st.rerun()
    st.caption("장중 60초 자동 갱신")

try:
    from streamlit_autorefresh import st_autorefresh
    st_autorefresh(interval=60_000, key="stock-monitor-refresh")
except Exception:
    pass

codes = list(st.session_state["watchlist_codes"])
if not codes:
    st.info("왼쪽 검색창에서 감시할 종목을 추가하세요.")
    st.stop()

try:
    kospi_history = fetch_kospi_history()
except Exception as exc:
    st.error(f"KOSPI 상대강도 기준 데이터 수집 실패: {exc}")
    st.stop()

analyses, failures = {}, {}
with st.spinner(f"{len(codes)}개 종목 자동 분석..."):
    with ThreadPoolExecutor(max_workers=min(8, len(codes))) as pool:
        future_map = {pool.submit(fetch_bundle, code): code for code in codes}
        for future in as_completed(future_map):
            code = future_map[future]
            try:
                basic, history, investor = future.result()
                analyses[code] = evaluate_stock(
                    basic, history, investor, kospi_history
                )
            except Exception as exc:
                failures[code] = str(exc)

if failures:
    st.warning(
        "분석 제외: "
        + " / ".join(f"{code}({message})" for code, message in failures.items())
    )
if not analyses:
    st.error("분석 가능한 종목이 없습니다.")
    st.stop()

summary_rows = []
for code, result in analyses.items():
    basic = result["basic"]
    st.session_state["stock_labels"][code] = basic["name"]
    summary_rows.append({
        "우선순위": STAGE_RANK[result["stage"]],
        "종목": basic["name"],
        "코드": code,
        "단계": f"{STAGE_ICON[result['stage']]} {result['stage']}",
        "현재가": basic["price"],
        "등락률(%)": basic["change_pct"],
        "바닥형성": f"{result['formation_score']}/6",
        "바닥확인": f"{result['confirmation_score']}/5",
        "상승추세": f"{result['uptrend_score']}/5",
        "RSI14": result["rsi"],
        "KOSPI대비20일(%p)": result["rs20"],
        "60일고점대비(%)": result["drawdown60"],
        "과열": " / ".join(result["overheat"]) or "없음",
    })

summary = (
    pd.DataFrame(summary_rows)
    .sort_values(["우선순위", "바닥확인", "바닥형성"])
    .drop(columns="우선순위")
)

st.subheader("전체 감시판")
st.dataframe(
    summary,
    width="stretch",
    hide_index=True,
    column_config={
        "현재가": st.column_config.NumberColumn(format="%,.0f"),
        "등락률(%)": st.column_config.NumberColumn(format="%+.2f"),
        "RSI14": st.column_config.NumberColumn(format="%.1f"),
        "KOSPI대비20일(%p)": st.column_config.NumberColumn(format="%+.2f"),
        "60일고점대비(%)": st.column_config.NumberColumn(format="%+.2f"),
    },
)

options = list(analyses)
selected_code = st.selectbox(
    "상세 분석 종목",
    options,
    format_func=lambda code: f"{analyses[code]['basic']['name']} ({code})",
)
selected = analyses[selected_code]
basic = selected["basic"]
history = selected["history"]

st.divider()
st.subheader(
    f"{STAGE_ICON[selected['stage']]} {basic['name']} ({selected_code}) · "
    f"{selected['stage']}"
)

m1, m2, m3, m4, m5 = st.columns(5)
m1.metric(
    "현재가",
    f"{basic['price']:,.0f}" if basic["price"] is not None else "—",
    f"{basic['change_pct']:+.2f}%" if basic["change_pct"] is not None else None,
)
m2.metric("바닥 형성", f"{selected['formation_score']}/6")
m3.metric("바닥 확인", f"{selected['confirmation_score']}/5")
m4.metric("상승추세", f"{selected['uptrend_score']}/5")
m5.metric(
    "KOSPI 대비 20일",
    f"{selected['rs20']:+.2f}%p" if pd.notna(selected["rs20"]) else "—",
)
st.info(selected["action"])
if selected["overheat"]:
    st.warning("과열·추격주의: " + " / ".join(selected["overheat"]))


def show_signal_group(title, items, danger=False):
    st.markdown(f"#### {title}")
    for item in items:
        if danger:
            icon = "⛔" if item["passed"] else "✅"
        else:
            icon = "✅" if item["passed"] else "❌"
        st.markdown(f"{icon} **{item['label']}** — {item['detail']}")


g1, g2, g3, g4 = st.columns(4)
with g1:
    show_signal_group("1단계 · 바닥 형성", selected["formation"])
with g2:
    show_signal_group("2단계 · 바닥 확인", selected["confirmation"])
with g3:
    show_signal_group("3단계 · 상승추세", selected["uptrend"])
with g4:
    show_signal_group("무효화 · 추세 훼손", selected["breakdown"], danger=True)

st.divider()
chart_data = history[["close", "ma5", "ma20", "ma60"]].tail(100).rename(
    columns={"close": "종가", "ma5": "MA5", "ma20": "MA20", "ma60": "MA60"}
)
st.line_chart(chart_data, height=420)

c1, c2 = st.columns(2)
with c1:
    st.markdown("#### 거래량")
    volume_chart = history[["volume"]].tail(60).rename(columns={"volume": "거래량"})
    st.bar_chart(volume_chart, height=220)
with c2:
    st.markdown("#### RSI14")
    rsi_chart = history[["rsi14"]].tail(100).rename(columns={"rsi14": "RSI14"})
    st.line_chart(rsi_chart, height=220)

if not selected["investor"].empty:
    st.markdown("#### 외국인·기관 순매수 수량")
    flow_chart = selected["investor"][["foreign", "institution"]].rename(
        columns={"foreign": "외국인", "institution": "기관"}
    )
    st.bar_chart(flow_chart, height=220)
else:
    st.info("이 종목은 투자자별 수급 공개 응답이 없어 가격·거래량으로만 판정했습니다.")

krx = fetch_krx_confirmation(krx_auth_key, selected_code, basic["sosok"])
if krx.get("status") == "정상":
    st.success(
        f"KRX 공식 확정치 대조 정상 · {krx['date']} 종가 "
        f"{krx['close']:,.0f}원 / 등락률 {krx['change_pct']:+.2f}%"
    )
else:
    st.caption(f"KRX 공식 확정치: {krx.get('status', '확인불가')}")

st.caption(
    f"장중 기준시각: {basic['traded_at'] or '확인불가'} · "
    "네이버 장중/일봉·투자자 수급과 KRX 확정 일별 통계정보를 대조·가공했습니다."
)
st.caption(
    "⚠️ 바닥과 추세는 사후적으로만 확정됩니다. 이 도구는 확률적 상태 모니터이며 "
    "투자 권유·자동매매 신호가 아닙니다. 종가 확정 전 장중 상태는 바뀔 수 있습니다."
)
