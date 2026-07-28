# -*- coding: utf-8 -*-
"""
개별종목 바닥확인 → 상승추세·매수구간 모니터 v2.0
========================================

국내 개별종목을 다음 5단계로 자동 분류한다.

  1) 하락 진행
  2) 바닥 형성 관찰
  3) 바닥 확인
  4) 상승추세
  5) 추세 훼손

판정 축:
  - 바닥 형성: 신저가 중단, RSI 반등, 단기선 회복, 거래량 소진,
               외국인·기관 수급, 시장 대비 상대강도
  - 바닥 확인: MA20 2일 회복, 높아진 저점, MACD 양전환,
               RSI 45 상회, OBV 개선
  - 상승추세: 정배열, MA20·MA60 기울기, 20일 고점 접근,
               상대강도, 외국인·기관 수급
  - 추세 훼손: MA20 이탈, MA60 이탈, 20일 저점 이탈
  - 매수 판단: 눌림목 구간, 돌파 확인가격, 추격 위험, 진입취소선
  - 수급 판단: 외국인·기관 매수/매도 줄다리기, KRX 공매도 거래·잔고

KRX 인증키는 코드에 넣지 않는다.
Streamlit Cloud → Settings → Secrets:

    KRX_AUTH_KEY = "발급받은 인증키"
    WATCHLIST = "005930,000660,005380,000270"

실행:
    streamlit run stock_bottom_trend_monitor.py
"""

import datetime as dt
import math
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
KRX_DATA_URL = "https://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd"

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
def fetch_index_history(index_code: str):
    """KOSPI 또는 KOSDAQ 일봉을 가져온다."""
    index_code = index_code.upper()
    if index_code not in ("KOSPI", "KOSDAQ"):
        raise ValueError("지원하지 않는 시장지수")
    r = requests.get(
        f"https://api.stock.naver.com/chart/domestic/index/{index_code}",
        params={"periodType": "dayCandle"},
        headers=UA,
        timeout=15,
    )
    r.raise_for_status()
    rows = r.json().get("priceInfos", [])
    df = pd.DataFrame(rows)
    if df.empty:
        raise ValueError(f"{index_code} 일봉 없음")
    df.index = pd.to_datetime(df["localDate"], format="%Y%m%d")
    df["close"] = pd.to_numeric(df["closePrice"], errors="coerce")
    return df[["close"]].dropna().sort_index()


def _krx_numeric(value):
    if value in (None, "", "-", "–"):
        return np.nan
    return fnum(value)


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_short_selling(code: str, calendar_days: int = 70):
    """KRX 공매도 종합정보의 일별 거래량·공시 잔고를 가져온다."""
    headers = {
        **UA,
        "Referer": (
            "https://data.krx.co.kr/comm/srt/srtLoader/"
            f"index.cmd?screenId=MDCSTAT300&isuCd={code}"
        ),
    }
    finder = requests.get(
        KRX_DATA_URL,
        params={
            "bld": "dbms/comm/finder/get_srtisu",
            "isuCd": code,
            "locale": "ko_KR",
        },
        headers=headers,
        timeout=20,
    )
    finder.raise_for_status()
    matches = finder.json().get("output", [])
    if not matches:
        return pd.DataFrame()

    full_code = str(matches[0].get("code", "")).strip()
    if not full_code:
        return pd.DataFrame()

    start = TODAY - dt.timedelta(days=calendar_days)
    response = requests.post(
        KRX_DATA_URL,
        params={"bld": "dbms/MDC_OUT/STAT/srt/MDCSTAT30001_OUT"},
        data={
            "locale": "ko_KR",
            "isuCd": full_code,
            "strtDd": start.strftime("%Y%m%d"),
            "endDd": TODAY.strftime("%Y%m%d"),
            "share": "1",
            "money": "1",
        },
        headers=headers,
        timeout=25,
    )
    response.raise_for_status()
    rows = response.json().get("OutBlock_1", [])
    parsed = []
    for row in rows:
        try:
            parsed.append({
                "date": pd.to_datetime(row["TRD_DD"], format="%Y/%m/%d"),
                "short_volume": _krx_numeric(row.get("CVSRTSELL_TRDVOL")),
                "uptick_volume": _krx_numeric(row.get("UPTICKRULE_APPL_TRDVOL")),
                "exception_volume": _krx_numeric(
                    row.get("UPTICKRULE_EXCPT_TRDVOL")
                ),
                "short_balance": _krx_numeric(row.get("STR_CONST_VAL1")),
                "short_value": _krx_numeric(row.get("CVSRTSELL_TRDVAL")),
                "balance_value": _krx_numeric(row.get("STR_CONST_VAL2")),
            })
        except (KeyError, TypeError, ValueError):
            continue
    if not parsed:
        return pd.DataFrame()
    return (
        pd.DataFrame(parsed)
        .drop_duplicates("date")
        .set_index("date")
        .sort_index()
    )


