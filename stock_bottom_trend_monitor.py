# -*- coding: utf-8 -*-
"""
개별종목 바닥확인 → 상승추세·매수구간 모니터 v3.1
========================================
2026-07-29 개별주식선물 수급 추가판. v3.0 → v3.1 주요 변경:

  [신규 · 개별주식선물 외국인/기관 수급]
  A. 한국 종목은 KRX 주식선물 상품을 자동 매칭하고 외국인·기관의
     일별 순매수 계약을 현물 수급과 분리해 분석한다.
  B. KRX 투자자별 파생상품 통계가 로그인 응답으로 제한되는 환경을
     위해 KRX/HTS 내보내기 CSV 업로드를 지원한다. 종목코드·일자와
     외국인/기관 순매수 열을 자동 인식한다.
  C. 미결제약정·선물종가가 함께 있으면 가격×미결제약정 조합으로
     신규 롱, 숏커버, 신규 숏, 롱청산 가능성을 표시한다. 미결제약정이
     없으면 신규 포지션과 청산을 구분할 수 없다고 명시한다.
  D. 선물 수급이 있을 때 진입점수 100점 안에서 현물수급·공매도
     가중치를 재배분해 선물수급 10점을 반영한다. 데이터가 없으면
     기존 v3.0 점수체계를 그대로 유지한다.

  [v3.0 · 미국 종목 지원]
  E. 감시 단위를 6자리 코드 하나에서 (시장, 심볼) 복합키로 확장.
     내부 식별키는 "KR:005930", "US:NVDA" 형태의 uid를 쓴다.
     한국 005930과 미국 티커가 겹쳐도 충돌하지 않는다.
  F. 미국 종목은 야후 파이낸스 v8 chart(무인증·수정주가)로 일봉·현재가,
     v1 search로 종목 검색. 상대강도 기준은 미국 S&P500(^GSPC).
  G. 확정 종가 앵커를 시장별 정규장 마감으로 분리. KR 15:30 KST,
     US 16:00 America/New_York.
  H. 미국은 외국인/기관 수급·KRX 공매도·KRX 확정 대조가 모두 없으므로
     해당 신호를 '해당 없음'으로 자동 제외한다. 미국은 공매도 압력이
     진입점수에서 중립(50)으로 빠지고 나머지 축으로만 판정한다.
     바닥형성/상승추세 만점을 시장별로 조정해 점수 표기 왜곡을 막는다.
     호가단위·가격 포맷도 미국(달러·소수)과 한국(원·정수)으로 분기.

  [v2.0 · 공매도 로직 감사 수정]
  I. evaluate_short_pressure의 reference_balance 기준일 버그 수정 —
     "최근 10개 중 첫 값"(공시 간격에 따라 임의 과거일)이 아니라 실제
     10영업일 이전에 가장 가까운 잔고를 anchor로 사용.
  J. 공매도 거래일과 잔고 공시일이 서로 다른 날짜인데 한 판정에 섞이던
     문제 — 두 최근일 간극이 5영업일을 넘으면 잔고 변화 가중을 줄인다.
  K. _krx_stock_row의 `code in digits` 과다 매칭 제거(단축코드 정확
     일치 → ISIN 위치 기반). higher_low/near_high 등 슬라이스 NaN 가드.

미국은 인증 불필요. 한국 KRX 인증키는 코드에 넣지 않는다.
Streamlit Cloud → Settings → Secrets:

    KRX_AUTH_KEY = "발급받은 인증키"        # 한국 KRX 종가 대조용(선택)
    WATCHLIST = "KR:005930,KR:000660,US:NVDA,US:AVGO"

실행:
    streamlit run stock_bottom_trend_monitor.py
"""

import datetime as dt
import difflib
from io import BytesIO
import math
import os
import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import pandas as pd
import requests
import streamlit as st

try:
    from zoneinfo import ZoneInfo
    _US_TZ = ZoneInfo("America/New_York")
except Exception:
    _US_TZ = dt.timezone(dt.timedelta(hours=-5))


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
YF_BASE = "https://query1.finance.yahoo.com"

MARKET_KR = "KR"
MARKET_US = "US"
VALID_MARKETS = (MARKET_KR, MARKET_US)

MARKET_META = {
    MARKET_KR: {
        "tz": KST,
        "close_time": dt.time(15, 30),
        "currency": "원",
        "price_fmt": "{:,.0f}",
        "index_name": "KOSPI",
        "has_investor_flow": True,
        "has_stock_futures_flow": True,
        "has_short_selling": True,
        "has_krx_confirm": True,
    },
    MARKET_US: {
        "tz": _US_TZ,
        "close_time": dt.time(16, 0),
        "currency": "$",
        "price_fmt": "{:,.2f}",
        "index_name": "S&P500",
        "has_investor_flow": False,
        "has_stock_futures_flow": False,
        "has_short_selling": False,
        "has_krx_confirm": False,
    },
}


def make_uid(market: str, symbol: str) -> str:
    return f"{market}:{symbol}"


def split_uid(uid: str):
    """uid → (market, symbol). 접두어 없으면 6자리 숫자는 KR, 나머지는 US로 추정."""
    if ":" in uid:
        market, symbol = uid.split(":", 1)
        market = market.strip().upper()
        symbol = symbol.strip().upper()
        if market in VALID_MARKETS and symbol:
            return market, symbol
    token = uid.strip().upper()
    digits = "".join(ch for ch in token if ch.isdigit())
    if len(digits) == 6 and digits == token:
        return MARKET_KR, digits
    return MARKET_US, token


def price_format(market: str):
    return MARKET_META[market]["price_fmt"]


def _money(value, market: str):
    """시장별 통화 표기. KR: 12,300원 · US: $45.67"""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "—"
    if market == MARKET_US:
        return f"${value:,.2f}"
    return f"{value:,.0f}원"


def market_now(market: str) -> dt.datetime:
    return dt.datetime.now(MARKET_META[market]["tz"])


def market_today(market: str) -> dt.date:
    return market_now(market).date()

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


def parse_watchlist(raw: str):
    """감시목록 문자열을 uid 리스트로 파싱한다(시장 인지).

    허용: "US:NVDA" "KR:005930" (권장) · "005930"(→KR) · "NVDA"(→US)
    """
    uids = []
    for token in raw.replace("\n", ",").split(","):
        token = token.strip()
        if not token:
            continue
        market, symbol = split_uid(token)
        if market == MARKET_KR:
            symbol = "".join(ch for ch in symbol if ch.isdigit())
            if len(symbol) != 6:
                continue
        else:
            symbol = "".join(
                ch for ch in symbol.upper() if ch.isalnum() or ch in ".-"
            )
            if not symbol:
                continue
        uid = make_uid(market, symbol)
        if uid not in uids:
            uids.append(uid)
    return uids[:20]


# ──────────────────────────────────────────────────────────────
# 1. 데이터 수집
# ──────────────────────────────────────────────────────────────
def quote_datetime(traded_at, market: str):
    """시세 타임스탬프를 해당 시장 현지시각으로 파싱한다. 실패 시 None."""
    if not traded_at:
        return None
    tz = MARKET_META[market]["tz"]
    try:
        parsed = dt.datetime.fromisoformat(str(traded_at))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=tz)
    return parsed.astimezone(tz)


def is_final_quote(traded_at, market: str):
    """당일 정규장 마감(현지시각) 이후 시세인지 — 시장별 마감시각 적용."""
    parsed = quote_datetime(traded_at, market)
    if not parsed:
        return False
    return bool(
        parsed.date() == market_today(market)
        and parsed.time() >= MARKET_META[market]["close_time"]
    )


def apply_confirmed_cut(frame, market: str, final: bool):
    """공식 판정용 앵커. 마감 확정 전에는 당일(현지) 행을 제외한다."""
    if frame is None or frame.empty or final:
        return frame
    return frame[frame.index.date < market_today(market)]


@st.cache_data(ttl=300, show_spinner=False)
def search_stocks_kr(query: str):
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
                "market": MARKET_KR,
                "symbol": code,
                "name": item.get("name", code),
                "exchange": item.get("typeName", item.get("typeCode", "")),
            })
        if len(results) >= 10:
            break
    return results


@st.cache_data(ttl=30, show_spinner=False)
def fetch_basic_kr(code: str):
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
        "market": MARKET_KR,
        "symbol": code,
        "name": d.get("stockName", code),
        "price": optional_number(d.get("closePrice")),
        "change_pct": optional_number(d.get("fluctuationsRatio")),
        "traded_at": d.get("localTradedAt", ""),
        "market_status": d.get("marketStatus", ""),
        "exchange": d.get("stockExchangeName", ""),
        "sosok": str(d.get("sosok", "")),
    }


@st.cache_data(ttl=300, show_spinner=False)
def fetch_price_history_kr(code: str):
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
    df = df[["open", "high", "low", "close", "volume"]].dropna().sort_index()
    # 인덱스(날짜) 기준 중복 제거(keep=last) — 같은날 다른값도 정리
    return df[~df.index.duplicated(keep="last")]


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


def _compact_text(value) -> str:
    """열 이름·종목명을 비교하기 위한 공백/기호 제거 문자열."""
    text = unicodedata.normalize("NFKC", str(value or "")).lower()
    return re.sub(r"[^0-9a-z가-힣]", "", text)


def _normalized_security_name(value) -> str:
    text = _compact_text(value)
    for suffix in ("주식선물", "선물", "보통주", "commonstock"):
        if text.endswith(suffix):
            text = text[: -len(suffix)]
    return text


def _find_column(columns, predicate):
    for column in columns:
        if predicate(_compact_text(column)):
            return column
    return None


def _numeric_series(series: pd.Series) -> pd.Series:
    cleaned = (
        series.astype(str)
        .str.replace(",", "", regex=False)
        .str.replace("계약", "", regex=False)
        .str.replace("주", "", regex=False)
        .str.strip()
    )
    cleaned = cleaned.replace({"": np.nan, "-": np.nan, "–": np.nan})
    return pd.to_numeric(cleaned, errors="coerce")


def _date_series(series: pd.Series) -> pd.Series:
    raw = series.astype(str).str.strip().str.replace(r"\.0$", "", regex=True)
    compact = raw.str.replace(r"[^0-9]", "", regex=True)
    parsed = pd.to_datetime(compact, format="%Y%m%d", errors="coerce")
    fallback = pd.to_datetime(raw, errors="coerce")
    return parsed.fillna(fallback)


def _standardize_stock_futures_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """KRX/HTS의 wide·long CSV를 공통 선물수급 포맷으로 바꾼다."""
    if frame is None or frame.empty:
        return pd.DataFrame()
    frame = frame.copy()
    frame.columns = [str(col).strip() for col in frame.columns]
    columns = list(frame.columns)

    date_col = _find_column(
        columns,
        lambda c: c in {
            "일자", "날짜", "기준일", "거래일", "매매일", "date",
            "trddd", "basdd",
        } or c.endswith("일자"),
    )
    if date_col is None:
        raise ValueError("일자 열을 찾지 못했습니다")

    def is_net_column(compact, subject):
        if subject not in compact:
            return False
        if "순매수" in compact or "순매매" in compact or "net" in compact:
            return True
        return compact in {
            subject,
            subject + "합계",
            subject + "계",
            subject + "순매수량",
            subject + "순매수계약",
        }

    foreign_col = _find_column(
        columns, lambda c: is_net_column(c, "외국인")
    )
    institution_col = _find_column(
        columns, lambda c: is_net_column(c, "기관")
    )

    dates = _date_series(frame[date_col])
    standardized = pd.DataFrame(index=dates)
    standardized.index.name = "date"

    if foreign_col is not None and institution_col is not None:
        standardized["foreign"] = _numeric_series(frame[foreign_col]).to_numpy()
        standardized["institution"] = _numeric_series(
            frame[institution_col]
        ).to_numpy()
    else:
        investor_col = _find_column(
            columns,
            lambda c: (
                "투자자" in c
                or c in {"주체", "투자주체", "구분", "investor"}
            ),
        )
        net_col = _find_column(
            columns,
            lambda c: (
                "순매수" in c or "순매매" in c or c in {"net", "netbuy"}
            ),
        )
        if investor_col is None or net_col is None:
            raise ValueError(
                "외국인·기관 순매수 열 또는 투자자구분·순매수 열을 찾지 못했습니다"
            )
        long = pd.DataFrame({
            "date": dates,
            "investor": frame[investor_col].astype(str),
            "net": _numeric_series(frame[net_col]),
        }).dropna(subset=["date", "net"])
        investor_compact = long["investor"].map(_compact_text)
        foreign_total_tokens = {"외국인", "외국인합계", "외국인계"}
        institution_total_tokens = {"기관", "기관합계", "기관계", "기관투자자"}
        has_foreign_total = investor_compact.isin(
            foreign_total_tokens
        ).any()
        has_institution_total = investor_compact.isin(
            institution_total_tokens
        ).any()
        institution_tokens = (
            "기관", "금융투자", "보험", "투신", "사모", "은행",
            "기타금융", "연기금",
        )
        long["type"] = long["investor"].map(
            lambda value: (
                "foreign"
                if (
                    _compact_text(value) in foreign_total_tokens
                    if has_foreign_total
                    else "외국" in _compact_text(value)
                )
                else "institution"
                if (
                    _compact_text(value) in institution_total_tokens
                    if has_institution_total
                    else any(
                        token in _compact_text(value)
                        for token in institution_tokens
                    )
                )
                else ""
            )
        )
        long = long[long["type"] != ""]
        if long.empty:
            raise ValueError("외국인·기관 행을 찾지 못했습니다")
        standardized = (
            long.pivot_table(
                index="date", columns="type", values="net", aggfunc="sum"
            )
            .rename_axis(None, axis=1)
        )
        for required in ("foreign", "institution"):
            if required not in standardized:
                standardized[required] = 0.0

    oi_col = _find_column(
        columns,
        lambda c: (
            "미결제약정" in c
            or c in {"openinterest", "openinterestqty", "oi"}
        ),
    )
    futures_close_col = _find_column(
        columns,
        lambda c: (
            ("선물" in c and ("종가" in c or "가격" in c))
            or c in {"선물종가", "futuresclose", "futureclose"}
        ),
    )
    if futures_close_col is None:
        futures_close_col = _find_column(
            columns, lambda c: c in {"종가", "현재가", "close", "price"}
        )

    extras = pd.DataFrame(index=dates)
    if oi_col is not None:
        extras["open_interest"] = _numeric_series(frame[oi_col]).to_numpy()
    if futures_close_col is not None:
        extras["futures_close"] = _numeric_series(
            frame[futures_close_col]
        ).to_numpy()
    standardized = standardized[~standardized.index.isna()]
    standardized = (
        standardized[["foreign", "institution"]]
        .groupby(level=0)
        .sum(min_count=1)
        .sort_index()
    )
    if not extras.empty:
        extras = extras[~extras.index.isna()].groupby(level=0).last()
        standardized = standardized.join(extras, how="outer")
    standardized[["foreign", "institution"]] = standardized[
        ["foreign", "institution"]
    ].fillna(0.0)
    return standardized


def _extract_stock_code(series: pd.Series):
    values = []
    for value in series.dropna().astype(str):
        match = re.search(r"(?<!\d)(\d{6})(?!\d)", value)
        if match:
            values.append(match.group(1))
    unique = list(dict.fromkeys(values))
    return unique[0] if len(unique) == 1 else ""


def _read_uploaded_csv(uploaded_file):
    raw = uploaded_file.getvalue()
    last_error = None
    for encoding in ("utf-8-sig", "cp949", "euc-kr", "utf-8"):
        try:
            return pd.read_csv(
                BytesIO(raw), encoding=encoding, sep=None, engine="python"
            )
        except Exception as exc:
            last_error = exc
    raise ValueError(f"CSV 읽기 실패: {last_error}")


def parse_stock_futures_uploads(uploaded_files):
    """업로드 CSV들을 종목 단위 데이터셋으로 분리한다."""
    datasets, errors = [], []
    for uploaded in uploaded_files or []:
        try:
            raw = _read_uploaded_csv(uploaded)
            raw.columns = [str(col).strip() for col in raw.columns]
            columns = list(raw.columns)
            code_col = _find_column(
                columns,
                lambda c: c in {
                    "종목코드", "단축코드", "기초자산코드", "현물코드",
                    "stockcode", "symbol", "ticker",
                },
            )
            name_col = _find_column(
                columns,
                lambda c: c in {
                    "종목명", "기초자산명", "현물명", "상품명",
                    "stockname", "underlying", "underlyingname",
                },
            )

            groups = [("", raw)]
            if code_col is not None:
                def code_from_value(value):
                    match = re.search(
                        r"(?<!\d)(\d{6})(?!\d)", str(value)
                    )
                    return match.group(1) if match else ""

                valid_codes = raw[code_col].map(code_from_value)
                if valid_codes[valid_codes != ""].nunique() > 1:
                    groups = [
                        (code, raw.loc[valid_codes == code].copy())
                        for code in valid_codes[valid_codes != ""].unique()
                    ]
            elif name_col is not None:
                valid_names = raw[name_col].astype(str).str.strip()
                valid_names = valid_names[
                    ~valid_names.isin(("", "nan", "None"))
                ]
                if valid_names.nunique() > 1:
                    groups = [
                        ("", raw.loc[raw[name_col].astype(str).str.strip() == name])
                        for name in valid_names.unique()
                    ]

            for group_code, group in groups:
                standardized = _standardize_stock_futures_frame(group)
                if standardized.empty:
                    continue
                code = group_code
                if not code and code_col is not None:
                    code = _extract_stock_code(group[code_col])
                name = ""
                if name_col is not None:
                    names = [
                        str(value).strip()
                        for value in group[name_col].dropna().unique()
                        if str(value).strip()
                    ]
                    if len(names) == 1:
                        name = names[0]
                datasets.append({
                    "frame": standardized,
                    "code": code,
                    "name": name,
                    "filename": uploaded.name,
                    "source": "업로드 CSV",
                })
        except Exception as exc:
            errors.append(f"{uploaded.name}: {exc}")
    return datasets, errors


def match_uploaded_stock_futures(
    datasets,
    symbol: str,
    stock_name: str,
    kr_stock_count: int,
):
    if not datasets:
        return None
    for dataset in datasets:
        if dataset.get("code") == symbol:
            return dataset

    target = _normalized_security_name(stock_name)
    named = []
    for dataset in datasets:
        candidate = _normalized_security_name(dataset.get("name", ""))
        filename = _compact_text(dataset.get("filename", ""))
        if candidate and (
            candidate == target
            or (min(len(candidate), len(target)) >= 3
                and (candidate in target or target in candidate))
        ):
            named.append(dataset)
        elif symbol and symbol in filename:
            named.append(dataset)
    if len(named) == 1:
        return named[0]
    if len(datasets) == 1 and kr_stock_count == 1:
        return datasets[0]
    return None