def fetch_bundle(code: str):
    """한 종목의 기본정보·일봉·투자자 수급·공매도를 묶는다."""
    basic = fetch_basic(code)
    with ThreadPoolExecutor(max_workers=3) as pool:
        history_future = pool.submit(fetch_price_history, code)
        investor_future = pool.submit(fetch_investor_trend, code)
        short_future = pool.submit(fetch_short_selling, code)
        history = history_future.result()
        try:
            investor = investor_future.result()
        except Exception:
            investor = pd.DataFrame(
                columns=["foreign", "institution", "individual"]
            )
        try:
            short_selling = short_future.result()
        except Exception:
            short_selling = pd.DataFrame()
    return basic, history, investor, short_selling


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


def relative_strength(stock: pd.DataFrame, benchmark: pd.DataFrame, window: int):
    aligned = pd.concat(
        [
            stock["close"].rename("stock"),
            benchmark["close"].rename("benchmark"),
        ],
        axis=1,
        join="inner",
    ).dropna()
    if len(aligned) <= window:
        return np.nan
    stock_return = aligned["stock"].iloc[-1] / aligned["stock"].iloc[-window - 1] - 1
    benchmark_return = (
        aligned["benchmark"].iloc[-1]
        / aligned["benchmark"].iloc[-window - 1]
        - 1
    )
    return (stock_return - benchmark_return) * 100


def tick_size(price: float):
    """국내 주식 정규시장 가격대별 호가단위."""
    if price < 2_000:
        return 1
    if price < 5_000:
        return 5
    if price < 20_000:
        return 10
    if price < 50_000:
        return 50
    if price < 200_000:
        return 100
    if price < 500_000:
        return 500
    return 1_000


def round_to_tick(price: float, direction="nearest"):
    if pd.isna(price):
        return np.nan
    tick = tick_size(float(price))
    units = float(price) / tick
    if direction == "up":
        return float(math.ceil(units) * tick)
    if direction == "down":
        return float(math.floor(units) * tick)
    return float(math.floor(units + 0.5) * tick)


def _flow_momentum(series: pd.Series):
    clean = pd.to_numeric(series, errors="coerce").dropna()
    if len(clean) < 6:
        return "표본 부족"
    recent = float(clean.tail(3).sum())
    prior = float(clean.iloc[-6:-3].sum())
    if recent > 0 and prior <= 0:
        return "매수 전환"
    if recent >= 0 and recent > prior * 1.2:
        return "매수 확대"
    if recent < 0 and prior < 0 and abs(recent) <= abs(prior) * 0.75:
        return "매도 완화"
    if recent < 0 and prior >= 0:
        return "매도 전환"
    if recent < prior and recent < 0:
        return "매도 확대"
    return "유지"