@st.cache_data(ttl=21600, show_spinner=False)
def fetch_stock_futures_catalog():
    """KRX 주식선물 기초자산별 상품 코드를 가져온다."""
    r = requests.post(
        KRX_DATA_URL,
        data={
            "bld": "dbms/comm/component/drv_clss19",
            "prodId": "KR___FUEQU",
            "isuCd": "KR___FUEQU",
            "lang": "ko_KR",
            "locale": "ko_KR",
        },
        headers={
            **UA,
            "Referer": (
                "https://data.krx.co.kr/contents/MDC/STAT/standard/"
                "MDCSTAT131.jsp"
            ),
        },
        timeout=20,
    )
    r.raise_for_status()
    payload = r.json()
    return [
        item for item in payload.get("output", [])
        if item.get("value") and item.get("value") != "KR___FUEQU"
    ]


def resolve_stock_futures_product(stock_name: str):
    target = _normalized_security_name(stock_name)
    if not target:
        return None
    candidates = []
    for item in fetch_stock_futures_catalog():
        candidate = _normalized_security_name(item.get("name", ""))
        if not candidate:
            continue
        if candidate == target:
            score = 1.0
        elif (
            min(len(candidate), len(target)) >= 3
            and (candidate in target or target in candidate)
        ):
            score = 0.90 + 0.09 * (
                min(len(candidate), len(target))
                / max(len(candidate), len(target))
            )
        else:
            score = difflib.SequenceMatcher(None, target, candidate).ratio()
        candidates.append((score, item))
    if not candidates:
        return None
    score, item = max(candidates, key=lambda pair: pair[0])
    if score < 0.72:
        return None
    return {
        "product_id": item["value"],
        "product_name": item.get("name", ""),
        "match_score": score,
    }


def _request_stock_futures_flow(product_id: str, start: dt.date, end: dt.date):
    response = requests.post(
        KRX_DATA_URL,
        data={
            "bld": "dbms/MDC/STAT/standard/MDCSTAT13102",
            "locale": "ko_KR",
            "inqTpCd": "2",
            "prodId": "KR___FUEQU",
            "isuCd": "KR___FUEQU",
            "isuCd2": product_id,
            "isuOpt": "ALL",
            "aggBasTpCd": "",
            "strtDd": start.strftime("%Y%m%d"),
            "endDd": end.strftime("%Y%m%d"),
            "strtDdBox1": start.strftime("%Y%m%d"),
            "endDdBox1": end.strftime("%Y%m%d"),
            "prtType": "QTY",
            "prtCheck": "SUN",
            "share": "1",
            "money": "1",
        },
        headers={
            **UA,
            "Referer": (
                "https://data.krx.co.kr/contents/MDC/STAT/standard/"
                "MDCSTAT131.jsp"
            ),
        },
        timeout=25,
    )
    response.raise_for_status()
    text = response.text.strip()
    if text == "LOGOUT" or "로그인" in text:
        return pd.DataFrame(), "로그인 필요"
    if text.startswith("<"):
        return pd.DataFrame(), "KRX 응답 제한"
    payload = response.json()
    rows = payload.get("output", [])
    if not isinstance(rows, list):
        return pd.DataFrame(), "응답 형식 오류"
    parsed = []
    for row in rows:
        try:
            parsed.append({
                "date": pd.to_datetime(row["TRD_DD"], format="%Y/%m/%d"),
                "foreign": _krx_numeric(row.get("A12")),
                "institution": _krx_numeric(row.get("A07")),
            })
        except (KeyError, TypeError, ValueError):
            continue
    if not parsed:
        return pd.DataFrame(), "조회 데이터 없음"
    frame = (
        pd.DataFrame(parsed)
        .drop_duplicates("date")
        .set_index("date")
        .sort_index()
    )
    return frame, "정상"


@st.cache_data(ttl=3600, show_spinner=False)
def probe_stock_futures_flow_access():
    """KRX 파생 투자자 통계의 무인증 응답 가능 여부를 한 번만 확인한다."""
    end = market_today(MARKET_KR)
    start = end - dt.timedelta(days=14)
    try:
        _, status = _request_stock_futures_flow("KR___FUS11", start, end)
        return status not in ("로그인 필요", "KRX 응답 제한"), status
    except Exception as exc:
        return False, f"{type(exc).__name__}"


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_stock_futures_flow_auto(stock_name: str):
    product = resolve_stock_futures_product(stock_name)
    if product is None:
        return pd.DataFrame(), {
            "status": "상장상품 매칭 없음",
            "source": "KRX 자동조회",
        }
    end = market_today(MARKET_KR)
    start = end - dt.timedelta(days=50)
    try:
        frame, status = _request_stock_futures_flow(
            product["product_id"], start, end
        )
    except Exception as exc:
        frame, status = pd.DataFrame(), f"조회 실패: {type(exc).__name__}"
    return frame, {
        **product,
        "status": status,
        "source": "KRX 자동조회",
    }


@st.cache_data(ttl=300, show_spinner=False)
def fetch_index_history(index_code: str):
    """KOSPI 또는 KOSDAQ 일봉을 가져온다(한국 벤치마크)."""
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


# ── 미국(야후 파이낸스, 무인증) ──
def _yahoo_chart(symbol: str, rng: str = "2y", interval: str = "1d"):
    r = requests.get(
        f"{YF_BASE}/v8/finance/chart/{symbol}",
        params={"range": rng, "interval": interval, "includePrePost": "false"},
        headers=UA,
        timeout=15,
    )
    r.raise_for_status()
    payload = r.json()
    chart = payload.get("chart") or {}
    if chart.get("error"):
        raise ValueError(f"야후 오류: {chart['error']}")
    result = chart.get("result") or []
    if not result:
        raise ValueError("야후 응답 비어 있음")
    return result[0]


def _yahoo_to_frame(result):
    ts = result.get("timestamp") or []
    quote = ((result.get("indicators") or {}).get("quote") or [{}])[0]
    if not ts or not quote:
        raise ValueError("야후 캔들 없음")
    idx = pd.to_datetime(pd.Series(ts, dtype="int64"), unit="s", utc=True)
    idx = idx.dt.tz_convert(_US_TZ).dt.normalize().dt.tz_localize(None)
    df = pd.DataFrame({
        "open": quote.get("open"),
        "high": quote.get("high"),
        "low": quote.get("low"),
        "close": quote.get("close"),
        "volume": quote.get("volume"),
    })
    df.index = idx
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["open", "high", "low", "close"]).sort_index()
    df["volume"] = df["volume"].fillna(0)
    return df[~df.index.duplicated(keep="last")]


@st.cache_data(ttl=300, show_spinner=False)
def search_stocks_us(query: str):
    query = query.strip()
    if not query:
        return []
    r = requests.get(
        f"{YF_BASE}/v1/finance/search",
        params={"q": query, "quotesCount": 10, "newsCount": 0},
        headers=UA,
        timeout=12,
    )
    r.raise_for_status()
    results = []
    for q in r.json().get("quotes", []):
        symbol = str(q.get("symbol", "")).strip().upper()
        if not symbol or "." in symbol:
            continue
        if str(q.get("quoteType", "")).upper() not in ("EQUITY", "ETF"):
            continue
        results.append({
            "market": MARKET_US,
            "symbol": symbol,
            "name": q.get("shortname") or q.get("longname") or symbol,
            "exchange": q.get("exchDisp") or q.get("exchange") or "",
        })
        if len(results) >= 10:
            break
    return results


@st.cache_data(ttl=30, show_spinner=False)
def fetch_basic_us(symbol: str):
    result = _yahoo_chart(symbol, rng="5d", interval="1d")
    meta = result.get("meta") or {}
    price = optional_number(meta.get("regularMarketPrice"))
    prev = optional_number(
        meta.get("chartPreviousClose") or meta.get("previousClose")
    )
    change_pct = None
    if price is not None and prev not in (None, 0):
        change_pct = (price / prev - 1) * 100
    traded_at = ""
    mkt_time = meta.get("regularMarketTime")
    if mkt_time:
        try:
            traded_at = (
                dt.datetime.fromtimestamp(int(mkt_time), tz=dt.timezone.utc)
                .astimezone(_US_TZ)
                .isoformat()
            )
        except (TypeError, ValueError, OverflowError):
            traded_at = ""
    return {
        "market": MARKET_US,
        "symbol": symbol,
        "name": (
            meta.get("longName") or meta.get("shortName")
            or meta.get("symbol") or symbol
        ),
        "price": price,
        "change_pct": change_pct,
        "traded_at": traded_at,
        "market_status": meta.get("marketState", ""),
        "exchange": meta.get("fullExchangeName") or meta.get("exchangeName") or "",
        "sosok": "",
    }


@st.cache_data(ttl=300, show_spinner=False)
def fetch_price_history_us(symbol: str):
    df = _yahoo_to_frame(_yahoo_chart(symbol, rng="2y", interval="1d"))
    if len(df) < 80:
        raise ValueError(f"일봉 표본 부족 ({len(df)}일)")
    return df


@st.cache_data(ttl=300, show_spinner=False)
def fetch_sp500_history():
    return _yahoo_to_frame(_yahoo_chart("^GSPC", rng="2y", interval="1d"))[["close"]]


def fetch_benchmark(market: str, sosok: str = ""):
    """시장별 상대강도 기준지수. KR: KOSPI/KOSDAQ, US: S&P500."""
    if market == MARKET_US:
        return fetch_sp500_history(), "S&P500"
    name = "KOSPI" if sosok == "0" else "KOSDAQ"
    return fetch_index_history(name), name


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