def evaluate_investor_flow(investor: pd.DataFrame):
    if investor.empty:
        return {
            "available": False,
            "label": "데이터 없음",
            "score": 50,
            "foreign5": np.nan,
            "foreign10": np.nan,
            "institution5": np.nan,
            "institution10": np.nan,
            "combined5": np.nan,
            "combined10": np.nan,
            "foreign_momentum": "데이터 없음",
            "institution_momentum": "데이터 없음",
        }

    foreign5 = float(investor["foreign"].tail(5).sum())
    foreign10 = float(investor["foreign"].tail(10).sum())
    institution5 = float(investor["institution"].tail(5).sum())
    institution10 = float(investor["institution"].tail(10).sum())
    combined5 = foreign5 + institution5
    combined10 = foreign10 + institution10

    if foreign5 > 0 and institution5 > 0:
        label = "쌍끌이 매수"
    elif foreign5 > 0 and institution5 < 0:
        label = "외국인 매수·기관 매도"
    elif foreign5 < 0 and institution5 > 0:
        label = "기관 방어·외국인 매도"
    elif foreign5 < 0 and institution5 < 0:
        label = "동반 매도"
    else:
        label = "수급 중립"

    foreign_momentum = _flow_momentum(investor["foreign"])
    institution_momentum = _flow_momentum(investor["institution"])
    score = 50
    score += 15 if foreign5 > 0 else -15
    score += 15 if institution5 > 0 else -15
    score += 7 if foreign10 > 0 else -7
    score += 7 if institution10 > 0 else -7
    for momentum in (foreign_momentum, institution_momentum):
        if momentum in ("매수 전환", "매수 확대", "매도 완화"):
            score += 5
        elif momentum in ("매도 전환", "매도 확대"):
            score -= 5

    return {
        "available": True,
        "label": label,
        "score": int(np.clip(score, 0, 100)),
        "foreign5": foreign5,
        "foreign10": foreign10,
        "institution5": institution5,
        "institution10": institution10,
        "combined5": combined5,
        "combined10": combined10,
        "foreign_momentum": foreign_momentum,
        "institution_momentum": institution_momentum,
        "latest_date": investor.index.max(),
    }


def evaluate_short_pressure(
    short_selling: pd.DataFrame,
    raw_history: pd.DataFrame,
):
    empty_result = {
        "available": False,
        "label": "데이터 없음",
        "score": 50,
        "latest_ratio": np.nan,
        "avg5_ratio": np.nan,
        "previous5_ratio": np.nan,
        "balance": np.nan,
        "balance_change_pct": np.nan,
        "latest_trade_date": None,
        "latest_balance_date": None,
        "series": pd.DataFrame(),
    }
    if short_selling.empty or "short_volume" not in short_selling:
        return empty_result

    series = short_selling.copy()
    series = series.join(
        raw_history[["volume"]].rename(columns={"volume": "total_volume"}),
        how="left",
    )
    series["short_ratio"] = (
        series["short_volume"] / series["total_volume"].replace(0, np.nan) * 100
    )
    ratio_series = series["short_ratio"].dropna()
    balances = series["short_balance"].dropna()
    if ratio_series.empty and balances.empty:
        return empty_result

    avg5 = float(ratio_series.tail(5).mean()) if not ratio_series.empty else np.nan
    previous5 = (
        float(ratio_series.iloc[-10:-5].mean())
        if len(ratio_series) >= 10
        else np.nan
    )
    latest_ratio = (
        float(ratio_series.iloc[-1]) if not ratio_series.empty else np.nan
    )
    latest_balance = float(balances.iloc[-1]) if not balances.empty else np.nan
    reference_balance = (
        float(balances.tail(10).iloc[0]) if len(balances) >= 2 else np.nan
    )
    balance_change_pct = (
        (latest_balance / reference_balance - 1) * 100
        if pd.notna(reference_balance) and reference_balance > 0
        else np.nan
    )

    if (
        (pd.notna(balance_change_pct) and balance_change_pct > 10)
        or (
            pd.notna(avg5)
            and avg5 >= 15
            and pd.notna(balance_change_pct)
            and balance_change_pct > 5
        )
    ):
        label = "악화"
    elif (
        (pd.notna(avg5) and avg5 >= 10)
        or (pd.notna(balance_change_pct) and balance_change_pct > 3)
    ):
        label = "경계"
    elif (
        pd.notna(avg5)
        and pd.notna(previous5)
        and avg5 <= previous5 * 0.8
        and (pd.isna(balance_change_pct) or balance_change_pct <= 0)
    ):
        label = "완화"
    else:
        label = "중립"

    score = 70
    if pd.notna(avg5):
        if avg5 < 5:
            score += 15
        elif avg5 < 10:
            score += 5
        elif avg5 < 15:
            score -= 15
        else:
            score -= 30
    if pd.notna(previous5) and pd.notna(avg5):
        if avg5 <= previous5 * 0.8:
            score += 10
        elif avg5 >= previous5 * 1.2:
            score -= 10
    if pd.notna(balance_change_pct):
        if balance_change_pct > 10:
            score -= 25
        elif balance_change_pct > 3:
            score -= 10
        elif balance_change_pct <= -5:
            score += 10

    return {
        "available": True,
        "label": label,
        "score": int(np.clip(score, 0, 100)),
        "latest_ratio": latest_ratio,
        "avg5_ratio": avg5,
        "previous5_ratio": previous5,
        "balance": latest_balance,
        "balance_change_pct": balance_change_pct,
        "latest_trade_date": (
            ratio_series.index[-1] if not ratio_series.empty else None
        ),
        "latest_balance_date": (
            balances.index[-1] if not balances.empty else None
        ),
        "series": series,
    }