def _fallback_basic(market: str, symbol: str, label: str = ""):
    return {
        "market": market, "symbol": symbol, "name": label or symbol,
        "price": None, "change_pct": None, "traded_at": "",
        "market_status": "", "exchange": "", "sosok": "",
        "basic_failed": True,
    }


def fetch_bundle(uid: str, label: str = ""):
    """한 종목의 기본정보·일봉·(한국)수급·공매도를 시장별로 묶는다."""
    market, symbol = split_uid(uid)
    empty_flow = pd.DataFrame(columns=["foreign", "institution", "individual"])
    if market == MARKET_US:
        history = fetch_price_history_us(symbol)
        try:
            basic = fetch_basic_us(symbol)
        except Exception:
            basic = _fallback_basic(market, symbol, label)
        return basic, history, empty_flow, pd.DataFrame()
    # 한국
    history = fetch_price_history_kr(symbol)
    try:
        basic = fetch_basic_kr(symbol)
    except Exception:
        basic = _fallback_basic(market, symbol, label)
    with ThreadPoolExecutor(max_workers=2) as pool:
        investor_future = pool.submit(fetch_investor_trend, symbol)
        short_future = pool.submit(fetch_short_selling, symbol)
        try:
            investor = investor_future.result()
        except Exception:
            investor = empty_flow
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
    """단축코드 정확 일치 → ISIN 위치 기반(KR7+종목코드). `code in digits`
    식 부분 매칭은 다른 종목 오매칭 위험이 있어 제거 (v3.0 #G)."""
    for row in rows:
        short = str(row.get("ISU_SRT_CD", "")).strip().upper()
        if short == code or short == "A" + code:
            return row
    for row in rows:
        isin_digits = "".join(
            ch for ch in str(row.get("ISU_CD", "")) if ch.isdigit()
        )
        if len(isin_digits) >= 7 and isin_digits[1:7] == code:
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


def tick_size(price: float, market: str = MARKET_KR):
    """가격대별 호가단위. 미국은 $0.01 고정."""
    if market == MARKET_US:
        return 0.01
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


def round_to_tick(price: float, direction="nearest", market: str = MARKET_KR):
    if pd.isna(price):
        return np.nan
    tick = tick_size(float(price), market)
    units = float(price) / tick
    if direction == "up":
        return round(float(math.ceil(units) * tick), 2)
    if direction == "down":
        return round(float(math.floor(units) * tick), 2)
    return round(float(math.floor(units + 0.5) * tick), 2)


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


def evaluate_stock_futures_flow(
    stock_futures: pd.DataFrame,
    raw_history: pd.DataFrame,
):
    """개별주식선물의 외국인·기관 순매수와 OI 기반 포지션 변화를 판정한다."""
    empty_result = {
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
        "latest_date": None,
        "oi_available": False,
        "oi_change_pct": np.nan,
        "price_change_pct": np.nan,
        "price_source": "자료 없음",
        "position_label": "판정 불가",
        "interpretation": (
            "선물 수급 데이터가 없어 외국인·기관의 파생 포지션 방향을 "
            "진입점수에 반영하지 않았습니다."
        ),
        "series": pd.DataFrame(),
    }
    required = {"foreign", "institution"}
    if stock_futures.empty or not required.issubset(stock_futures.columns):
        return empty_result

    series = stock_futures.copy().sort_index()
    numeric_flow = series[["foreign", "institution"]].apply(
        pd.to_numeric, errors="coerce"
    )
    if numeric_flow.dropna(how="all").empty:
        return empty_result
    series[["foreign", "institution"]] = numeric_flow.fillna(0.0)

    foreign5 = float(series["foreign"].tail(5).sum())
    foreign10 = float(series["foreign"].tail(10).sum())
    institution5 = float(series["institution"].tail(5).sum())
    institution10 = float(series["institution"].tail(10).sum())
    combined5 = foreign5 + institution5
    combined10 = foreign10 + institution10

    if foreign5 > 0 and institution5 > 0:
        label = "선물 동반 순매수"
    elif foreign5 > 0 and institution5 < 0:
        label = "외국인 순매수·기관 순매도"
    elif foreign5 < 0 and institution5 > 0:
        label = "기관 순매수·외국인 순매도"
    elif foreign5 < 0 and institution5 < 0:
        label = "선물 동반 순매도"
    else:
        label = "선물 수급 중립"

    foreign_momentum = _flow_momentum(series["foreign"])
    institution_momentum = _flow_momentum(series["institution"])
    score = 50
    score += 15 if foreign5 > 0 else -15 if foreign5 < 0 else 0
    score += (
        15 if institution5 > 0 else -15 if institution5 < 0 else 0
    )
    score += 7 if foreign10 > 0 else -7 if foreign10 < 0 else 0
    score += (
        7 if institution10 > 0 else -7 if institution10 < 0 else 0
    )
    for momentum in (foreign_momentum, institution_momentum):
        if momentum in ("매수 전환", "매수 확대", "매도 완화"):
            score += 5
        elif momentum in ("매도 전환", "매도 확대"):
            score -= 5

    oi_change_pct = np.nan
    oi_available = False
    if "open_interest" in series:
        oi_values = pd.to_numeric(
            series["open_interest"], errors="coerce"
        ).dropna()
        if len(oi_values) >= 2:
            reference = (
                float(oi_values.iloc[-6])
                if len(oi_values) >= 6
                else float(oi_values.iloc[0])
            )
            if reference > 0:
                oi_change_pct = (
                    float(oi_values.iloc[-1]) / reference - 1
                ) * 100
                oi_available = True

    price_change_pct = np.nan
    price_source = "자료 없음"
    if "futures_close" in series:
        price_values = pd.to_numeric(
            series["futures_close"], errors="coerce"
        ).dropna()
    else:
        price_values = pd.Series(dtype=float)
    if len(price_values) >= 2:
        price_source = "선물"
    if len(price_values) < 2 and not raw_history.empty:
        price_values = pd.to_numeric(
            raw_history["close"], errors="coerce"
        ).dropna()
        if len(price_values) >= 2:
            price_source = "현물 기초자산"
    if len(price_values) >= 2:
        reference = (
            float(price_values.iloc[-6])
            if len(price_values) >= 6
            else float(price_values.iloc[0])
        )
        if reference > 0:
            price_change_pct = (
                float(price_values.iloc[-1]) / reference - 1
            ) * 100

    direction = 1 if combined5 > 0 else -1 if combined5 < 0 else 0
    price_direction = (
        1 if price_change_pct > 0 else -1 if price_change_pct < 0 else 0
    )
    oi_direction = (
        1 if oi_change_pct > 0 else -1 if oi_change_pct < 0 else 0
    )
    if not oi_available:
        position_label = (
            "순매수 우위" if direction > 0
            else "순매도 우위" if direction < 0
            else "방향 혼재"
        )
        interpretation = (
            f"최근 5일 외국인·기관 합산은 {position_label}입니다. "
            "미결제약정이 없어 신규 포지션과 기존 포지션 청산은 "
            "구분할 수 없습니다."
        )
    elif direction > 0 and price_direction > 0 and oi_direction > 0:
        position_label = "신규 롱 유입 가능성"
        interpretation = (
            "순매수·가격·미결제약정이 함께 증가해 신규 매수 포지션 "
            "유입 가능성이 있습니다."
        )
    elif direction > 0 and price_direction > 0 and oi_direction < 0:
        position_label = "숏커버 가능성"
        interpretation = (
            "순매수와 가격 상승에 미결제약정 감소가 동반돼 기존 "
            "매도 포지션 청산 가능성이 있습니다."
        )
    elif direction < 0 and price_direction < 0 and oi_direction > 0:
        position_label = "신규 숏 유입 가능성"
        interpretation = (
            "순매도·가격 하락·미결제약정 증가가 겹쳐 신규 매도 "
            "포지션 유입 가능성이 있습니다."
        )
    elif direction < 0 and price_direction < 0 and oi_direction < 0:
        position_label = "롱청산 가능성"
        interpretation = (
            "순매도와 가격 하락에 미결제약정 감소가 동반돼 기존 "
            "매수 포지션 청산 가능성이 있습니다."
        )
    else:
        position_label = "포지션 혼재"
        interpretation = (
            "수급·가격·미결제약정 방향이 엇갈려 신규 진입과 청산 중 "
            "한쪽으로 단정하기 어렵습니다."
        )
    if oi_available:
        interpretation += (
            " 전체 미결제약정은 투자자별 잔고가 아니므로 가능성 "
            "판정으로만 해석해야 합니다."
        )

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
        "latest_date": series.index.max(),
        "oi_available": oi_available,
        "oi_change_pct": oi_change_pct,
        "price_change_pct": price_change_pct,
        "price_source": price_source,
        "position_label": position_label,
        "interpretation": interpretation,
        "series": series,
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
        "balance_stale": False,
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

    # v3.0 수정 #E: 잔고 변화 기준일을 "최근 10개 중 첫 값"(공시 간격에 따라
    # 임의 과거일)이 아니라 실제 10영업일(≈14일) 이전에 가장 가까운 잔고로.
    reference_balance = np.nan
    if len(balances) >= 2:
        target_date = balances.index[-1] - pd.Timedelta(days=14)
        earlier = balances[balances.index <= target_date]
        if not earlier.empty:
            reference_balance = float(earlier.iloc[-1])
        else:
            reference_balance = float(balances.iloc[0])
    balance_change_pct = (
        (latest_balance / reference_balance - 1) * 100
        if pd.notna(reference_balance) and reference_balance > 0
        else np.nan
    )

    # v3.0 수정 #F: 공매도 거래 최근일과 잔고 공시 최근일이 크게 어긋나면
    # (5영업일≈7일 초과) 잔고 신호 신뢰도를 낮춘다.
    balance_stale = False
    if not ratio_series.empty and not balances.empty:
        gap_days = abs((ratio_series.index[-1] - balances.index[-1]).days)
        balance_stale = gap_days > 7

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
        # 잔고 공시가 거래일과 크게 어긋나면 가중치 절반으로 (v3.0 #F)
        w = 0.5 if balance_stale else 1.0
        if balance_change_pct > 10:
            score -= int(round(25 * w))
        elif balance_change_pct > 3:
            score -= int(round(10 * w))
        elif balance_change_pct <= -5:
            score += int(round(10 * w))

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
        "balance_stale": balance_stale,
        "series": series,
    }


def build_entry_plan(
    stage: str,
    df: pd.DataFrame,
    flow: dict,
    futures_flow: dict,
    short_pressure: dict,
    market: str = MARKET_KR,
):
    """추세·가격·현물/선물 수급·공매도로 조건부 매수계획을 만든다."""
    last = df.iloc[-1]
    close = float(last["close"])
    ma5 = float(last["ma5"])
    ma20 = float(last["ma20"])
    atr = float(last["atr14"]) if pd.notna(last["atr14"]) else close * 0.03
    rsi = float(last["rsi14"])
    prior20_high = float(df["high"].iloc[-21:-1].max())
    breakout_trigger = round_to_tick(
        prior20_high + tick_size(prior20_high, market),
        "up", market,
    )

    pullback_low_raw = max(ma20, ma5 - atr * 0.10)
    pullback_high_raw = min(close, ma5 + atr * 0.30)
    pullback_low = round_to_tick(pullback_low_raw, "nearest", market)
    pullback_high = round_to_tick(
        max(pullback_low_raw, pullback_high_raw), "nearest", market
    )
    entry_cancel = round_to_tick(
        pullback_low - tick_size(pullback_low, market),
        "down", market,
    )
    trend_invalidation = round_to_tick(ma20, "nearest", market)

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
    futures_safe = (
        not futures_flow["available"] or futures_flow["score"] >= 35
    )
    short_safe = short_pressure["label"] != "악화"

    breakout_confirmed = bool(
        close >= breakout_trigger
        and close_location >= 0.65
        and volume_ratio >= 1.30
        and rsi <= 72
        and flow_safe
        and futures_safe
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
        and futures_safe
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
    if futures_flow["available"]:
        flow_component = int(round(flow["score"] * 0.15))
        futures_component = int(round(futures_flow["score"] * 0.10))
        short_component = int(round(short_pressure["score"] * 0.10))
        component_max = {
            "추세": 25,
            "가격위치": 25,
            "거래량": 15,
            "현물 외국인·기관": 15,
            "개별주식선물": 10,
            "공매도": 10,
        }
    else:
        flow_component = int(round(flow["score"] * 0.20))
        futures_component = 0
        short_component = int(round(short_pressure["score"] * 0.15))
        component_max = {
            "추세": 25,
            "가격위치": 25,
            "거래량": 15,
            "현물 외국인·기관": 20,
            "공매도": 15,
        }
    score = int(np.clip(
        trend_component
        + price_component
        + volume_component
        + flow_component
        + futures_component
        + short_component,
        0,
        100,
    ))

    if stage in ("하락 진행", "추세 훼손"):
        status = "⛔ 신규매수 금지"
        reason = "가격 추세가 아직 하락 중이거나 기존 상승추세가 훼손됐습니다."
    elif (
        futures_flow["available"]
        and flow["label"] == "동반 매도"
        and futures_flow["score"] <= 30
    ):
        status = "⛔ 신규매수 금지"
        reason = "현물 동반 매도와 개별주식선물 수급 약세가 겹쳤습니다."
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
            "현물 외국인·기관": flow_component,
            **(
                {"개별주식선물": futures_component}
                if futures_flow["available"]
                else {}
            ),
            "공매도": short_component,
        },
        "component_max": component_max,
        "buy_condition": (
            f"눌림목 {_money(pullback_low, market)}~"
            f"{_money(pullback_high, market)}에서 "
            "거래량 감소 후 양봉 전환, 또는 "
            f"{_money(breakout_trigger, market)} 이상 종가+거래량 1.3배"
        ),
        "cancel_condition": (
            f"눌림 진입 후 {_money(entry_cancel, market)} 종가 이탈 시 "
            f"진입가설 재검토. MA20 부근 {_money(trend_invalidation, market)} "
            "2일 이탈 시 추세 재판정"
        ),
    }


def _signal(label, passed, detail):
    return {"label": label, "passed": bool(passed), "detail": detail}


def _safe_min(series):
    s = series.dropna()
    return float(s.min()) if len(s) else np.nan


def _safe_max(series):
    s = series.dropna()
    return float(s.max()) if len(s) else np.nan