def build_entry_plan(
    stage: str,
    df: pd.DataFrame,
    flow: dict,
    short_pressure: dict,
):
    """추세 상태와 가격·수급·공매도를 합쳐 조건부 매수계획을 만든다."""
    last = df.iloc[-1]
    close = float(last["close"])
    ma5 = float(last["ma5"])
    ma20 = float(last["ma20"])
    atr = float(last["atr14"]) if pd.notna(last["atr14"]) else close * 0.03
    rsi = float(last["rsi14"])
    prior20_high = float(df["high"].iloc[-21:-1].max())
    breakout_trigger = round_to_tick(
        prior20_high + tick_size(prior20_high),
        "up",
    )

    pullback_low_raw = max(ma20, ma5 - atr * 0.10)
    pullback_high_raw = min(close, ma5 + atr * 0.30)
    pullback_low = round_to_tick(pullback_low_raw)
    pullback_high = round_to_tick(max(pullback_low_raw, pullback_high_raw))
    entry_cancel = round_to_tick(
        pullback_low - tick_size(pullback_low),
        "down",
    )
    trend_invalidation = round_to_tick(ma20)

    avg20_volume = float(df["volume"].tail(20).mean())
    volume_ratio = (
        float(last["volume"]) / avg20_volume if avg20_volume > 0 else np.nan
    )
    day_range = float(last["high"] - last["low"])
    close_location = (
        float((close - last["low"]) / day_range) if day_range > 0 else 0.5
    )
    return5 = (
        (close / float(df["close"].iloc[-6]) - 1) * 100
        if len(df) >= 6
        else np.nan
    )
    distance_ma20 = (close / ma20 - 1) * 100
    flow_safe = flow["label"] != "동반 매도"
    short_safe = short_pressure["label"] != "악화"

    breakout_confirmed = bool(
        close >= breakout_trigger
        and close_location >= 0.65
        and volume_ratio >= 1.30
        and rsi <= 72
        and flow_safe
        and short_safe
    )
    quiet_or_reversal = bool(
        volume_ratio <= 1.20
        or (
            close > float(last["open"])
            and close_location >= 0.60
            and volume_ratio <= 1.60
        )
    )
    in_pullback_band = pullback_low <= close <= pullback_high
    pullback_ready = bool(
        stage in ("바닥 확인", "상승추세")
        and in_pullback_band
        and close > ma20
        and 42 <= rsi <= 68
        and quiet_or_reversal
        and flow_safe
        and short_safe
    )
    extended = bool(
        distance_ma20 > 10
        or (pd.notna(return5) and return5 > 15)
        or rsi > 72
        or close > ma20 + atr * 1.50
    )

    trend_component = {
        "상승추세": 25,
        "바닥 확인": 20,
        "바닥 형성 관찰": 10,
        "하락 진행": 2,
        "추세 훼손": 0,
    }[stage]
    if breakout_confirmed or pullback_ready:
        price_component = 25
    elif in_pullback_band:
        price_component = 18
    elif extended:
        price_component = 5
    else:
        price_component = 12
    if breakout_confirmed:
        volume_component = 15
    elif pullback_ready:
        volume_component = 13
    elif pd.notna(volume_ratio) and volume_ratio <= 1.50:
        volume_component = 9
    else:
        volume_component = 5
    flow_component = int(round(flow["score"] * 0.20))
    short_component = int(round(short_pressure["score"] * 0.15))
    score = int(np.clip(
        trend_component
        + price_component
        + volume_component
        + flow_component
        + short_component,
        0,
        100,
    ))

    if stage in ("하락 진행", "추세 훼손"):
        status = "⛔ 신규매수 금지"
        reason = "가격 추세가 아직 하락 중이거나 기존 상승추세가 훼손됐습니다."
    elif flow["label"] == "동반 매도" and short_pressure["label"] == "악화":
        status = "⛔ 신규매수 금지"
        reason = "외국인·기관 동반 매도와 공매도 압력 악화가 겹쳤습니다."
    elif breakout_confirmed and score >= 70:
        status = "🟢 돌파 매수 검토"
        reason = "직전 20일 고점을 종가·거래량·수급으로 확인했습니다."
    elif pullback_ready and score >= 65:
        status = "🟢 눌림목 매수 검토"
        reason = "상승추세 안에서 과열을 식힌 눌림 구간이 확인됐습니다."
    elif in_pullback_band and score >= 55:
        status = "🟡 소액 탐색"
        reason = "가격은 눌림 구간이지만 수급·거래량 확인이 한 단계 부족합니다."
    elif extended and not breakout_confirmed:
        status = "🔴 추격 금지"
        reason = "상승추세와 별개로 현재가는 눌림 구간 위이고 돌파 종가확인이 없습니다."
    else:
        status = "🟡 진입 대기"
        reason = "눌림목 또는 거래량 동반 돌파 중 하나가 확인될 때까지 기다립니다."

    return {
        "status": status,
        "score": score,
        "reason": reason,
        "pullback_low": pullback_low,
        "pullback_high": pullback_high,
        "breakout_trigger": breakout_trigger,
        "entry_cancel": entry_cancel,
        "trend_invalidation": trend_invalidation,
        "prior20_high": prior20_high,
        "volume_ratio": volume_ratio,
        "close_location": close_location,
        "return5": return5,
        "distance_ma20": distance_ma20,
        "breakout_confirmed": breakout_confirmed,
        "pullback_ready": pullback_ready,
        "extended": extended,
        "components": {
            "추세": trend_component,
            "가격위치": price_component,
            "거래량": volume_component,
            "외국인·기관": flow_component,
            "공매도": short_component,
        },
        "buy_condition": (
            f"눌림목 {pullback_low:,.0f}~{pullback_high:,.0f}원에서 "
            "거래량 감소 후 양봉 전환, 또는 "
            f"{breakout_trigger:,.0f}원 이상 종가+거래량 1.3배"
        ),
        "cancel_condition": (
            f"눌림 진입 후 {entry_cancel:,.0f}원 종가 이탈 시 진입가설 재검토. "
            f"MA20 부근 {trend_invalidation:,.0f}원 2일 이탈 시 추세 재판정"
        ),
    }