def evaluate_stock(
    basic: dict,
    raw_history: pd.DataFrame,
    investor: pd.DataFrame,
    short_selling: pd.DataFrame,
    stock_futures: pd.DataFrame,
    stock_futures_meta: dict,
    benchmark: pd.DataFrame,
    benchmark_name: str,
):
    market = basic.get("market", MARKET_KR)
    has_flow = MARKET_META[market]["has_investor_flow"]
    has_futures_flow = MARKET_META[market]["has_stock_futures_flow"]
    pfmt = price_format(market)
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
    futures_flow = evaluate_stock_futures_flow(stock_futures, raw_history)
    futures_flow.update({
        key: value
        for key, value in (stock_futures_meta or {}).items()
        if key in {
            "status", "source", "product_id", "product_name",
            "match_score", "filename",
        }
    })
    futures_available = futures_flow["available"]

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
            f"종가 {pfmt.format(close)} / MA5 {pfmt.format(last['ma5'])}",
        ),
        _signal(
            "매도 거래량 소진·투매반전",
            volume_signal,
            "최근 하락 거래량 감소" if volume_exhaustion else
            "최근 10일 투매 후 종가회복" if capitulation_reversal else
            "거래량 소진 미확인",
        ),
    ]
    if has_flow:
        formation.append(_signal(
            "외국인·기관 5일 줄다리기",
            flow5_positive,
            (
                f"{flow['label']} / 합계 {flow5:+,.0f}주"
                if flow_available
                else "수급 데이터 없음"
            ),
        ))
    if has_futures_flow and futures_available:
        formation.append(_signal(
            "개별주식선물 외·기 5일 수급",
            futures_flow["combined5"] > 0,
            (
                f"{futures_flow['label']} / 합계 "
                f"{futures_flow['combined5']:+,.0f}계약"
            ),
        ))
    formation.append(_signal(
        f"{benchmark_name} 대비 10일 상대강도",
        pd.notna(rs10) and rs10 > 0,
        f"{rs10:+.2f}%p" if pd.notna(rs10) else "계산불가",
    ))
    formation_max = len(formation)

    above_ma20_two_days = bool((df["close"].tail(2) > df["ma20"].tail(2)).all())
    recent_low = _safe_min(df["low"].iloc[-10:])
    prior_low = _safe_min(df["low"].iloc[-20:-10])
    higher_low = (
        pd.notna(prior_low) and pd.notna(recent_low) and recent_low > prior_low
    )
    macd_positive = last["macd_hist"] > 0
    rsi_confirmed = rsi > 45
    obv_improving = last["obv"] > df["obv"].iloc[-6]
    prior_low_txt = pfmt.format(prior_low) if pd.notna(prior_low) else "—"
    recent_low_txt = pfmt.format(recent_low) if pd.notna(recent_low) else "—"

    confirmation = [
        _signal(
            "MA20 2일 연속 회복",
            above_ma20_two_days,
            f"종가 {pfmt.format(close)} / MA20 {pfmt.format(last['ma20'])}",
        ),
        _signal(
            "높아진 저점",
            higher_low,
            f"직전10일 저점 {prior_low_txt} → 최근10일 {recent_low_txt}",
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
    prior20_high = _safe_max(df["high"].iloc[-21:-1])
    near_high = pd.notna(prior20_high) and close >= prior20_high * 0.95
    rs20_positive = pd.notna(rs20) and rs20 > 0
    flow10_positive = flow_available and flow10 > 0
    prior20_high_txt = pfmt.format(prior20_high) if pd.notna(prior20_high) else "—"

    uptrend = [
        _signal(
            "종가 > MA20 > MA60",
            ordered,
            f"{pfmt.format(close)} > {pfmt.format(last['ma20'])} > "
            f"{pfmt.format(last['ma60'])}",
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
            f"종가 {pfmt.format(close)} / 직전20일 고점 {prior20_high_txt}",
        ),
        _signal(
            f"{benchmark_name} 대비 20일 상대강도",
            rs20_positive,
            f"{rs20:+.2f}%p" if pd.notna(rs20) else "계산불가",
        ),
    ]
    if has_flow:
        uptrend.append(_signal(
            "외국인·기관 10일 수급",
            flow10_positive,
            (
                f"{flow['label']} / 합계 {flow10:+,.0f}주"
                if flow_available
                else "수급 데이터 없음"
            ),
        ))
    if has_futures_flow and futures_available:
        uptrend.append(_signal(
            "개별주식선물 외·기 10일 수급",
            futures_flow["combined10"] > 0,
            (
                f"{futures_flow['label']} / 합계 "
                f"{futures_flow['combined10']:+,.0f}계약"
            ),
        ))
    uptrend_max = len(uptrend)

    below_ma20_two_days = bool((df["close"].tail(2) < df["ma20"].tail(2)).all())
    ma20_falling = last["ma20"] < df["ma20"].iloc[-6]
    below_ma60 = close < last["ma60"]
    prior20_low = _safe_min(df["low"].iloc[-21:-1])
    broke_20d_low = pd.notna(prior20_low) and close < prior20_low
    prior20_low_txt = pfmt.format(prior20_low) if pd.notna(prior20_low) else "—"
    breakdown = [
        _signal(
            "MA20 2일 이탈+기울기 하락",
            below_ma20_two_days and ma20_falling,
            f"종가 {pfmt.format(close)} / MA20 {pfmt.format(last['ma20'])}",
        ),
        _signal(
            "MA60 이탈",
            below_ma60,
            f"종가 {pfmt.format(close)} / MA60 {pfmt.format(last['ma60'])}",
        ),
        _signal(
            "직전 20일 저점 이탈",
            broke_20d_low,
            f"종가 {pfmt.format(close)} / 직전20일 저점 {prior20_low_txt}",
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

    # 수급 신호가 빠진 미국은 만점이 낮으므로 임계값을 비례 조정 (v3.0 #D)
    form_threshold = 3 if formation_max >= 6 else max(2, round(formation_max * 0.5))
    up_threshold = 3 if uptrend_max >= 5 else max(2, round(uptrend_max * 0.6))

    if historical_uptrend and breakdown_score >= 2:
        stage = "추세 훼손"
        action = "기존 상승추세가 훼손됨. 신규진입보다 위험 재평가 우선"
    elif uptrend_score >= up_threshold and close > last["ma20"]:
        stage = "상승추세"
        action = "추세 유지 여부 관찰. 과열이면 추격 금지"
    elif confirmation_score >= 3 and above_ma20_two_days:
        stage = "바닥 확인"
        action = "바닥 후보가 가격으로 확인되는 단계. 종가 기준 재확인"
    elif formation_score >= form_threshold:
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
    entry = build_entry_plan(
        stage, df, flow, futures_flow, short_pressure, market
    )
    drawdown60 = (close / df["high"].tail(60).max() - 1) * 100
    result = {
        "market": market,
        "basic": basic,
        "history": df,
        "investor": investor,
        "short_selling": short_selling,
        "stock_futures": stock_futures,
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
        "formation_max": formation_max,
        "uptrend_max": uptrend_max,
        "rsi": rsi,
        "rs20": rs20,
        "drawdown60": drawdown60,
        "overheat": overheat_reasons,
        "flow5": flow5,
        "flow10": flow10,
        "flow": flow,
        "futures_flow": futures_flow,
        "short_pressure": short_pressure,
        "entry": entry,
    }
    return result


# ──────────────────────────────────────────────────────────────
# 3. 화면
# ──────────────────────────────────────────────────────────────
st.title("📈 개별종목 상승추세·매수구간 모니터")
st.caption(
    "한국·미국 개별종목의 바닥·상승추세, 눌림목·돌파 가격, 추격 위험을 판정합니다. "
    "한국은 현물과 개별주식선물의 외국인·기관 수급, KRX 공매도 압력까지, "
    "미국은 가격·거래량·상대강도 기반으로 자동 판정합니다."
)

default_watchlist = _secret(
    "WATCHLIST",
    "KR:005930,KR:000660,KR:005380,US:NVDA,US:AVGO,US:GOOGL",
)
krx_auth_key = _secret("KRX_AUTH_KEY")

query_watchlist = parse_watchlist(st.query_params.get("stocks", ""))
if "watchlist_uids" not in st.session_state:
    st.session_state["watchlist_uids"] = (
        query_watchlist or parse_watchlist(default_watchlist)
    )
if "stock_labels" not in st.session_state:
    st.session_state["stock_labels"] = {}


def sync_watchlist_url():
    current = st.session_state["watchlist_uids"]
    if current:
        st.query_params["stocks"] = ",".join(current)
    elif "stocks" in st.query_params:
        del st.query_params["stocks"]


def uid_display(uid: str):
    market, symbol = split_uid(uid)
    label = st.session_state["stock_labels"].get(uid)
    flag = "🇰🇷" if market == MARKET_KR else "🇺🇸"
    return f"{flag} {label} ({symbol})" if label else f"{flag} {symbol}"


with st.sidebar:
    st.header("🔎 종목 검색")
    market_choice = st.radio(
        "시장",
        [MARKET_KR, MARKET_US],
        format_func=lambda m: "🇰🇷 한국" if m == MARKET_KR else "🇺🇸 미국",
        horizontal=True,
    )
    placeholder = (
        "예: 삼성전자, 하이닉스, 005930"
        if market_choice == MARKET_KR
        else "예: NVIDIA, NVDA, AAPL"
    )
    search_query = st.text_input("종목명 또는 티커/코드", placeholder=placeholder)

    search_results = []
    if search_query.strip():
        try:
            search_results = (
                search_stocks_us(search_query)
                if market_choice == MARKET_US
                else search_stocks_kr(search_query)
            )
        except Exception as exc:
            st.warning(f"종목 검색 실패: {exc}")

    if search_results:
        result_map = {item["symbol"]: item for item in search_results}
        picked_symbol = st.selectbox(
            "검색 결과",
            list(result_map),
            format_func=lambda s: (
                f"{result_map[s]['name']} ({s}) · {result_map[s]['exchange']}"
            ),
        )
        if st.button("➕ 감시목록에 추가", type="primary"):
            picked = result_map[picked_symbol]
            uid = make_uid(picked["market"], picked["symbol"])
            current = st.session_state["watchlist_uids"]
            if uid in current:
                st.info("이미 감시 중인 종목입니다.")
            elif len(current) >= 20:
                st.warning("감시종목은 최대 20개입니다.")
            else:
                current.append(uid)
                st.session_state["stock_labels"][uid] = picked["name"]
                sync_watchlist_url()
                st.rerun()
    elif search_query.strip():
        label = "KOSPI·KOSDAQ" if market_choice == MARKET_KR else "미국 상장"
        st.info(f"{label} 종목 검색 결과가 없습니다.")

    st.divider()
    st.subheader("현재 감시목록")
    current_uids = st.session_state["watchlist_uids"]
    if current_uids:
        remove_uids = st.multiselect(
            "삭제할 종목 선택", current_uids, format_func=uid_display
        )
        if st.button("🗑️ 선택 종목 삭제", disabled=not remove_uids):
            st.session_state["watchlist_uids"] = [
                u for u in current_uids if u not in remove_uids
            ]
            sync_watchlist_url()
            st.rerun()
        kr_n = sum(1 for u in current_uids if split_uid(u)[0] == MARKET_KR)
        us_n = len(current_uids) - kr_n
        st.caption(f"{len(current_uids)}개 (🇰🇷{kr_n} · 🇺🇸{us_n}) / 최대 20개")
    else:
        st.info("검색 후 종목을 추가하세요.")

    st.divider()
    if krx_auth_key:
        st.success("KRX 종가 대조용 Open API 키 설정됨 (한국)")
    else:
        st.info("KRX 종가 대조키 미설정 · 한국 공매도 통계는 자동수집")

    st.subheader("📄 개별주식선물 수급")
    futures_flow_uploads = st.file_uploader(
        "KRX·HTS 수급 CSV",
        type=["csv"],
        accept_multiple_files=True,
        help=(
            "일자와 외국인·기관 순매수 계약 열이 필요합니다. 종목코드 또는 "
            "기초자산명이 있으면 여러 종목을 한 파일에 넣어도 자동 분리합니다."
        ),
    )
    futures_template = pd.DataFrame({
        "종목코드": ["005930", "005930"],
        "기초자산명": ["삼성전자", "삼성전자"],
        "일자": ["2026-07-28", "2026-07-29"],
        "외국인순매수": [1200, -350],
        "기관순매수": [-400, 600],
        "미결제약정": [105000, 106500],
        "선물종가": [150200, 151000],
    }).to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        "CSV 양식 받기",
        futures_template,
        file_name="stock_futures_flow_template.csv",
        mime="text/csv",
    )
    st.caption(
        "미결제약정·선물종가는 선택 열입니다. KRX 자동조회가 제한되면 "
        "업로드 자료를 우선 사용합니다."
    )
    if st.button("🔄 데이터 새로고침"):
        st.cache_data.clear()
        st.rerun()
    st.caption("장중(한국·미국) 60초 자동 갱신")

kr_now = dt.datetime.now(KST)
kr_open = kr_now.weekday() < 5 and dt.time(8, 30) <= kr_now.time() < dt.time(15, 45)
us_now = dt.datetime.now(_US_TZ)
us_open = us_now.weekday() < 5 and dt.time(9, 0) <= us_now.time() < dt.time(16, 15)
if kr_open or us_open:
    try:
        from streamlit_autorefresh import st_autorefresh
        st_autorefresh(interval=60_000, key="stock-monitor-refresh")
    except Exception:
        pass

uids = list(st.session_state["watchlist_uids"])
if not uids:
    st.info("왼쪽 검색창에서 감시할 종목을 추가하세요.")
    st.stop()

futures_upload_datasets, futures_upload_errors = (
    parse_stock_futures_uploads(futures_flow_uploads)
)
if futures_upload_errors:
    st.warning(
        "개별주식선물 CSV 일부를 읽지 못했습니다: "
        + " / ".join(futures_upload_errors)
    )
kr_stock_count = sum(
    1 for uid in uids if split_uid(uid)[0] == MARKET_KR
)
if kr_stock_count:
    futures_auto_access, futures_auto_status = (
        probe_stock_futures_flow_access()
    )
else:
    futures_auto_access, futures_auto_status = False, "해당 없음"
if futures_upload_datasets:
    st.caption(
        f"개별주식선물 수급 CSV {len(futures_upload_datasets)}개 종목 자료를 "
        "우선 반영합니다."
    )
elif kr_stock_count and not futures_auto_access:
    st.caption(
        f"KRX 개별주식선물 투자자 통계 자동조회 제한({futures_auto_status}) · "
        "필요한 종목의 KRX·HTS CSV를 업로드하면 분석됩니다."
    )

# 시장별 벤치마크는 한 번씩만 수집. 한국은 sosok을 아직 모르므로 둘 다,
# 미국은 S&P500. (실패해도 해당 종목은 상대강도 계산불가로만 처리)
benchmark_cache, benchmark_errors = {}, {}
markets_present = {split_uid(u)[0] for u in uids}
if MARKET_KR in markets_present:
    for name in ("KOSPI", "KOSDAQ"):
        try:
            benchmark_cache[name] = fetch_index_history(name)
        except Exception as exc:
            benchmark_errors[name] = str(exc)
if MARKET_US in markets_present:
    try:
        benchmark_cache["S&P500"] = fetch_sp500_history()
    except Exception as exc:
        benchmark_errors["S&P500"] = str(exc)
if benchmark_errors:
    st.warning(
        "상대강도 기준지수 수집 실패: "
        + " / ".join(f"{k}({v})" for k, v in benchmark_errors.items())
        + " — 해당 시장 종목의 상대강도는 계산불가로 표시됩니다."
    )

empty_benchmark = pd.DataFrame(columns=["close"])
labels = st.session_state["stock_labels"]
analyses, failures = {}, {}
with st.spinner(f"{len(uids)}개 종목 자동 분석..."):
    with ThreadPoolExecutor(max_workers=min(8, len(uids))) as pool:
        future_map = {
            pool.submit(fetch_bundle, uid, labels.get(uid, "")): uid
            for uid in uids
        }
        for future in as_completed(future_map):
            uid = future_map[future]
            market, symbol = split_uid(uid)
            try:
                basic, history, investor, short_selling = future.result()
                stock_futures = pd.DataFrame()
                stock_futures_meta = {
                    "status": "해당 없음",
                    "source": "",
                }
                if market == MARKET_KR:
                    uploaded_match = match_uploaded_stock_futures(
                        futures_upload_datasets,
                        symbol,
                        basic.get("name", labels.get(uid, symbol)),
                        kr_stock_count,
                    )
                    if uploaded_match is not None:
                        stock_futures = uploaded_match["frame"].copy()
                        stock_futures_meta = {
                            "status": "정상",
                            "source": uploaded_match["source"],
                            "filename": uploaded_match["filename"],
                            "product_name": (
                                uploaded_match.get("name")
                                or basic.get("name", symbol)
                            ),
                        }
                    elif futures_auto_access:
                        stock_futures, stock_futures_meta = (
                            fetch_stock_futures_flow_auto(
                                basic.get("name", labels.get(uid, symbol))
                            )
                        )
                    else:
                        stock_futures_meta = {
                            "status": futures_auto_status,
                            "source": "KRX 자동조회",
                        }
                if market == MARKET_US:
                    benchmark_name = "S&P500"
                else:
                    benchmark_name = "KOSPI" if basic["sosok"] == "0" else "KOSDAQ"
                benchmark_df = benchmark_cache.get(benchmark_name, empty_benchmark)
                final_quote = is_final_quote(basic.get("traded_at"), market)
                today_local = market_today(market)
                partial_dropped = (
                    not final_quote
                    and len(history) > 0
                    and history.index[-1].date() == today_local
                )
                conf_hist = apply_confirmed_cut(history, market, final_quote)
                conf_inv = apply_confirmed_cut(investor, market, final_quote)
                conf_futures = apply_confirmed_cut(
                    stock_futures, market, final_quote
                )
                result = evaluate_stock(
                    basic, conf_hist, conf_inv, short_selling,
                    conf_futures, stock_futures_meta,
                    benchmark_df, benchmark_name,
                )
                result["uid"] = uid
                result["symbol"] = symbol
                result["final_quote"] = final_quote
                result["partial_dropped"] = partial_dropped
                result["live_stage"] = None
                if partial_dropped:
                    try:
                        live = evaluate_stock(
                            basic, history, investor, short_selling,
                            stock_futures, stock_futures_meta,
                            benchmark_df, benchmark_name,
                        )
                        if live["stage"] != result["stage"]:
                            result["live_stage"] = live["stage"]
                    except Exception:
                        pass
                if result["basic"].get("price") is None and len(conf_hist):
                    result["basic"]["price"] = float(conf_hist["close"].iloc[-1])
                analyses[uid] = result
            except Exception as exc:
                failures[uid] = str(exc)

if failures:
    st.warning(
        "분석 제외: "
        + " / ".join(f"{code}({message})" for code, message in failures.items())
    )
if not analyses:
    st.error("분석 가능한 종목이 없습니다.")
    st.stop()

summary_rows = []
for uid, result in analyses.items():
    market, symbol = split_uid(uid)
    basic = result["basic"]
    entry = result["entry"]
    flow = result["flow"]
    futures_flow = result["futures_flow"]
    short_pressure = result["short_pressure"]
    if basic["name"] != symbol:
        st.session_state["stock_labels"][uid] = basic["name"]
    flag = "🇰🇷" if market == MARKET_KR else "🇺🇸"
    live_stage = result.get("live_stage")
    pl = entry["pullback_low"]
    ph = entry["pullback_high"]
    summary_rows.append({
        "우선순위": STAGE_RANK[result["stage"]],
        "_score": entry["score"],
        "시장": flag,
        "종목": basic["name"],
        "심볼": symbol,
        "단계": f"{STAGE_ICON[result['stage']]} {result['stage']}",
        "장중잠정": (f"{STAGE_ICON[live_stage]} {live_stage}" if live_stage else ""),
        "매수판정": entry["status"],
        "진입점수": entry["score"],
        "현재가": basic["price"],
        "등락률(%)": basic["change_pct"],
        "눌림목 가격": f"{_money(pl, market)}~{_money(ph, market)}",
        "돌파가격": _money(entry["breakout_trigger"], market),
        "진입취소선": _money(entry["entry_cancel"], market),
        "현물 외·기 수급": flow["label"],
        "선물 외·기 수급": (
            futures_flow["label"]
            if futures_flow["available"]
            else "데이터 없음" if market == MARKET_KR
            else "해당없음"
        ),
        "공매도": short_pressure["label"],
        "RSI14": result["rsi"],
        "지수대비20일(%p)": result["rs20"],
    })

summary = (
    pd.DataFrame(summary_rows)
    .sort_values(["_score", "우선순위"], ascending=[False, True])
    .drop(columns=["우선순위", "_score"])
)
if (summary["장중잠정"] == "").all():
    summary = summary.drop(columns=["장중잠정"])

st.subheader("전체 감시판 · 매수 타이밍 우선")
st.dataframe(
    summary,
    width="stretch",
    hide_index=True,
    column_config={
        "현재가": st.column_config.NumberColumn(format="localized"),
        "등락률(%)": st.column_config.NumberColumn(format="%+.2f"),
        "진입점수": st.column_config.ProgressColumn(
            min_value=0, max_value=100, format="%d",
        ),
        "RSI14": st.column_config.NumberColumn(format="%.1f"),
        "지수대비20일(%p)": st.column_config.NumberColumn(format="%+.2f"),
    },
)
st.caption(
    "정렬: 진입점수 내림차순 · 현재가·등락률은 실시간, 단계 판정은 시장별 확정 "
    "종가 기준 · 상대강도는 한국 KOSPI·KOSDAQ / 미국 S&P500 · 개별주식선물 "
    "수급은 데이터가 있을 때만 10점 비중으로 반영"
)

options = [uid for uid in uids if uid in analyses]
selected_uid = st.selectbox(
    "상세 분석 종목",
    options,
    format_func=lambda uid: (
        f"{('🇰🇷' if split_uid(uid)[0] == MARKET_KR else '🇺🇸')} "
        f"{analyses[uid]['basic']['name']} ({split_uid(uid)[1]})"
    ),
)
selected = analyses[selected_uid]
sel_market, sel_symbol = split_uid(selected_uid)
sel_meta = MARKET_META[sel_market]
basic = selected["basic"]
history = selected["history"]
entry = selected["entry"]
flow = selected["flow"]
futures_flow = selected["futures_flow"]
short_pressure = selected["short_pressure"]
sel_flag = "🇰🇷" if sel_market == MARKET_KR else "🇺🇸"

st.divider()
st.subheader(
    f"{sel_flag} {STAGE_ICON[selected['stage']]} {basic['name']} "
    f"({sel_symbol}) · {selected['stage']} · {entry['status']}"
)

close_label = sel_meta["close_time"].strftime("%H:%M")
if selected["final_quote"]:
    anchor_note = f"판정 기준: 확정 종가 (당일 마감 반영)"
elif selected["partial_dropped"]:
    anchor_note = (
        f"판정 기준: 확정 종가 · 장중 당일 캔들 제외, 현지 {close_label} 이후 반영"
    )
else:
    anchor_note = "판정 기준: 확정 종가 (직전 거래일)"
st.caption(anchor_note)

m1, m2, m3, m4, m5, m6, m7 = st.columns(7)
m1.metric(
    "현재가",
    _money(basic["price"], sel_market),
    f"{basic['change_pct']:+.2f}%" if basic["change_pct"] is not None else None,
)
m2.metric("추세 단계", selected["stage"])
m3.metric("진입점수", f"{entry['score']}/100")
m4.metric(
    "현물 외·기 수급",
    flow["label"] if sel_meta["has_investor_flow"] else "해당없음",
)
m5.metric(
    "선물 외·기 수급",
    futures_flow["label"]
    if futures_flow["available"]
    else "데이터 없음" if sel_market == MARKET_KR
    else "해당없음",
)
m6.metric(
    "공매도 압력",
    short_pressure["label"]
    if sel_meta["has_short_selling"]
    else "해당없음",
)
m7.metric(
    f"{selected['benchmark_name']} 대비 20일",
    f"{selected['rs20']:+.2f}%p" if pd.notna(selected["rs20"]) else "—",
)
if selected.get("live_stage"):
    st.info(
        f"장중 잠정(당일 캔들 포함 시): {STAGE_ICON[selected['live_stage']]} "
        f"{selected['live_stage']} — 현지 {close_label} 확정 후 반영됩니다."
    )

entry_message = f"{entry['status']} — {entry['reason']}"
if entry["status"].startswith("🟢"):
    st.success(entry_message)
else:
    st.warning(entry_message)

st.markdown("### 매수 타이밍·가격")
p1, p2, p3, p4, p5 = st.columns(5)
p1.metric("분석 기준 종가", _money(history["close"].iloc[-1], sel_market))
p2.metric(
    "눌림목 검토구간",
    f"{_money(entry['pullback_low'], sel_market)}~"
    f"{_money(entry['pullback_high'], sel_market)}",
)
p3.metric("돌파 확인가격", _money(entry["breakout_trigger"], sel_market))
p4.metric("눌림 진입취소선", _money(entry["entry_cancel"], sel_market))
p5.metric("MA20 추세선", _money(entry["trend_invalidation"], sel_market))

st.markdown(f"**매수 확인 조건:** {entry['buy_condition']}")
st.markdown(f"**취소·재판정 조건:** {entry['cancel_condition']}")
st.caption(
    "진입 가능 판정이어도 한 번에 전액 매수하지 않고 1차 20~30%만 탐색한 뒤, "
    "종가 확인과 수급 지속 여부에 따라 나눠 확인하는 기준입니다."
)

component_row = {
    key: f"{value}/{entry['component_max'][key]}"
    for key, value in entry["components"].items()
}
st.dataframe(
    pd.DataFrame([component_row], index=["진입점수 구성"]),
    width="stretch",
)
if sel_market == MARKET_US:
    st.caption(
        "미국 종목은 현물 외국인·기관 구분 수급과 공매도가 중립값(각 10·8점), "
        "개별주식선물 수급은 점수 구성에서 제외됩니다. 추세·가격·거래량 "
        "중심으로 보세요."
    )

st.info(selected["action"])
if selected["overheat"]:
    st.warning("과열·추격주의: " + " / ".join(selected["overheat"]))

if not sel_meta["has_investor_flow"]:
    st.markdown("### 외국인·기관 매수/매도 줄다리기")
    st.info("미국 종목은 외국인·기관 수급 구분 데이터가 없어 표시하지 않습니다.")
elif flow["available"]:
    st.markdown("### 외국인·기관 매수/매도 줄다리기")
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

st.markdown("### 개별주식선물 외국인·기관 수급")
if not sel_meta["has_stock_futures_flow"]:
    st.info("미국 종목은 KRX 개별주식선물 수급 분석 대상이 아닙니다.")
elif futures_flow["available"]:
    ff1, ff2, ff3, ff4, ff5 = st.columns(5)
    ff1.metric("5일 수급", futures_flow["label"])
    ff2.metric("선물 수급점수", f"{futures_flow['score']}/100")
    ff3.metric(
        "외국인 5일",
        f"{futures_flow['foreign5']:+,.0f}계약",
    )
    ff4.metric(
        "기관 5일",
        f"{futures_flow['institution5']:+,.0f}계약",
    )
    ff5.metric(
        "미결제약정 변화",
        (
            f"{futures_flow['oi_change_pct']:+.2f}%"
            if futures_flow["oi_available"]
            else "자료 없음"
        ),
    )
    futures_table = pd.DataFrame([
        {
            "주체": "외국인",
            "최근 5일(계약)": futures_flow["foreign5"],
            "최근 10일(계약)": futures_flow["foreign10"],
            "최근 변화": futures_flow["foreign_momentum"],
        },
        {
            "주체": "기관",
            "최근 5일(계약)": futures_flow["institution5"],
            "최근 10일(계약)": futures_flow["institution10"],
            "최근 변화": futures_flow["institution_momentum"],
        },
        {
            "주체": "합계",
            "최근 5일(계약)": futures_flow["combined5"],
            "최근 10일(계약)": futures_flow["combined10"],
            "최근 변화": _flow_momentum(
                selected["stock_futures"]["foreign"]
                + selected["stock_futures"]["institution"]
            ),
        },
    ])
    fc1, fc2 = st.columns([1, 2])
    with fc1:
        st.metric("포지션 해석", futures_flow["position_label"])
        price_change_text = (
            f"{futures_flow['price_change_pct']:+.2f}%"
            if pd.notna(futures_flow["price_change_pct"])
            else "—"
        )
        st.metric(
            f"5일 {futures_flow['price_source']} 가격 변화",
            price_change_text,
        )
    with fc2:
        st.dataframe(
            futures_table,
            width="stretch",
            hide_index=True,
            column_config={
                "최근 5일(계약)": st.column_config.NumberColumn(
                    format="%+,.0f"
                ),
                "최근 10일(계약)": st.column_config.NumberColumn(
                    format="%+,.0f"
                ),
            },
        )
    futures_chart = (
        selected["stock_futures"][["foreign", "institution"]]
        .tail(20)
        .rename(columns={"foreign": "외국인", "institution": "기관"})
    )
    st.bar_chart(futures_chart, height=220)
    st.info(futures_flow["interpretation"])
    source = futures_flow.get("source") or "출처 확인불가"
    product = futures_flow.get("product_name") or basic["name"]
    latest = futures_flow["latest_date"]
    filename = futures_flow.get("filename")
    st.caption(
        f"기초자산·상품: {product} · 최근 반영일: "
        f"{latest.strftime('%Y-%m-%d')} · 출처: {source}"
        + (f" ({filename})" if filename else "")
    )
else:
    status = futures_flow.get("status") or "응답 없음"
    st.info(
        f"개별주식선물 수급 데이터 없음 ({status}). KRX·HTS에서 일자, "
        "외국인 순매수, 기관 순매수 계약이 포함된 CSV를 내려받아 왼쪽 "
        "업로더에 넣으면 분석과 진입점수에 반영됩니다."
    )

if not sel_meta["has_short_selling"]:
    st.markdown("### 공매도 압력")
    st.info(
        "미국은 일별 공매도 데이터가 없습니다(FINRA 월 2회 지연 공시). "
        "공매도 항목은 진입점수에서 중립으로 처리됩니다."
    )
elif short_pressure["available"]:
    st.markdown("### KRX 공매도 압력")
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
    stale_note = (
        " · ⚠️ 거래일과 잔고 공시일 간극이 커 잔고 변화 가중을 절반으로 낮췄습니다"
        if short_pressure.get("balance_stale")
        else ""
    )
    st.caption(
        "공매도 거래 최근일 "
        f"{trade_date.strftime('%Y-%m-%d') if trade_date is not None else '—'} · "
        "잔고 공시 최근일 "
        f"{balance_date.strftime('%Y-%m-%d') if balance_date is not None else '—'} · "
        "KRX+NXT 전체 당일 거래는 통상 18:10 이후, 공매도 잔고는 T+2 지연 반영"
        + stale_note
    )
else:
    st.markdown("### KRX 공매도 압력")
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

if sel_meta["has_krx_confirm"]:
    krx = fetch_krx_confirmation(krx_auth_key, sel_symbol, basic.get("sosok", ""))
    if krx.get("status") == "정상":
        st.success(
            f"KRX 공식 확정치 대조 정상 · {krx['date']} 종가 "
            f"{krx['close']:,.0f}원 / 등락률 {krx['change_pct']:+.2f}%"
        )
    else:
        st.caption(f"KRX 공식 확정치: {krx.get('status', '확인불가')}")
else:
    st.caption("미국 종목: 야후 파이낸스 수정주가 기준 (KRX 대조 없음)")

source_note = (
    "네이버 장중/일봉·현물 투자자 수급, KRX/HTS 개별주식선물 수급, "
    "KRX 공매도 통계와 확정 일별 통계를 대조·가공"
    if sel_market == MARKET_KR
    else "야후 파이낸스 v8 chart(수정주가)를 가공"
)
st.caption(
    f"장중 기준시각: {basic['traded_at'] or '확인불가'} · {source_note}했습니다."
)
st.caption(
    "⚠️ 표시 가격은 확정 수익을 보장하는 목표가가 아니라 조건부 관찰선입니다. "
    "이 도구는 투자 권유·자동주문이 아니며 종가 확정 전 장중 판정은 바뀔 수 있습니다."
)