def _signal(label, passed, detail):
    return {"label": label, "passed": bool(passed), "detail": detail}


def evaluate_stock(
    basic: dict,
    raw_history: pd.DataFrame,
    investor: pd.DataFrame,
    short_selling: pd.DataFrame,
    benchmark: pd.DataFrame,
    benchmark_name: str,
):
    df = add_indicators(raw_history)
    if len(df) < 80:
        raise ValueError("기술지표 계산 표본 부족")

    last = df.iloc[-1]
    close = float(last["close"])
    rsi = float(last["rsi14"])
    rs10 = relative_strength(df, benchmark, 10)
    rs20 = relative_strength(df, benchmark, 20)

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

    flow = evaluate_investor_flow(investor)
    flow_available = flow["available"]
    flow5 = flow["combined5"]
    flow10 = flow["combined10"]
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
            "외국인·기관 5일 줄다리기",
            flow5_positive,
            (
                f"{flow['label']} / 합계 {flow5:+,.0f}주"
                if flow_available
                else "수급 데이터 없음"
            ),
        ),
        _signal(
            f"{benchmark_name} 대비 10일 상대강도",
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
            f"{benchmark_name} 대비 20일 상대강도",
            rs20_positive,
            f"{rs20:+.2f}%p" if pd.notna(rs20) else "계산불가",
        ),
        _signal(
            "외국인·기관 10일 수급",
            flow10_positive,
            (
                f"{flow['label']} / 합계 {flow10:+,.0f}주"
                if flow_available
                else "수급 데이터 없음"
            ),
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

    short_pressure = evaluate_short_pressure(short_selling, raw_history)
    entry = build_entry_plan(stage, df, flow, short_pressure)
    drawdown60 = (close / df["high"].tail(60).max() - 1) * 100
    result = {
        "basic": basic,
        "history": df,
        "investor": investor,
        "short_selling": short_selling,
        "stage": stage,
        "action": action,
        "benchmark_name": benchmark_name,
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
        "flow": flow,
        "short_pressure": short_pressure,
        "entry": entry,
    }
    return result


# ──────────────────────────────────────────────────────────────
# 3. 화면
# ──────────────────────────────────────────────────────────────
st.title("📈 개별종목 상승추세·매수구간 모니터")
st.caption(
    "바닥·상승추세뿐 아니라 눌림목 가격, 돌파 확인가격, 추격 위험, "
    "외국인·기관 줄다리기와 KRX 공매도 압력을 자동 판정합니다."
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
        st.success("KRX 종가 대조용 Open API 키 설정됨")
    else:
        st.info("KRX 종가 대조키 미설정 · 공매도 통계는 자동수집")
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
    with ThreadPoolExecutor(max_workers=2) as benchmark_pool:
        benchmark_futures = {
            name: benchmark_pool.submit(fetch_index_history, name)
            for name in ("KOSPI", "KOSDAQ")
        }
        market_history = {
            name: future.result()
            for name, future in benchmark_futures.items()
        }
except Exception as exc:
    st.error(f"시장 상대강도 기준 데이터 수집 실패: {exc}")
    st.stop()

analyses, failures = {}, {}
with st.spinner(f"{len(codes)}개 종목 자동 분석..."):
    with ThreadPoolExecutor(max_workers=min(8, len(codes))) as pool:
        future_map = {pool.submit(fetch_bundle, code): code for code in codes}
        for future in as_completed(future_map):
            code = future_map[future]
            try:
                basic, history, investor, short_selling = future.result()
                benchmark_name = "KOSPI" if basic["sosok"] == "0" else "KOSDAQ"
                analyses[code] = evaluate_stock(
                    basic,
                    history,
                    investor,
                    short_selling,
                    market_history[benchmark_name],
                    benchmark_name,
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
    entry = result["entry"]
    flow = result["flow"]
    short_pressure = result["short_pressure"]
    st.session_state["stock_labels"][code] = basic["name"]
    summary_rows.append({
        "우선순위": STAGE_RANK[result["stage"]],
        "종목": basic["name"],
        "코드": code,
        "단계": f"{STAGE_ICON[result['stage']]} {result['stage']}",
        "매수판정": entry["status"],
        "진입점수": entry["score"],
        "현재가": basic["price"],
        "등락률(%)": basic["change_pct"],
        "눌림목 가격": (
            f"{entry['pullback_low']:,.0f}~{entry['pullback_high']:,.0f}"
        ),
        "돌파가격": entry["breakout_trigger"],
        "진입취소선": entry["entry_cancel"],
        "수급 줄다리기": flow["label"],
        "공매도": short_pressure["label"],
        "RSI14": result["rsi"],
        "시장대비20일(%p)": result["rs20"],
    })

summary = (
    pd.DataFrame(summary_rows)
    .sort_values(
        ["진입점수", "우선순위"],
        ascending=[False, True],
    )
    .drop(columns="우선순위")
)

st.subheader("전체 감시판 · 매수 타이밍 우선")
st.dataframe(
    summary,
    width="stretch",
    hide_index=True,
    column_config={
        "현재가": st.column_config.NumberColumn(format="%,.0f"),
        "등락률(%)": st.column_config.NumberColumn(format="%+.2f"),
        "진입점수": st.column_config.ProgressColumn(
            min_value=0,
            max_value=100,
            format="%d",
        ),
        "돌파가격": st.column_config.NumberColumn(format="%,.0f"),
        "진입취소선": st.column_config.NumberColumn(format="%,.0f"),
        "RSI14": st.column_config.NumberColumn(format="%.1f"),
        "시장대비20일(%p)": st.column_config.NumberColumn(format="%+.2f"),
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
entry = selected["entry"]
flow = selected["flow"]
short_pressure = selected["short_pressure"]

st.divider()
st.subheader(
    f"{STAGE_ICON[selected['stage']]} {basic['name']} ({selected_code}) · "
    f"{selected['stage']}"
    f" · {entry['status']}"
)

m1, m2, m3, m4, m5, m6 = st.columns(6)
m1.metric(
    "현재가",
    f"{basic['price']:,.0f}" if basic["price"] is not None else "—",
    f"{basic['change_pct']:+.2f}%" if basic["change_pct"] is not None else None,
)
m2.metric("추세 단계", selected["stage"])
m3.metric("진입점수", f"{entry['score']}/100")
m4.metric("수급 줄다리기", flow["label"])
m5.metric("공매도 압력", short_pressure["label"])
m6.metric(
    f"{selected['benchmark_name']} 대비 20일",
    f"{selected['rs20']:+.2f}%p" if pd.notna(selected["rs20"]) else "—",
)

entry_message = f"{entry['status']} — {entry['reason']}"
if entry["status"].startswith("🟢"):
    st.success(entry_message)
else:
    st.warning(entry_message)

st.markdown("### 매수 타이밍·가격")
p1, p2, p3, p4, p5 = st.columns(5)
p1.metric(
    "분석 기준 종가",
    f"{history['close'].iloc[-1]:,.0f}원",
)
p2.metric(
    "눌림목 검토구간",
    f"{entry['pullback_low']:,.0f}~{entry['pullback_high']:,.0f}원",
)
p3.metric("돌파 확인가격", f"{entry['breakout_trigger']:,.0f}원")
p4.metric("눌림 진입취소선", f"{entry['entry_cancel']:,.0f}원")
p5.metric("MA20 추세선", f"{entry['trend_invalidation']:,.0f}원")

st.markdown(f"**매수 확인 조건:** {entry['buy_condition']}")
st.markdown(f"**취소·재판정 조건:** {entry['cancel_condition']}")
st.caption(
    "진입 가능 판정이어도 한 번에 전액 매수하지 않고 1차 20~30%만 탐색한 뒤, "
    "종가 확인과 수급 지속 여부에 따라 나눠 확인하는 기준입니다."
)

component_max = {
    "추세": 25,
    "가격위치": 25,
    "거래량": 15,
    "외국인·기관": 20,
    "공매도": 15,
}
component_row = {
    key: f"{value}/{component_max[key]}"
    for key, value in entry["components"].items()
}
st.dataframe(
    pd.DataFrame([component_row], index=["진입점수 구성"]),
    width="stretch",
)

st.info(selected["action"])
if selected["overheat"]:
    st.warning("과열·추격주의: " + " / ".join(selected["overheat"]))

st.markdown("### 외국인·기관 매수/매도 줄다리기")
if flow["available"]:
    flow_table = pd.DataFrame([
        {
            "주체": "외국인",
            "최근 5일(주)": flow["foreign5"],
            "최근 10일(주)": flow["foreign10"],
            "최근 변화": flow["foreign_momentum"],
        },
        {
            "주체": "기관",
            "최근 5일(주)": flow["institution5"],
            "최근 10일(주)": flow["institution10"],
            "최근 변화": flow["institution_momentum"],
        },
        {
            "주체": "합계",
            "최근 5일(주)": flow["combined5"],
            "최근 10일(주)": flow["combined10"],
            "최근 변화": _flow_momentum(
                selected["investor"]["foreign"]
                + selected["investor"]["institution"]
            ),
        },
    ])
    f1, f2 = st.columns([1, 2])
    with f1:
        st.metric("줄다리기 판정", flow["label"])
        st.metric("수급점수", f"{flow['score']}/100")
        st.caption(
            f"최근 반영일: {flow['latest_date'].strftime('%Y-%m-%d')}"
        )
    with f2:
        st.dataframe(
            flow_table,
            width="stretch",
            hide_index=True,
            column_config={
                "최근 5일(주)": st.column_config.NumberColumn(format="%+,.0f"),
                "최근 10일(주)": st.column_config.NumberColumn(format="%+,.0f"),
            },
        )
    flow_chart = selected["investor"][["foreign", "institution"]].tail(20).rename(
        columns={"foreign": "외국인", "institution": "기관"}
    )
    st.bar_chart(flow_chart, height=220)
else:
    st.info("투자자별 수급 응답이 없어 가격·거래량만으로 진입점수를 계산했습니다.")

st.markdown("### KRX 공매도 압력")
if short_pressure["available"]:
    s1, s2, s3, s4, s5 = st.columns(5)
    s1.metric("판정", short_pressure["label"])
    s2.metric(
        "최근 공매도 비중",
        (
            f"{short_pressure['latest_ratio']:.2f}%"
            if pd.notna(short_pressure["latest_ratio"])
            else "—"
        ),
    )
    s3.metric(
        "5일 평균 비중",
        (
            f"{short_pressure['avg5_ratio']:.2f}%"
            if pd.notna(short_pressure["avg5_ratio"])
            else "—"
        ),
    )
    s4.metric(
        "최근 공시잔고",
        (
            f"{short_pressure['balance']:,.0f}주"
            if pd.notna(short_pressure["balance"])
            else "—"
        ),
    )
    s5.metric(
        "잔고 변화",
        (
            f"{short_pressure['balance_change_pct']:+.1f}%"
            if pd.notna(short_pressure["balance_change_pct"])
            else "—"
        ),
    )

    short_series = short_pressure["series"]
    sc1, sc2 = st.columns(2)
    with sc1:
        ratio_chart = (
            short_series[["short_ratio"]]
            .dropna()
            .tail(30)
            .rename(columns={"short_ratio": "공매도 비중(%)"})
        )
        if not ratio_chart.empty:
            st.bar_chart(ratio_chart, height=220)
    with sc2:
        balance_chart = (
            short_series[["short_balance"]]
            .dropna()
            .tail(30)
            .rename(columns={"short_balance": "공시잔고(주)"})
        )
        if not balance_chart.empty:
            st.line_chart(balance_chart, height=220)

    trade_date = short_pressure["latest_trade_date"]
    balance_date = short_pressure["latest_balance_date"]
    st.caption(
        "공매도 거래 최근일 "
        f"{trade_date.strftime('%Y-%m-%d') if trade_date is not None else '—'} · "
        "잔고 공시 최근일 "
        f"{balance_date.strftime('%Y-%m-%d') if balance_date is not None else '—'} · "
        "KRX+NXT 전체 당일 거래는 통상 18:10 이후, 공매도 잔고는 T+2 지연 반영"
    )
else:
    st.info("KRX 공매도 통계 응답이 없어 공매도 항목은 중립값으로 계산했습니다.")

st.markdown("### 바닥·추세 세부 신호")


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
chart_data["눌림하단"] = entry["pullback_low"]
chart_data["눌림상단"] = entry["pullback_high"]
chart_data["돌파확인"] = entry["breakout_trigger"]
st.markdown("#### 가격·이동평균·매수 기준선")
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
    "네이버 장중/일봉·투자자 수급, KRX 공매도 통계와 확정 일별 통계를 대조·가공했습니다."
)
st.caption(
    "⚠️ 표시 가격은 확정 수익을 보장하는 목표가가 아니라 조건부 관찰선입니다. "
    "이 도구는 투자 권유·자동주문이 아니며 종가 확정 전 장중 판정은 바뀔 수 있습니다."
)
