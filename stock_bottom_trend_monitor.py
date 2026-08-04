# -*- coding: utf-8 -*-
"""
개별종목 바닥확인 → 상승추세·매수구간 분석기 v3.6
========================================
2026-08-05 v3.5 감사·수정. v3.5 → v3.6 주요 변경:

  [크래시 제거]
  1. KRX 확정치 종가·등락률이 None일 때 f-string 포맷이 TypeError로
     페이지 전체를 중단시키던 문제 수정. 동시에 "대조 정상"이라 표기만
     하고 실제 대조를 하지 않던 부분을 네이버 일봉 실대조로 복원.
  2. 날짜 표기를 fmt_date로 통일. pd.NaT는 `is not None` 검사를
     통과한 뒤 strftime에서 ValueError를 내므로 전용 헬퍼로 차단.
  3. apply_confirmed_cut이 DatetimeIndex가 아닌 프레임에서
     AttributeError를 내던 문제를 인덱스 강제 변환으로 방지.

  [판정 오류]
  4. 업로드 선물 CSV 오적용 차단 — 종목코드·종목명이 명시된 자료는
     현재 종목과 일치할 때만 쓰고, 식별정보가 전혀 없는 자료만
     현재 종목에 적용한다. 불일치 자료는 화면에 사유를 표시한다.
  5. 진입점수 가중치 재배분을 "선물 수급(외국인·기관 순매수)이 실제로
     있을 때"로 한정. 선물 시세·OI만 있는데도 현물수급 20→15,
     공매도 15→10으로 깎이던 문제 수정.
  6. RSI14가 14일 내내 하락이 없으면 NaN이 되어 과열 경고·RSI 신호가
     모두 침묵하던 문제 수정(하락 0 → RSI 100, 무변동 → 50).
  7. 단계 임계값을 신호 개수에 비례(바닥 50%·상승 60%)하도록 통일.
     신호가 늘수록 문턱 비율이 낮아지던 비단조성 제거.
  8. "RSI 과매도 반등" 두 번째 조건에 상한(<70)을 부여. 첫 조건에만
     상한 60이 있어 RSI 90에서도 통과하던 비대칭 제거.
  9. 진입점수를 시장별 적용 가능 축으로 정규화. 미국은 현물수급·
     공매도 축이 구조적으로 없어 최대 83점에 갇혀 있었고, 임계값
     70/65/55는 시장 공통이라 불리하게 왜곡됐다.

  [표시·정합성]
  10. NumberColumn format="%+,.0f"는 sprintf 규격에 쉼표 플래그가
      없어 렌더 오류를 낸다. 문자열 사전 포맷으로 대체.
  11. 자동수집이 제거된 v3.5 이후에도 남아 있던 "업로드가 자동조회보다
      우선" 등 사실과 다른 안내문 수정.
  12. CSV 병합 우선순위를 공매도·선물 모두 "나중 파일 우선"으로 통일.
  13. 일자 파싱 시 시각 성분을 제거(normalize)해 현물 거래량 조인이
      조용히 실패하던 경로 차단.
  14. 업로드 CSV를 dtype=str로 읽어 종목코드 "000660"이 정수 660으로
      바뀌며 6자리 매칭이 실패하던 문제 수정. 잘린 앞자리 0 복원과
      ISIN(KR7…) 형식 인식을 _normalize_stock_code로 통합.

2026-07-30 단일 종목·공매도 CSV 분석. v3.4 → v3.5 주요 변경:

  [변경 · 종목 한 개씩 분석]
  A. 최대 20개 감시목록과 전체 감시판을 제거하고 검색에서 선택한 종목
     한 개만 수집·분석·표시한다.
  B. 선물 CSV와 KRX 개별종목 공매도 종합정보 CSV를 현재 종목에 바로
     적용하며 여러 기간 파일은 일자를 기준으로 자동 병합한다.
  C. 공매도 자동수집은 사용하지 않고 CSV가 없으면 중립, 업로드하면
     공매도 거래량·거래대금·업틱룰·순보유잔고를 분석한다.

2026-07-30 KRX 공매도 Streamlit 403 우회. v3.3 → v3.4 주요 변경:

  [수정 · 공매도 ISIN 조회 403 제거]
  A. 배포 앱에서 확인된 finder_stkisu HTTP 403을 피하도록 KRX 공식
     주식 Open API의 ISIN을 우선 사용하고 보통주는 ISO 6166 규칙으로
     ISIN을 자체 생성해 공매도 종합정보를 직접 요청한다.
  B. KRX Data Marketplace 요청 헤더를 현재 pykrx 방식의 outerLoader
     Referer로 맞추고 네이버 간편로그인 비밀번호 입력 금지를 명시한다.

2026-07-30 KRX 공식 API 자동수집 수정. v3.2 → v3.3 주요 변경:

  [수정 · KRX 공식 파생 API와 공매도 실패 진단]
  A. KOSPI/KOSDAQ 개별주식선물 일별 시세를 KRX Open API의
     eqsfu_stk_bydd_trd/eqkfu_ksq_bydd_trd에서 직접 수집한다.
  B. 공식 응답의 현물가격·선물종가·거래량·미결제약정으로 베이시스와
     가격×OI를 계산하며, 거래량이 가장 큰 활성월물을 일관되게 추적한다.
  C. 공매도 Data Marketplace 호출의 잘못된 _OUT 경로를 수정하고
     로그인·권한·응답형식 오류를 숨기지 않고 화면에 구체적으로 표시한다.

2026-07-29 현·선물 통합 분석판. v3.1 → v3.2 주요 변경:

  [신규 · Hull 기반 현·선물 통합 분석]
  A. Hull의 정의에 따라 베이시스를 현물-선물(S-F)로 통일하고
     선물가격·거래량·미결제약정·만기까지 남은 기간을 함께 분석한다.
  B. 가격×미결제약정으로 신규계약/청산 가능성을 추정하되, 미결제약정의
     롱·숏 총수는 항상 같다는 한계를 명시하고 만기 롤오버를 별도 경고한다.
  C. 현물 외국인·기관, 개별주식선물, KOSPI200 지수선물, 공매도,
     가격추세·RSI·상대강도·OBV·ATR을 교차 검증하는 종합 근거표를 제공한다.
  D. KRX의 CP949/EUC-KR, 구분자 차이, 제목행, 2단 헤더를 자동 탐지하고
     여러 CSV의 수급·가격·거래량·미결제약정 열을 종목·일자별로 병합한다.

  [v3.1 · 개별주식선물 외국인/기관 수급]
  E. 한국 종목은 KRX 주식선물 상품을 자동 매칭하고 외국인·기관의
     일별 순매수 계약을 현물 수급과 분리해 분석한다.
  F. KRX 투자자별 파생상품 통계가 로그인 응답으로 제한되는 환경을
     위해 KRX/HTS 내보내기 CSV 업로드를 지원한다. 종목코드·일자와
     외국인/기관 순매수 열을 자동 인식한다.
  G. 미결제약정·선물종가가 함께 있으면 가격×미결제약정 조합으로
     신규 롱, 숏커버, 신규 숏, 롱청산 가능성을 표시한다. 미결제약정이
     없으면 신규 포지션과 청산을 구분할 수 없다고 명시한다.
  H. 선물 수급이 있을 때 진입점수 100점 안에서 현물수급·공매도
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

    KRX_AUTH_KEY = "발급받은 인증키"        # 종가·주식선물 Open API
    KRX_ID = "data.krx.co.kr 아이디"         # 공매도 로그인 요구 시(선택)
    KRX_PW = "data.krx.co.kr 비밀번호"       # 공매도 로그인 요구 시(선택)
    WATCHLIST = "KR:005930,KR:000660,US:NVDA,US:AVGO"

실행:
    streamlit run stock_bottom_trend_monitor.py
"""

import datetime as dt
import difflib
from io import BytesIO, StringIO
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
    page_title="개별종목 바닥·상승추세 분석기",
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


def fmt_date(value, empty: str = "—", pattern: str = "%Y-%m-%d"):
    """날짜 표기 통일. None·NaT·파싱 실패는 모두 empty로 (v3.6 #2).

    pd.NaT는 `is not None`을 통과한 뒤 strftime에서 ValueError를 내므로
    호출부마다 None 검사만 하면 화면 전체가 죽는다.
    """
    if value is None:
        return empty
    try:
        stamp = pd.Timestamp(value)
    except (TypeError, ValueError):
        return empty
    if pd.isna(stamp):
        return empty
    return stamp.strftime(pattern)


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
    """공식 판정용 앵커. 마감 확정 전에는 당일(현지) 행을 제외한다.

    v3.6 #3: 인덱스가 DatetimeIndex가 아니면 `.date` 접근에서
    AttributeError가 났다. 변환 불가하면 원본을 그대로 돌려준다.
    """
    if frame is None or frame.empty or final:
        return frame
    index = frame.index
    if not isinstance(index, pd.DatetimeIndex):
        converted = pd.to_datetime(index, errors="coerce")
        if not isinstance(converted, pd.DatetimeIndex) or converted.isna().all():
            return frame
        frame = frame.set_axis(converted)
    cutoff = pd.Timestamp(market_today(market))
    keep = frame.index.notna() & (frame.index.normalize() < cutoff)
    return frame[keep]


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
    text = re.sub(r"(?:f|선물)?20\d{4}$", "", text)
    text = re.sub(r"\d{4,6}$", "", text)
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
    merged = parsed.fillna(fallback)
    # v3.6 #13: 시각 성분이 남으면 일봉 인덱스와 조인이 조용히 실패한다.
    return merged.dt.normalize()


def _standardize_stock_futures_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """KRX/HTS CSV를 선물수급·가격·거래량·OI 공통 포맷으로 바꾼다."""
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
        raise ValueError(
            "일자 열을 찾지 못했습니다. KRX 조회구분을 '기간합계'가 아닌 "
            "'일별추이'로 선택해 내려받으세요"
        )

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
    foreign_buy_col = _find_column(
        columns,
        lambda c: (
            "외국인" in c and "매수" in c
            and "순매수" not in c and "순매매" not in c
        ),
    )
    foreign_sell_col = _find_column(
        columns,
        lambda c: "외국인" in c and "매도" in c,
    )
    institution_buy_col = _find_column(
        columns,
        lambda c: (
            "기관" in c and "매수" in c
            and "순매수" not in c and "순매매" not in c
        ),
    )
    institution_sell_col = _find_column(
        columns,
        lambda c: "기관" in c and "매도" in c,
    )

    dates = _date_series(frame[date_col])
    flow_frame = pd.DataFrame(index=dates)
    flow_frame.index.name = "date"
    has_flow = False

    if foreign_col is not None or institution_col is not None:
        flow_frame["foreign"] = (
            _numeric_series(frame[foreign_col]).to_numpy()
            if foreign_col is not None
            else 0.0
        )
        flow_frame["institution"] = (
            _numeric_series(frame[institution_col]).to_numpy()
            if institution_col is not None
            else 0.0
        )
        has_flow = True
    elif (
        foreign_buy_col is not None and foreign_sell_col is not None
    ) or (
        institution_buy_col is not None
        and institution_sell_col is not None
    ):
        flow_frame["foreign"] = (
            (
                _numeric_series(frame[foreign_buy_col])
                - _numeric_series(frame[foreign_sell_col])
            ).to_numpy()
            if foreign_buy_col is not None
            and foreign_sell_col is not None
            else np.zeros(len(frame))
        )
        flow_frame["institution"] = (
            (
                _numeric_series(frame[institution_buy_col])
                - _numeric_series(frame[institution_sell_col])
            ).to_numpy()
            if institution_buy_col is not None
            and institution_sell_col is not None
            else np.zeros(len(frame))
        )
        has_flow = True
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
        buy_col = _find_column(
            columns,
            lambda c: (
                (
                    "매수" in c
                    and "순매수" not in c
                    and "순매매" not in c
                )
                or c in {"buy", "buyqty", "매수량", "매수거래량"}
            ),
        )
        sell_col = _find_column(
            columns,
            lambda c: (
                "매도" in c
                or c in {"sell", "sellqty", "매도량", "매도거래량"}
            ),
        )
        if investor_col is not None and (
            net_col is not None or (buy_col is not None and sell_col is not None)
        ):
            net_values = (
                _numeric_series(frame[net_col])
                if net_col is not None
                else (
                    _numeric_series(frame[buy_col])
                    - _numeric_series(frame[sell_col])
                )
            )
            long = pd.DataFrame({
                "date": dates,
                "investor": frame[investor_col].astype(str),
                "net": net_values,
            }).dropna(subset=["date", "net"])
            investor_compact = long["investor"].map(_compact_text)
            foreign_total_tokens = {"외국인", "외국인합계", "외국인계"}
            institution_total_tokens = {
                "기관", "기관합계", "기관계", "기관투자자"
            }
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
            if not long.empty:
                flow_frame = (
                    long.pivot_table(
                        index="date", columns="type", values="net",
                        aggfunc="sum",
                    )
                    .rename_axis(None, axis=1)
                )
                for required in ("foreign", "institution"):
                    if required not in flow_frame:
                        flow_frame[required] = 0.0
                has_flow = True

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
    spot_close_col = _find_column(
        columns,
        lambda c: (
            (
                ("현물" in c or "기초자산" in c)
                and ("종가" in c or "가격" in c)
            )
            or c in {"현물종가", "기초자산종가", "spotclose"}
        ),
    )
    if futures_close_col is None:
        futures_close_col = _find_column(
            columns,
            lambda c: (
                c in {"종가", "현재가", "close", "price"}
                and c != _compact_text(spot_close_col)
            ),
        )
    futures_volume_col = _find_column(
        columns,
        lambda c: (
            c in {
                "거래량", "약정수량", "거래계약수", "volume",
                "tradingvolume", "acctradvol",
            }
            or (
                ("거래량" in c or "약정수량" in c)
                and "매수" not in c
                and "매도" not in c
            )
        ),
    )
    theoretical_price_col = _find_column(
        columns,
        lambda c: (
            c in {
                "이론가", "이론가격", "theoreticalprice",
                "theoreticalfuturesprice",
            }
            or ("이론" in c and ("가격" in c or c.endswith("가")))
        ),
    )
    basis_pct_col = _find_column(
        columns,
        lambda c: (
            "베이시스율" in c
            or c in {"basispct", "basispercent", "basisrate"}
        ),
    )
    basis_col = _find_column(
        columns,
        lambda c: (
            ("시장베이시스" in c or c in {"베이시스", "basis"})
            and "이론" not in c
            and "율" not in c
        ),
    )
    expiry_col = _find_column(
        columns,
        lambda c: (
            c in {
                "만기일", "최종거래일", "결제일", "expiration",
                "expiry", "expirydate",
            }
            or c.endswith("만기일")
        ),
    )

    extras = pd.DataFrame(index=dates)
    if oi_col is not None:
        extras["open_interest"] = _numeric_series(frame[oi_col]).to_numpy()
    if futures_close_col is not None:
        extras["futures_close"] = _numeric_series(
            frame[futures_close_col]
        ).to_numpy()
    if spot_close_col is not None:
        extras["spot_close"] = _numeric_series(
            frame[spot_close_col]
        ).to_numpy()
    if futures_volume_col is not None:
        extras["futures_volume"] = _numeric_series(
            frame[futures_volume_col]
        ).to_numpy()
    if theoretical_price_col is not None:
        extras["theoretical_price"] = _numeric_series(
            frame[theoretical_price_col]
        ).to_numpy()
    if basis_col is not None:
        extras["reported_basis"] = _numeric_series(
            frame[basis_col]
        ).to_numpy()
    if basis_pct_col is not None:
        extras["reported_basis_pct"] = _numeric_series(
            frame[basis_pct_col]
        ).to_numpy()
    if expiry_col is not None:
        extras["expiry_date"] = _date_series(
            frame[expiry_col]
        ).to_numpy()

    if not has_flow and extras.empty:
        raise ValueError(
            "외국인·기관 수급, 선물종가, 거래량, 미결제약정 또는 "
            "베이시스 열을 찾지 못했습니다"
        )

    if has_flow:
        flow_frame = flow_frame[~flow_frame.index.isna()]
        standardized = (
            flow_frame[["foreign", "institution"]]
            .groupby(level=0)
            .sum(min_count=1)
            .sort_index()
        )
    else:
        standardized = pd.DataFrame()
    if not extras.empty:
        extras = extras[~extras.index.isna()].groupby(level=0).last()
        standardized = (
            extras
            if standardized.empty
            else standardized.join(extras, how="outer")
        )
    if {"foreign", "institution"}.issubset(standardized.columns):
        standardized[["foreign", "institution"]] = standardized[
            ["foreign", "institution"]
        ].fillna(0.0)
    return standardized


def _normalize_stock_code(value) -> str:
    """종목코드 문자열에서 6자리 단축코드를 뽑는다.

    v3.6 #14: 엑셀·CSV가 "000660"을 660으로 저장한 경우까지 살린다.
    앞자리 0이 잘린 6자리 이하 순수 숫자는 zfill로 복원한다.
    """
    text = str(value or "").strip().upper()
    if not text or text in ("NAN", "NONE"):
        return ""
    isin = re.fullmatch(r"KR[0-9A-Z](\d{6})\d{3}", text)
    if isin:
        return isin.group(1)
    match = re.search(r"(?<!\d)(\d{6})(?!\d)", text)
    if match:
        return match.group(1)
    if text.startswith("A") and text[1:].isdigit() and len(text) <= 7:
        return text[1:].zfill(6)
    digits = re.sub(r"[^0-9]", "", text)
    if digits and len(digits) <= 6 and digits == text:
        return digits.zfill(6)
    return ""


def _extract_stock_code(series: pd.Series):
    values = []
    for value in series.dropna().astype(str):
        code = _normalize_stock_code(value)
        if code:
            values.append(code)
    unique = list(dict.fromkeys(values))
    return unique[0] if len(unique) == 1 else ""


def _flatten_csv_columns(columns) -> list:
    flattened = []
    for column in columns:
        parts = column if isinstance(column, tuple) else (column,)
        clean_parts = []
        for part in parts:
            text = str(part).strip()
            if not text or text.lower().startswith("unnamed"):
                continue
            if text not in clean_parts:
                clean_parts.append(text)
        flattened.append(" ".join(clean_parts) or "Unnamed")
    return flattened


def _csv_structure_score(frame: pd.DataFrame) -> int:
    if frame is None or frame.empty or len(frame.columns) < 2:
        return -100
    columns = [_compact_text(col) for col in frame.columns]
    score = 0
    for column in columns:
        if (
            column in {"일자", "날짜", "기준일", "거래일", "거래일자"}
            or column.endswith("일자")
            or column in {"trddd", "basdd", "date"}
        ):
            score += 15
        if "외국" in column:
            score += 5
        if "기관" in column or "투자자" in column:
            score += 5
        if "순매수" in column or "순매매" in column:
            score += 4
        if "매수" in column or "매도" in column:
            score += 1
        if "미결제약정" in column:
            score += 6
        if "베이시스" in column:
            score += 6
        if "종가" in column or "가격" in column:
            score += 3
        if "거래량" in column or "약정수량" in column:
            score += 3
        if "종목명" in column or "기초자산명" in column:
            score += 2
        if "공매도" in column:
            score += 5
        if "업틱룰" in column:
            score += 3
        if "잔고" in column:
            score += 5
        if column.startswith("unnamed"):
            score -= 1
    return score


@st.cache_data(ttl=3600, show_spinner=False)
def _read_uploaded_csv_bytes(raw: bytes):
    """KRX의 인코딩·구분자·제목행·다단 헤더 차이를 자동 탐색한다."""
    if not raw:
        raise ValueError("빈 파일입니다")
    head = raw[:4096].lower()
    if b"<html" in head or b"<!doctype" in head:
        raise ValueError(
            "CSV가 아니라 KRX 로그인/오류 HTML입니다. KRX 화면에서 "
            "조회 완료 후 다시 다운로드하세요"
        )

    best_frame, best_score, last_error = None, -1000, None
    encodings = ("utf-8-sig", "cp949", "euc-kr", "utf-8")
    selected_encoding = ""
    for encoding in encodings:
        try:
            preview = raw[:8192].decode(encoding)
            selected_encoding = encoding
            break
        except UnicodeDecodeError as exc:
            last_error = exc
    if not selected_encoding:
        raise ValueError(f"CSV 문자 인코딩을 읽지 못했습니다: {last_error}")

    counts = {
        separator: preview.count(separator)
        for separator in (",", "\t", ";", "|")
    }
    separators = [
        separator
        for separator, count in sorted(
            counts.items(), key=lambda item: item[1], reverse=True
        )
        if count > 0
    ][:2] or [","]
    for separator in separators:
        for header in range(0, 7):
            header_options = (
                header,
                [header, header + 1],
                [header, header + 1, header + 2],
            )
            for header_option in header_options:
                try:
                    candidate = pd.read_csv(
                        BytesIO(raw),
                        encoding=selected_encoding,
                        sep=separator,
                        header=header_option,
                        on_bad_lines="skip",
                        # v3.6 #14: dtype 추론에 맡기면 종목코드 "000660"이
                        # 정수 660이 되어 6자리 매칭이 실패한다. 하위 변환은
                        # 모두 문자열을 받으므로 전부 문자열로 읽는다.
                        dtype=str,
                    )
                    candidate.columns = _flatten_csv_columns(
                        candidate.columns
                    )
                    candidate = candidate.dropna(how="all")
                    score = _csv_structure_score(candidate)
                    if score > best_score:
                        best_frame, best_score = candidate, score
                except Exception as exc:
                    last_error = exc
    if best_frame is not None and best_score >= 8:
        return best_frame
    raise ValueError(
        "CSV 열 구조를 판별하지 못했습니다"
        + (f": {last_error}" if last_error else "")
    )


def _read_uploaded_csv(uploaded_file):
    return _read_uploaded_csv_bytes(uploaded_file.getvalue()).copy()


def _standardize_short_selling_frame(frame: pd.DataFrame):
    """KRX 공매도 종합정보 CSV를 자동수집 자료와 같은 열로 변환한다."""
    if frame is None or frame.empty:
        return pd.DataFrame()
    frame = frame.copy()
    frame.columns = [str(column).strip() for column in frame.columns]
    columns = list(frame.columns)

    date_col = _find_column(
        columns,
        lambda c: c in {
            "일자", "날짜", "기준일", "거래일", "거래일자",
            "date", "trddd", "basdd",
        } or c.endswith("일자"),
    )
    if date_col is None:
        raise ValueError("일자 열을 찾지 못했습니다")

    short_volume_col = _find_column(
        columns,
        lambda c: (
            c in {
                "공매도거래량", "공매도수량", "전체공매도거래량",
                "shortvolume", "shortsellingvolume", "cvssrtelltrdvol",
                "cvssrtselltrdvol",
            }
            or (
                "공매도" in c
                and ("거래량" in c or "거래수량" in c)
                and "잔고" not in c
                and "업틱" not in c
            )
            or (
                "공매도수량" in c
                and "잔고" not in c
                and "업틱" not in c
            )
        ),
    )
    uptick_col = _find_column(
        columns,
        lambda c: (
            c in {"업틱룰적용", "업틱룰적용거래량", "uptickvolume"}
            or (
                "업틱룰적용" in c
                and ("거래량" in c or "수량" in c)
            )
        ),
    )
    exception_col = _find_column(
        columns,
        lambda c: (
            c in {"업틱룰예외", "업틱룰예외거래량", "exceptionvolume"}
            or (
                "업틱룰예외" in c
                and ("거래량" in c or "수량" in c)
            )
        ),
    )
    balance_col = _find_column(
        columns,
        lambda c: (
            c in {
                "공매도잔고수량", "순보유잔고수량", "잔고수량",
                "shortbalance", "shortbalanceqty", "strconstval1",
            }
            or (
                "잔고" in c
                and ("수량" in c or "순보유" in c)
                and "금액" not in c
            )
        ),
    )
    short_value_col = _find_column(
        columns,
        lambda c: (
            c in {
                "공매도거래대금", "공매도금액", "shortvalue",
                "shortsellingvalue", "cvssrtselltrdval",
            }
            or (
                "공매도" in c
                and ("거래대금" in c or "거래금액" in c)
                and "잔고" not in c
                and "업틱" not in c
            )
        ),
    )
    balance_value_col = _find_column(
        columns,
        lambda c: (
            c in {
                "공매도잔고금액", "순보유잔고금액", "잔고금액",
                "balancevalue", "shortbalancevalue", "strconstval2",
            }
            or ("잔고" in c and "금액" in c)
        ),
    )
    if short_volume_col is None and balance_col is None:
        raise ValueError(
            "공매도 거래량 또는 순보유잔고 수량 열을 찾지 못했습니다"
        )

    dates = _date_series(frame[date_col])
    standardized = pd.DataFrame(index=dates)
    standardized.index.name = "date"
    mappings = {
        "short_volume": short_volume_col,
        "uptick_volume": uptick_col,
        "exception_volume": exception_col,
        "short_balance": balance_col,
        "short_value": short_value_col,
        "balance_value": balance_value_col,
    }
    for output_column, source_column in mappings.items():
        standardized[output_column] = (
            _numeric_series(frame[source_column]).to_numpy()
            if source_column is not None
            else np.nan
        )
    standardized = (
        standardized[~standardized.index.isna()]
        .groupby(level=0)
        .last()
        .sort_index()
    )
    return standardized


def parse_short_selling_uploads(uploaded_files, target_uids):
    """사용자가 지정한 종목별로 KRX 공매도 CSV를 병합한다."""
    datasets, errors = {}, []
    for index, uploaded in enumerate(uploaded_files or []):
        target_uid = (
            target_uids[index]
            if index < len(target_uids or [])
            else ""
        )
        if not target_uid:
            errors.append(f"{uploaded.name}: 적용할 종목을 선택하세요")
            continue
        try:
            raw = _read_uploaded_csv(uploaded)
            standardized = _standardize_short_selling_frame(raw)
            if standardized.empty:
                raise ValueError("공매도 일별 자료가 없습니다")
            current = datasets.get(target_uid)
            if current is None:
                merged = standardized
                filenames = [uploaded.name]
            else:
                # 뒤에 올린 파일이 같은 날짜의 값을 갱신한다.
                merged = standardized.combine_first(current["frame"]).sort_index()
                filenames = list(dict.fromkeys(
                    current["filenames"] + [uploaded.name]
                ))
            datasets[target_uid] = {
                "frame": merged,
                "filenames": filenames,
                "source": (
                    f"업로드 KRX 공매도 CSV {len(filenames)}개 병합"
                    if len(filenames) > 1
                    else "업로드 KRX 공매도 CSV"
                ),
            }
        except Exception as exc:
            errors.append(f"{uploaded.name}: {exc}")
    return datasets, errors


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
                valid_codes = raw[code_col].map(_normalize_stock_code)
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
    """업로드 선물 자료를 현재 종목에 매칭한다.

    반환: (매칭 데이터셋 또는 None, 종목 불일치로 제외한 파일 설명 리스트)
    """
    if not datasets:
        return None, []

    def merge_matches(matches):
        if not matches:
            return None
        merged = pd.DataFrame()
        for dataset in matches:
            frame = dataset["frame"].copy().sort_index()
            # v3.6 #12: 나중에 올린 파일이 같은 날짜 값을 갱신한다
            # (공매도 병합과 우선순위를 일치시킨다).
            merged = frame if merged.empty else frame.combine_first(merged)
        merged = merged.sort_index()
        names = [
            item.get("name", "") for item in matches if item.get("name")
        ]
        filenames = list(dict.fromkeys(
            item.get("filename", "") for item in matches
            if item.get("filename")
        ))
        return {
            "frame": merged,
            "code": symbol,
            "name": names[0] if names else stock_name,
            "filename": ", ".join(filenames),
            "source": (
                f"업로드 CSV {len(filenames)}개 병합"
                if len(filenames) > 1
                else "업로드 CSV"
            ),
        }

    def describe(dataset):
        return (
            dataset.get("filename", "")
            or dataset.get("name", "")
            or dataset.get("code", "")
            or "이름없는 파일"
        )

    coded = [
        dataset for dataset in datasets
        if dataset.get("code") == symbol
    ]
    if coded:
        skipped = [
            f"{describe(d)}(종목코드 {d.get('code')})"
            for d in datasets
            if d.get("code") and d.get("code") != symbol
        ]
        return merge_matches(coded), skipped

    target = _normalized_security_name(stock_name)
    named, mismatched = [], []
    for dataset in datasets:
        candidate = _normalized_security_name(dataset.get("name", ""))
        filename = _compact_text(dataset.get("filename", ""))
        code = dataset.get("code", "")
        if code and code != symbol:
            mismatched.append(f"{describe(dataset)}(종목코드 {code})")
            continue
        if candidate and (
            candidate == target
            or (min(len(candidate), len(target)) >= 3
                and (candidate in target or target in candidate))
        ):
            named.append(dataset)
        elif symbol and symbol in filename:
            named.append(dataset)
        elif candidate:
            mismatched.append(
                f"{describe(dataset)}(종목명 {dataset.get('name')})"
            )
    if named:
        return merge_matches(named), mismatched

    # v3.6 #4: 종목코드·종목명이 명시된 자료를 현재 종목에 끌어다 쓰면
    # 다른 종목의 선물 수급이 조용히 섞인다. 식별정보가 전혀 없는
    # 자료만 현재 분석 종목에 적용한다.
    unidentified = [
        dataset for dataset in datasets
        if not dataset.get("code")
        and not _normalized_security_name(dataset.get("name", ""))
    ]
    if kr_stock_count == 1 and unidentified:
        return merge_matches(unidentified), mismatched
    return None, mismatched


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


def _futures_expiry_from_name(*values):
    """종목명 끝의 YYYYMM을 주식선물 만기월 둘째 목요일로 변환한다."""
    for value in values:
        match = re.search(
            r"(20\d{2})[\s./_-]?(0[1-9]|1[0-2])",
            str(value or ""),
        )
        if not match:
            continue
        year, month = int(match.group(1)), int(match.group(2))
        first = dt.date(year, month, 1)
        first_thursday = first + dt.timedelta(
            days=(3 - first.weekday()) % 7
        )
        return pd.Timestamp(first_thursday + dt.timedelta(days=7))
    return pd.NaT


def _stock_futures_row_score(row: dict, stock_name: str):
    target = _normalized_security_name(stock_name)
    if not target:
        return 0.0
    best = 0.0
    for key in ("ISU_NM", "PROD_NM"):
        candidate = _normalized_security_name(row.get(key, ""))
        if not candidate:
            continue
        if candidate == target:
            best = max(best, 1.0)
        elif (
            min(len(candidate), len(target)) >= 3
            and (candidate in target or target in candidate)
        ):
            best = max(
                best,
                0.90 + 0.09 * (
                    min(len(candidate), len(target))
                    / max(len(candidate), len(target))
                ),
            )
        else:
            best = max(
                best,
                difflib.SequenceMatcher(None, target, candidate).ratio(),
            )
    return best


@st.cache_data(ttl=21600, show_spinner=False)
def fetch_stock_futures_market_openapi(
    auth_key: str,
    stock_name: str,
    sosok: str,
    calendar_days: int = 55,
):
    """KRX 공식 Open API에서 활성 주식선물의 가격·거래량·OI를 수집한다."""
    empty = pd.DataFrame()
    if not auth_key:
        return empty, {
            "status": "KRX Open API 키 미설정",
            "source": "KRX Open API",
        }
    endpoint = (
        "drv/eqsfu_stk_bydd_trd"
        if str(sosok) == "0"
        else "drv/eqkfu_ksq_bydd_trd"
    )
    service_name = (
        "KOSPI 주식선물 일별매매정보"
        if str(sosok) == "0"
        else "KOSDAQ 주식선물 일별매매정보"
    )
    dates = []
    cursor = market_today(MARKET_KR)
    earliest = cursor - dt.timedelta(days=calendar_days)
    while cursor >= earliest:
        if cursor.weekday() < 5:
            dates.append(cursor)
        cursor -= dt.timedelta(days=1)

    active_code = ""
    active_name = ""
    product_name = ""
    rows_by_date = {}
    errors = []
    for base_date in dates:
        try:
            rows = _krx_rows(auth_key, endpoint, base_date)
        except KRXAPIError as exc:
            message = str(exc)
            if "401" in message:
                return empty, {
                    "status": (
                        f"Open API 권한 없음: '{service_name}' "
                        "서비스 이용신청·승인 필요"
                    ),
                    "source": "KRX Open API",
                }
            errors.append(message)
            continue
        except Exception as exc:
            errors.append(f"{type(exc).__name__}: {exc}")
            continue
        rows_by_date[base_date] = rows
        if active_code:
            continue
        candidates = [
            row for row in rows
            if _stock_futures_row_score(row, stock_name) >= 0.72
        ]
        if not candidates:
            continue
        # 동일 기초자산의 여러 월물 중 거래량이 가장 큰 활성월물을 채택한다.
        active = max(
            candidates,
            key=lambda row: (
                _krx_numeric(row.get("ACC_TRDVOL"))
                if pd.notna(_krx_numeric(row.get("ACC_TRDVOL")))
                else -1
            ),
        )
        active_code = str(active.get("ISU_CD", "")).strip()
        active_name = str(active.get("ISU_NM", "")).strip()
        product_name = str(active.get("PROD_NM", "")).strip()

    if not active_code:
        return empty, {
            "status": (
                "상장 주식선물 활성월물 매칭 없음"
                if not errors
                else " / ".join(dict.fromkeys(errors))[:240]
            ),
            "source": "KRX Open API",
        }

    parsed = []
    for base_date in reversed(dates):
        rows = rows_by_date.get(base_date)
        if rows is None:
            try:
                rows = _krx_rows(auth_key, endpoint, base_date)
            except Exception:
                continue
        row = next(
            (
                item for item in rows
                if str(item.get("ISU_CD", "")).strip() == active_code
            ),
            None,
        )
        if row is None:
            continue
        parsed.append({
            "date": pd.to_datetime(
                row.get("BAS_DD", base_date.strftime("%Y%m%d")),
                format="%Y%m%d",
                errors="coerce",
            ),
            "futures_close": _krx_numeric(row.get("TDD_CLSPRC")),
            "spot_close": _krx_numeric(row.get("SPOT_PRC")),
            "futures_volume": _krx_numeric(row.get("ACC_TRDVOL")),
            "open_interest": _krx_numeric(row.get("ACC_OPNINT_QTY")),
            "expiry_date": _futures_expiry_from_name(
                row.get("ISU_NM"), row.get("PROD_NM")
            ),
        })
    if not parsed:
        return empty, {
            "status": "활성월물 일별 자료 없음",
            "source": "KRX Open API",
            "product_id": active_code,
            "product_name": active_name or product_name,
        }
    frame = (
        pd.DataFrame(parsed)
        .dropna(subset=["date"])
        .drop_duplicates("date")
        .set_index("date")
        .sort_index()
    )
    return frame, {
        "status": "정상",
        "source": "KRX Open API",
        "product_id": active_code,
        "product_name": active_name or product_name,
    }


@st.cache_data(ttl=300, show_spinner=False)
def fetch_kospi200_futures_investor_flow():
    """네이버의 KOSPI200 지수선물 투자자별 일자 순매수를 가져온다."""
    response = requests.get(
        "https://finance.naver.com/sise/investorDealTrendDay.naver",
        params={
            "bizdate": market_today(MARKET_KR).strftime("%Y%m%d"),
            "sosok": "03",
            "page": "1",
        },
        headers=UA,
        timeout=15,
    )
    response.raise_for_status()
    tables = pd.read_html(StringIO(response.text))
    for table in tables:
        table = table.copy()
        table.columns = _flatten_csv_columns(table.columns)
        date_col = _find_column(
            table.columns,
            lambda c: c in {"날짜", "일자", "거래일", "거래일자"},
        )
        foreign_col = _find_column(
            table.columns, lambda c: "외국인" in c
        )
        institution_col = _find_column(
            table.columns,
            lambda c: c in {"기관계", "기관합계", "기관"},
        )
        if not all((date_col, foreign_col, institution_col)):
            continue
        raw_dates = table[date_col].astype(str).str.strip()
        dates = pd.to_datetime(
            raw_dates, format="%y.%m.%d", errors="coerce"
        )
        parsed = pd.DataFrame({
            "date": dates,
            "foreign": _numeric_series(table[foreign_col]),
            "institution": _numeric_series(table[institution_col]),
        }).dropna(subset=["date"])
        if not parsed.empty:
            return (
                parsed.drop_duplicates("date")
                .set_index("date")
                .sort_index()
            )
    return pd.DataFrame(columns=["foreign", "institution"])


def evaluate_market_futures_flow(frame: pd.DataFrame):
    empty = {
        "available": False,
        "label": "데이터 없음",
        "foreign5": np.nan,
        "institution5": np.nan,
        "foreign_momentum": "데이터 없음",
        "latest_date": None,
    }
    required = {"foreign", "institution"}
    if frame.empty or not required.issubset(frame.columns):
        return empty
    foreign = pd.to_numeric(frame["foreign"], errors="coerce").dropna()
    institution = pd.to_numeric(
        frame["institution"], errors="coerce"
    ).dropna()
    if foreign.empty or institution.empty:
        return empty
    foreign5 = float(foreign.tail(5).sum())
    institution5 = float(institution.tail(5).sum())
    if foreign5 > 0 and institution5 > 0:
        label = "지수선물 동반 순매수"
    elif foreign5 > 0:
        label = "지수선물 외국인 순매수"
    elif foreign5 < 0 and institution5 < 0:
        label = "지수선물 동반 순매도"
    elif foreign5 < 0:
        label = "지수선물 외국인 순매도"
    else:
        label = "지수선물 중립"
    return {
        "available": True,
        "label": label,
        "foreign5": foreign5,
        "institution5": institution5,
        "foreign_momentum": _flow_momentum(foreign),
        "latest_date": frame.index.max(),
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


def _empty_short_frame(status: str, source: str = "KRX Data Marketplace"):
    frame = pd.DataFrame()
    frame.attrs.update({"status": status, "source": source})
    return frame


def _krx_data_request_error(prefix: str, exc: Exception):
    response = getattr(exc, "response", None)
    status_code = getattr(response, "status_code", None)
    if status_code == 401:
        return (
            f"{prefix}: KRX Data Marketplace 로그인/접근 권한 필요 "
            "(HTTP 401)"
        )
    if status_code == 403:
        return f"{prefix}: KRX가 현재 서버 요청을 거부함 (HTTP 403)"
    detail = str(exc).strip()
    return (
        f"{prefix}: {type(exc).__name__}"
        + (f" ({detail})" if detail else "")
    )[:300]


@st.cache_resource(show_spinner=False)
def _krx_data_login_cookies(krx_id: str, krx_pw: str):
    """선택적으로 KRX Data Marketplace 로그인 쿠키를 한 번만 만든다."""
    if not (krx_id and krx_pw):
        return {}, "로그인정보 미설정"
    session = requests.Session()
    login_page = (
        "https://data.krx.co.kr/contents/MDC/COMS/client/MDCCOMS001.cmd"
    )
    login_jsp = (
        "https://data.krx.co.kr/contents/MDC/COMS/client/view/"
        "login.jsp?site=mdc"
    )
    login_url = (
        "https://data.krx.co.kr/contents/MDC/COMS/client/MDCCOMS001D1.cmd"
    )
    headers = {**UA, "Referer": login_page}
    try:
        session.get(login_page, headers=UA, timeout=15)
        session.get(login_jsp, headers=headers, timeout=15)
        payload = {
            "mbrNm": "",
            "telNo": "",
            "di": "",
            "certType": "",
            "mbrId": krx_id,
            "pw": krx_pw,
        }
        response = session.post(
            login_url, data=payload, headers=headers, timeout=15
        )
        data = response.json()
        if data.get("_error_code") == "CD011":
            payload["skipDup"] = "Y"
            response = session.post(
                login_url, data=payload, headers=headers, timeout=15
            )
            data = response.json()
        if data.get("_error_code") != "CD001":
            return {}, (
                "KRX 로그인 실패: "
                + str(data.get("_error_message") or data.get("_error_code"))
            )
        return session.cookies.get_dict(), "정상"
    except Exception as exc:
        return {}, f"KRX 로그인 실패: {type(exc).__name__}"


def _new_krx_data_session(krx_id: str = "", krx_pw: str = ""):
    session = requests.Session()
    loader = (
        "https://data.krx.co.kr/contents/MDC/MDI/outerLoader/index.cmd"
    )
    try:
        session.get(loader, headers=UA, timeout=15)
    except Exception:
        pass
    cookies, login_status = _krx_data_login_cookies(krx_id, krx_pw)
    if cookies:
        session.cookies.update(cookies)
    return session, login_status


def _isin_check_digit(base: str):
    """11자리 ISIN 본문에 ISO 6166/Luhn 검증 숫자를 붙일 때 쓸 값."""
    expanded = "".join(
        str(int(char, 36)) if char.isalpha() else char
        for char in base.upper()
    )
    total = 0
    for index, digit in enumerate(reversed(expanded)):
        number = int(digit) * (2 if index % 2 == 0 else 1)
        total += number // 10 + number % 10
    return str((10 - total % 10) % 10)


def _generated_common_stock_isin(code: str):
    """보통주 단축코드(끝자리 0)는 KRX 주권 ISIN 규칙으로 안전하게 생성."""
    clean = str(code or "").strip().upper()
    if not (len(clean) == 6 and clean.isdigit() and clean.endswith("0")):
        return ""
    base = f"KR7{clean}00"
    return base + _isin_check_digit(base)


@st.cache_data(ttl=21600, show_spinner=False)
def resolve_stock_isin_openapi(auth_key: str, code: str, sosok: str):
    """공식 KRX 주식 일별 API를 우선 사용하고 보통주는 규칙 생성으로 보완."""
    if auth_key:
        endpoints = (
            ["sto/stk_bydd_trd", "sto/ksq_bydd_trd"]
            if str(sosok) == "0"
            else ["sto/ksq_bydd_trd", "sto/stk_bydd_trd"]
        )
        for endpoint in endpoints:
            for base_date in _previous_weekdays(8):
                try:
                    row = _krx_stock_row(
                        _krx_rows(auth_key, endpoint, base_date), code
                    )
                except Exception:
                    break
                if not row:
                    continue
                isin = str(row.get("ISU_CD", "")).strip().upper()
                if len(isin) == 12 and isin.startswith("KR"):
                    return isin
    return _generated_common_stock_isin(code)


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_short_selling(
    code: str,
    calendar_days: int = 70,
    krx_id: str = "",
    krx_pw: str = "",
    auth_key: str = "",
    sosok: str = "",
):
    """KRX 공매도 종합정보의 일별 거래량·공시 잔고를 가져온다."""
    session, login_status = _new_krx_data_session(krx_id, krx_pw)
    headers = {
        **UA,
        "Referer": (
            "https://data.krx.co.kr/contents/MDC/MDI/outerLoader/index.cmd"
        ),
    }
    full_code = resolve_stock_isin_openapi(auth_key, code, sosok)
    if not full_code:
        try:
            finder = session.post(
                KRX_DATA_URL,
                data={
                    "bld": "dbms/comm/finder/finder_stkisu",
                    "mktsel": "ALL",
                    "searchText": code,
                    "typeNo": "0",
                    "locale": "ko_KR",
                },
                headers=headers,
                timeout=20,
            )
            finder.raise_for_status()
        except requests.RequestException as exc:
            return _empty_short_frame(_krx_data_request_error(
                "종목 ISIN 조회 실패", exc
            ))
        finder_text = finder.text.strip()
        if (
            finder_text.upper() == "LOGOUT"
            or "<html" in finder_text.lower()
            or "로그인" in finder_text[:500]
        ):
            return _empty_short_frame(
                "KRX Data Marketplace 로그인 필요"
                + (
                    f" ({login_status})"
                    if login_status != "로그인정보 미설정"
                    else ""
                )
            )
        try:
            finder_payload = finder.json()
        except ValueError:
            return _empty_short_frame("종목 ISIN 응답 형식 오류")
        matches = (
            finder_payload.get("block1")
            or finder_payload.get("output")
            or []
        )
        exact = [
            item for item in matches
            if str(
                item.get("short_code")
                or item.get("shortCode")
                or item.get("code")
                or ""
            ).strip() == code
        ]
        selected = exact[0] if exact else (matches[0] if matches else {})
        full_code = str(
            selected.get("full_code")
            or selected.get("fullCode")
            or selected.get("code")
            or ""
        ).strip()
    if not full_code.startswith("KR"):
        return _empty_short_frame("종목 ISIN을 찾지 못했습니다")

    start = TODAY - dt.timedelta(days=calendar_days)
    try:
        response = session.post(
            KRX_DATA_URL,
            data={
                "bld": "dbms/MDC/STAT/srt/MDCSTAT30001",
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
    except requests.RequestException as exc:
        return _empty_short_frame(_krx_data_request_error(
            "공매도 통계 요청 실패", exc
        ))
    text = response.text.strip()
    if (
        text.upper() == "LOGOUT"
        or "<html" in text.lower()
        or "로그인" in text[:500]
    ):
        return _empty_short_frame(
            "KRX Data Marketplace 로그인 필요"
            + (
                f" ({login_status})"
                if login_status != "로그인정보 미설정"
                else ""
            )
        )
    try:
        payload = response.json()
    except ValueError:
        return _empty_short_frame("공매도 통계 응답 형식 오류")
    error_message = payload.get("_error_message") or payload.get("message")
    rows = payload.get("OutBlock_1") or payload.get("output") or []
    if not isinstance(rows, list) or not rows:
        return _empty_short_frame(
            str(error_message or "조회기간 내 공매도 자료 없음")
        )

    parsed = []
    for row in rows:
        try:
            parsed.append({
                "date": pd.to_datetime(row["TRD_DD"], format="%Y/%m/%d"),
                "short_volume": _krx_numeric(row.get("CVSRTSELL_TRDVOL")),
                "uptick_volume": _krx_numeric(
                    row.get("UPTICKRULE_APPL_TRDVOL")
                ),
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
        return _empty_short_frame("공매도 행 파싱 결과 없음")
    frame = (
        pd.DataFrame(parsed)
        .drop_duplicates("date")
        .set_index("date")
        .sort_index()
    )
    frame.attrs.update({
        "status": "정상",
        "source": (
            "KRX Data Marketplace 로그인"
            if login_status == "정상"
            else "KRX Data Marketplace"
        ),
    })
    return frame


def _fallback_basic(market: str, symbol: str, label: str = ""):
    return {
        "market": market, "symbol": symbol, "name": label or symbol,
        "price": None, "change_pct": None, "traded_at": "",
        "market_status": "", "exchange": "", "sosok": "",
        "basic_failed": True,
    }


def fetch_bundle(
    uid: str,
    label: str = "",
    krx_id: str = "",
    krx_pw: str = "",
    auth_key: str = "",
    skip_short: bool = True,
):
    """한 종목의 기본정보·일봉·(한국)수급·공매도를 시장별로 묶는다.

    v3.5부터 공매도 자동수집은 기본 비활성(skip_short=True)이고 CSV
    업로드만 사용한다. fetch_short_selling·_krx_data_login_cookies 계열은
    재활성화를 위해 남겨두었을 뿐 현재 호출 경로가 없다(v3.6 주석).
    """
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
        short_future = (
            None
            if skip_short
            else pool.submit(
                fetch_short_selling,
                symbol,
                70,
                krx_id,
                krx_pw,
                auth_key,
                basic.get("sosok", ""),
            )
        )
        try:
            investor = investor_future.result()
        except Exception:
            investor = empty_flow
        if short_future is None:
            short_selling = _empty_short_frame("공매도 CSV 미업로드")
        else:
            try:
                short_selling = short_future.result()
            except Exception as exc:
                short_selling = _empty_short_frame(
                    f"공매도 수집 예외: {type(exc).__name__}: {exc}"
                )
    return basic, history, investor, short_selling


class KRXAPIError(RuntimeError):
    pass


@st.cache_data(ttl=21600, show_spinner=False)
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
    rsi = 100 - 100 / (1 + rs)
    # v3.6 #6: 하락이 전혀 없으면 rs가 발산해 RSI가 NaN이 됐다. NaN이면
    # 과열 경고·RSI 신호가 전부 조용히 False가 되므로 정의값으로 채운다.
    no_loss = loss.eq(0) & gain.notna()
    rsi = rsi.mask(no_loss & gain.gt(0), 100.0)
    rsi = rsi.mask(no_loss & gain.eq(0), 50.0)
    out["rsi14"] = rsi

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


def evaluate_stock_futures_context(
    stock_futures: pd.DataFrame,
    raw_history: pd.DataFrame,
    spot_flow: dict,
    market_futures: dict,
):
    """Hull의 베이시스·수렴·OI 정의를 바탕으로 현물/선물을 종합한다."""
    flow_result = evaluate_stock_futures_flow(
        stock_futures, raw_history
    )
    series = (
        stock_futures.copy().sort_index()
        if stock_futures is not None
        else pd.DataFrame()
    )
    market_columns = {
        "futures_close", "futures_volume", "open_interest",
        "reported_basis", "reported_basis_pct", "spot_close",
        "theoretical_price", "expiry_date",
    }
    def has_market_values(column):
        if column not in series:
            return False
        if column == "expiry_date":
            return pd.to_datetime(
                series[column], errors="coerce"
            ).notna().any()
        return pd.to_numeric(
            series[column], errors="coerce"
        ).notna().any()

    market_available = bool(
        not series.empty
        and any(has_market_values(column) for column in market_columns)
    )
    flow_available = flow_result["available"]
    available = flow_available or market_available

    defaults = {
        "available": available,
        "flow_available": flow_available,
        "market_data_available": market_available,
        "basis_available": False,
        "basis_latest": np.nan,
        "basis_pct_latest": np.nan,
        "basis_change": np.nan,
        "basis_label": "자료 없음",
        "basis_definition": "Hull 기준: 현물가격 - 선물가격",
        "volume_available": False,
        "volume_latest": np.nan,
        "volume_avg5": np.nan,
        "volume_ratio20": np.nan,
        "volume_oi_turnover": np.nan,
        "activity_label": "자료 없음",
        "days_to_expiry": np.nan,
        "near_expiry": False,
        "rollover_suspected": False,
        "oi_latest": np.nan,
        "oi_change": np.nan,
        "futures_price_change_pct": np.nan,
        "spot_price_change_pct": np.nan,
        "futures_spot_spread_pct": np.nan,
        "theoretical_price_available": False,
        "theoretical_price_latest": np.nan,
        "theoretical_gap_latest": np.nan,
        "theoretical_gap_pct": np.nan,
        "relation_label": "연계 판정 불가",
        "integrated_label": (
            flow_result["label"] if flow_available else "데이터 없음"
        ),
        "integrated_interpretation": (
            "선물 수급·가격·거래량·미결제약정 자료가 부족합니다."
        ),
        "diagnostics": [],
        "market_futures": market_futures,
        "series": series,
    }
    result = {**flow_result, **defaults}
    if not available:
        return result

    def lookback_change_pct(values: pd.Series, periods=5):
        clean = pd.to_numeric(values, errors="coerce").dropna()
        if len(clean) < 2:
            return np.nan
        reference = (
            float(clean.iloc[-periods - 1])
            if len(clean) > periods
            else float(clean.iloc[0])
        )
        return (
            (float(clean.iloc[-1]) / reference - 1) * 100
            if reference != 0
            else np.nan
        )

    if series.empty:
        series = pd.DataFrame(index=raw_history.index)

    if not raw_history.empty and "close" in raw_history:
        aligned_spot = pd.to_numeric(
            raw_history["close"], errors="coerce"
        ).reindex(series.index)
        if "spot_close" in series:
            series["spot_close"] = pd.to_numeric(
                series["spot_close"], errors="coerce"
            ).combine_first(aligned_spot)
        else:
            series["spot_close"] = aligned_spot

    futures_prices = (
        pd.to_numeric(series["futures_close"], errors="coerce")
        if "futures_close" in series
        else pd.Series(index=series.index, dtype=float)
    )
    spot_prices = (
        pd.to_numeric(series["spot_close"], errors="coerce")
        if "spot_close" in series
        else pd.Series(index=series.index, dtype=float)
    )
    paired_prices = pd.concat(
        [
            spot_prices.rename("spot"),
            futures_prices.rename("futures"),
        ],
        axis=1,
    ).dropna()

    basis_available = len(paired_prices) >= 1
    basis_latest = basis_pct_latest = basis_change = np.nan
    basis_label = "자료 없음"
    if basis_available:
        # Hull Ch.3 정의: basis = spot - futures.
        series["basis"] = spot_prices - futures_prices
        series["basis_pct"] = (
            series["basis"] / spot_prices.replace(0, np.nan) * 100
        )
        basis_values = series["basis"].dropna()
        basis_pct_values = series["basis_pct"].dropna()
        basis_latest = float(basis_values.iloc[-1])
        basis_pct_latest = float(basis_pct_values.iloc[-1])
        if len(basis_values) >= 2:
            reference = (
                float(basis_values.iloc[-6])
                if len(basis_values) >= 6
                else float(basis_values.iloc[0])
            )
            basis_change = basis_latest - reference
        level = (
            "현물 프리미엄" if basis_latest > 0
            else "선물 프리미엄" if basis_latest < 0
            else "현·선물 일치"
        )
        movement = (
            "베이시스 강화" if basis_change > 0
            else "베이시스 약화" if basis_change < 0
            else "변화 미미"
        )
        basis_label = f"{level}·{movement}"
    elif "reported_basis" in series:
        reported = pd.to_numeric(
            series["reported_basis"], errors="coerce"
        ).dropna()
        if not reported.empty:
            basis_label = "원자료 베이시스(정의 확인 필요)"

    oi_values = (
        pd.to_numeric(series["open_interest"], errors="coerce").dropna()
        if "open_interest" in series
        else pd.Series(dtype=float)
    )
    oi_available = len(oi_values) >= 2
    oi_latest = float(oi_values.iloc[-1]) if len(oi_values) else np.nan
    oi_change = np.nan
    oi_change_pct = np.nan
    if oi_available:
        reference = (
            float(oi_values.iloc[-6])
            if len(oi_values) >= 6
            else float(oi_values.iloc[0])
        )
        oi_change = oi_latest - reference
        if reference > 0:
            oi_change_pct = (oi_latest / reference - 1) * 100

    volume_values = (
        pd.to_numeric(series["futures_volume"], errors="coerce").dropna()
        if "futures_volume" in series
        else pd.Series(dtype=float)
    )
    volume_available = not volume_values.empty
    volume_latest = (
        float(volume_values.iloc[-1]) if volume_available else np.nan
    )
    volume_avg5 = (
        float(volume_values.tail(5).mean())
        if volume_available else np.nan
    )
    volume_avg20 = (
        float(volume_values.tail(20).mean())
        if len(volume_values) >= 20 else np.nan
    )
    volume_ratio20 = (
        volume_avg5 / volume_avg20
        if pd.notna(volume_avg20) and volume_avg20 > 0
        else np.nan
    )
    volume_oi_turnover = (
        volume_avg5 / oi_latest
        if pd.notna(volume_avg5)
        and pd.notna(oi_latest)
        and oi_latest > 0
        else np.nan
    )
    if not volume_available:
        activity_label = "거래량 자료 없음"
    elif pd.notna(volume_ratio20) and volume_ratio20 >= 1.25:
        if oi_available and oi_change > 0:
            activity_label = "거래 증가·신규 계약 증가"
        elif oi_available and oi_change < 0:
            activity_label = "거래 증가·청산/롤오버 우세"
        else:
            activity_label = "거래 증가·포지션 교체 가능"
    elif oi_available and oi_change > 0:
        activity_label = "미결제약정 증가·거래 보통"
    else:
        activity_label = "거래 활동 보통"

    days_to_expiry = np.nan
    near_expiry = False
    if "expiry_date" in series:
        expiries = pd.to_datetime(
            series["expiry_date"], errors="coerce"
        ).dropna()
        if not expiries.empty and not series.empty:
            days_to_expiry = (
                expiries.iloc[-1].date() - series.index.max().date()
            ).days
            near_expiry = 0 <= days_to_expiry <= 7
    rollover_suspected = bool(
        near_expiry
        and oi_available
        and pd.notna(oi_change_pct)
        and oi_change_pct <= -10
    )
    if rollover_suspected:
        activity_label = "만기근접·롤오버/청산 가능"

    futures_price_change_pct = (
        lookback_change_pct(futures_prices)
        if futures_prices.notna().sum() >= 2 else np.nan
    )
    spot_price_change_pct = (
        lookback_change_pct(spot_prices)
        if spot_prices.notna().sum() >= 2
        else lookback_change_pct(raw_history["close"])
        if not raw_history.empty and "close" in raw_history
        else np.nan
    )
    futures_spot_spread_pct = (
        futures_price_change_pct - spot_price_change_pct
        if pd.notna(futures_price_change_pct)
        and pd.notna(spot_price_change_pct)
        else np.nan
    )
    theoretical_prices = (
        pd.to_numeric(series["theoretical_price"], errors="coerce")
        if "theoretical_price" in series
        else pd.Series(index=series.index, dtype=float)
    )
    theoretical_pair = pd.concat(
        [
            futures_prices.rename("futures"),
            theoretical_prices.rename("theoretical"),
        ],
        axis=1,
    ).dropna()
    theoretical_price_available = not theoretical_pair.empty
    theoretical_price_latest = theoretical_gap_latest = (
        theoretical_gap_pct
    ) = np.nan
    if theoretical_price_available:
        theoretical_price_latest = float(
            theoretical_pair["theoretical"].iloc[-1]
        )
        theoretical_gap_latest = float(
            theoretical_pair["futures"].iloc[-1]
            - theoretical_price_latest
        )
        if theoretical_price_latest != 0:
            theoretical_gap_pct = (
                theoretical_gap_latest / theoretical_price_latest * 100
            )

    futures_direction = (
        1 if flow_available and flow_result["combined5"] > 0
        else -1 if flow_available and flow_result["combined5"] < 0
        else 0
    )
    spot_direction = (
        1 if spot_flow.get("available") and spot_flow["combined5"] > 0
        else -1 if spot_flow.get("available") and spot_flow["combined5"] < 0
        else 0
    )
    if spot_direction > 0 and futures_direction > 0:
        relation_label = "현·선물 동반 매수"
    elif spot_direction > 0 and futures_direction < 0:
        relation_label = "현물 매수·선물 매도"
    elif spot_direction < 0 and futures_direction > 0:
        relation_label = "현물 매도·선물 매수"
    elif spot_direction < 0 and futures_direction < 0:
        relation_label = "현·선물 동반 매도"
    else:
        relation_label = "현·선물 방향 혼재"

    price_direction = (
        1 if futures_price_change_pct > 0
        else -1 if futures_price_change_pct < 0
        else 0
    )
    oi_direction = (
        1 if oi_change > 0 else -1 if oi_change < 0 else 0
    )
    if rollover_suspected:
        position_label = "만기 롤오버 가능·방향판정 보류"
    elif not oi_available:
        position_label = "신규·청산 구분 불가"
    elif price_direction > 0 and oi_direction > 0:
        position_label = "신규 계약 증가·롱 우세 추정"
    elif price_direction > 0 and oi_direction < 0:
        position_label = "기존 포지션 청산·숏커버 추정"
    elif price_direction < 0 and oi_direction > 0:
        position_label = "신규 계약 증가·숏 우세 추정"
    elif price_direction < 0 and oi_direction < 0:
        position_label = "기존 포지션 청산·롱청산 추정"
    else:
        position_label = "가격·미결제약정 혼재"

    score = int(flow_result["score"] if flow_available else 50)
    if spot_direction > 0 and futures_direction > 0:
        score += 10
    elif spot_direction < 0 and futures_direction < 0:
        score -= 12
    elif spot_direction > 0 and futures_direction < 0:
        score -= 4

    if oi_available and not rollover_suspected:
        if price_direction > 0 and oi_direction > 0:
            score += 8
        elif price_direction > 0 and oi_direction < 0:
            score += 3
        elif price_direction < 0 and oi_direction > 0:
            score -= 8
        elif price_direction < 0 and oi_direction < 0:
            score -= 4
    if basis_available and pd.notna(basis_change):
        if futures_direction > 0 and basis_change < 0:
            score += 5
        elif futures_direction < 0 and basis_change > 0:
            score -= 5
    if pd.notna(volume_ratio20) and volume_ratio20 >= 1.25:
        if futures_direction > 0:
            score += 4
        elif futures_direction < 0:
            score -= 4
    if market_futures.get("available"):
        market_foreign5 = market_futures.get("foreign5", 0)
        score += 4 if market_foreign5 > 0 else -4 if market_foreign5 < 0 else 0
    score = int(np.clip(score, 0, 100))

    if (
        relation_label == "현물 매수·선물 매도"
        and basis_available
        and basis_latest < 0
    ):
        integrated_label = "현물매수·선물매도 헤지/차익 가능"
    elif score >= 70:
        integrated_label = "상승 포지션 우세"
    elif score <= 30:
        integrated_label = "하락·헤지 압력 우세"
    elif relation_label == "현·선물 동반 매도":
        integrated_label = "현·선물 위험회피"
    else:
        integrated_label = "포지션 혼재·확인 필요"

    explanations = [
        f"현물과 개별주식선물의 관계는 '{relation_label}'입니다."
    ]
    if basis_available:
        explanations.append(
            f"Hull 정의(S-F) 베이시스는 {basis_latest:+,.2f}"
            f"({basis_pct_latest:+.3f}%)이며 {basis_label}입니다."
        )
    else:
        explanations.append(
            "현물·선물 종가 쌍이 없어 Hull 기준 베이시스를 계산하지 못했습니다."
        )
    if theoretical_price_available:
        explanations.append(
            f"KRX 이론가 대비 선물 가격 차이는 "
            f"{theoretical_gap_latest:+,.2f}"
            f"({theoretical_gap_pct:+.3f}%)입니다. 이는 금리·배당·"
            "잔존만기가 반영된 공정가치와의 괴리이며 방향성 신호로 "
            "단독 사용하지 않습니다."
        )
    if oi_available:
        if rollover_suspected:
            explanations.append(
                f"만기까지 {days_to_expiry}일이고 미결제약정이 "
                f"{oi_change_pct:+.2f}% 감소해 방향성 청산보다 "
                "월물교체 가능성을 우선합니다."
            )
        else:
            explanations.append(
                f"5일 미결제약정은 {oi_change:+,.0f}계약"
                f"({oi_change_pct:+.2f}%)으로 '{position_label}'입니다."
            )
    else:
        explanations.append(
            "미결제약정이 없어 신규 계약과 포지션 청산을 구분할 수 없습니다."
        )
    if volume_available and pd.notna(volume_ratio20):
        explanations.append(
            f"5일 선물거래량은 20일 평균의 {volume_ratio20:.2f}배로 "
            f"'{activity_label}'입니다."
        )
    elif volume_available:
        explanations.append(
            f"최근 5일 선물거래량 평균은 {volume_avg5:,.0f}계약입니다. "
            "20일 표본이 부족해 장기평균 대비 증감은 판정하지 않았습니다."
        )
    if market_futures.get("available"):
        explanations.append(
            "시장 보조축인 KOSPI200 지수선물은 "
            f"'{market_futures['label']}'입니다."
        )
    explanations.append(
        "미결제약정은 동일 계약의 롱·숏 총수가 항상 같으므로, 가격과 "
        "수급을 결합한 우세 방향은 추정이지 투자자별 잔고 확정치가 아닙니다."
    )

    diagnostics = [
        {
            "항목": "현물 외국인·기관",
            "판정": spot_flow.get("label", "데이터 없음"),
            "근거": (
                f"5일 합계 {spot_flow['combined5']:+,.0f}주"
                if spot_flow.get("available") else "자료 없음"
            ),
        },
        {
            "항목": "개별주식선물 수급",
            "판정": flow_result["label"],
            "근거": (
                f"5일 합계 {flow_result['combined5']:+,.0f}계약"
                if flow_available else "자료 없음"
            ),
        },
        {
            "항목": "베이시스(S-F)",
            "판정": basis_label,
            "근거": (
                (
                    f"{basis_latest:+,.2f} / "
                    f"5일 변화 {basis_change:+,.2f}"
                    if pd.notna(basis_change)
                    else f"최근 {basis_latest:+,.2f} / 추세 표본 부족"
                )
                if basis_available else "현물·선물 종가 필요"
            ),
        },
        {
            "항목": "가격×미결제약정",
            "판정": position_label,
            "근거": (
                f"선물 {futures_price_change_pct:+.2f}% / "
                f"OI {oi_change_pct:+.2f}%"
                if pd.notna(futures_price_change_pct) and oi_available
                else "선물종가·미결제약정 필요"
            ),
        },
        {
            "항목": "이론가 대비",
            "판정": (
                "이론가 상회" if theoretical_gap_latest > 0
                else "이론가 하회" if theoretical_gap_latest < 0
                else "이론가 부근"
                if theoretical_price_available
                else "자료 없음"
            ),
            "근거": (
                f"선물-이론가 {theoretical_gap_latest:+,.2f}"
                f" ({theoretical_gap_pct:+.3f}%)"
                if theoretical_price_available
                else "KRX 이론가 또는 금리·배당·잔존만기 필요"
            ),
        },
        {
            "항목": "거래 활동",
            "판정": activity_label,
            "근거": (
                f"5일/20일 {volume_ratio20:.2f}배 · "
                f"거래량/OI {volume_oi_turnover:.2f}"
                if pd.notna(volume_ratio20)
                and pd.notna(volume_oi_turnover)
                else (
                    f"5일 평균 {volume_avg5:,.0f}계약"
                    if volume_available
                    else "선물거래량 자료 필요"
                )
            ),
        },
        {
            "항목": "KOSPI200 지수선물",
            "판정": market_futures.get("label", "데이터 없음"),
            "근거": (
                f"외국인 5일 {market_futures['foreign5']:+,.0f}계약"
                if market_futures.get("available") else "자료 없음"
            ),
        },
    ]

    result.update({
        "available": True,
        "score": score,
        "basis_available": basis_available,
        "basis_latest": basis_latest,
        "basis_pct_latest": basis_pct_latest,
        "basis_change": basis_change,
        "basis_label": basis_label,
        "volume_available": volume_available,
        "volume_latest": volume_latest,
        "volume_avg5": volume_avg5,
        "volume_ratio20": volume_ratio20,
        "volume_oi_turnover": volume_oi_turnover,
        "activity_label": activity_label,
        "days_to_expiry": days_to_expiry,
        "near_expiry": near_expiry,
        "rollover_suspected": rollover_suspected,
        "oi_available": oi_available,
        "oi_latest": oi_latest,
        "oi_change": oi_change,
        "oi_change_pct": oi_change_pct,
        "futures_price_change_pct": futures_price_change_pct,
        "spot_price_change_pct": spot_price_change_pct,
        "futures_spot_spread_pct": futures_spot_spread_pct,
        "theoretical_price_available": theoretical_price_available,
        "theoretical_price_latest": theoretical_price_latest,
        "theoretical_gap_latest": theoretical_gap_latest,
        "theoretical_gap_pct": theoretical_gap_pct,
        "price_change_pct": futures_price_change_pct,
        "price_source": "선물" if pd.notna(futures_price_change_pct)
        else "자료 없음",
        "position_label": position_label,
        "relation_label": relation_label,
        "integrated_label": integrated_label,
        "integrated_interpretation": " ".join(explanations),
        "interpretation": " ".join(explanations),
        "diagnostics": diagnostics,
        "market_futures": market_futures,
        "latest_date": series.index.max() if not series.empty else None,
        "series": series,
    })
    return result


def evaluate_short_pressure(
    short_selling: pd.DataFrame,
    raw_history: pd.DataFrame,
):
    source_status = getattr(short_selling, "attrs", {}) or {}
    empty_result = {
        "available": False,
        "label": "데이터 없음",
        "score": 50,
        "status": source_status.get("status", "응답 없음"),
        "source": source_status.get("source", "KRX Data Marketplace"),
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
        "status": source_status.get("status", "정상"),
        "source": source_status.get("source", "KRX Data Marketplace"),
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
    # v3.6 #5: 가중치·안전판정 모두 "선물 수급이 실제로 있을 때"만 적용한다.
    # 선물 시세·미결제약정만 있는 경우까지 available로 묶으면 현물수급
    # 배점이 근거 없이 깎였다.
    futures_flow_available = bool(futures_flow.get("flow_available"))
    flow_safe = flow["label"] != "동반 매도"
    futures_safe = (
        not futures_flow_available or futures_flow["score"] >= 35
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
    # v3.6 #9: 시장 구조상 존재하지 않는 축(미국의 현물 외국인·기관 구분,
    # KRX 공매도)은 중립 50점으로 채우지 않고 배점에서 제외한 뒤 100점으로
    # 정규화한다. 중립 채움은 미국 종목 상한을 83점으로 눌러 임계값
    # 70/65/55를 시장 공통으로 쓰는 구조와 충돌했다.
    # 반면 한국인데 API 응답만 없는 일시적 결측은 기존대로 중립 50 유지.
    meta = MARKET_META.get(market, MARKET_META[MARKET_KR])
    components = {
        "추세": trend_component,
        "가격위치": price_component,
        "거래량": volume_component,
    }
    component_max = {"추세": 25, "가격위치": 25, "거래량": 15}
    if meta["has_investor_flow"]:
        weight = 0.15 if futures_flow_available else 0.20
        components["현물 외국인·기관"] = int(round(flow["score"] * weight))
        component_max["현물 외국인·기관"] = int(round(100 * weight))
    if futures_flow_available:
        components["개별주식선물"] = int(round(futures_flow["score"] * 0.10))
        component_max["개별주식선물"] = 10
    if meta["has_short_selling"]:
        weight = 0.10 if futures_flow_available else 0.15
        components["공매도"] = int(round(short_pressure["score"] * weight))
        component_max["공매도"] = int(round(100 * weight))

    raw_total = sum(components.values())
    raw_max = sum(component_max.values())
    score = (
        int(np.clip(round(raw_total / raw_max * 100), 0, 100))
        if raw_max else 0
    )
    score_basis = (
        f"적용 배점 {raw_total}/{raw_max} → 100점 환산"
        if raw_max != 100
        else f"{raw_total}/100"
    )

    if stage in ("하락 진행", "추세 훼손"):
        status = "⛔ 신규매수 금지"
        reason = "가격 추세가 아직 하락 중이거나 기존 상승추세가 훼손됐습니다."
    elif (
        futures_flow_available
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
        "components": components,
        "component_max": component_max,
        "score_basis": score_basis,
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


def build_integrated_evidence(
    stage: str,
    df: pd.DataFrame,
    rsi: float,
    rs20: float,
    benchmark_name: str,
    flow: dict,
    futures_flow: dict,
    short_pressure: dict,
    entry: dict,
):
    """가격·수급·파생·위험 축을 한 표에서 교차 검증한다."""
    last = df.iloc[-1]
    close = float(last["close"])
    volume20 = float(df["volume"].tail(20).mean())
    volume_ratio = (
        float(last["volume"]) / volume20 if volume20 > 0 else np.nan
    )
    obv_change = (
        float(last["obv"] - df["obv"].iloc[-6])
        if len(df) >= 6 else np.nan
    )
    atr_pct = (
        float(last["atr14"]) / close * 100
        if pd.notna(last["atr14"]) and close > 0 else np.nan
    )
    distance_ma20 = (
        (close / float(last["ma20"]) - 1) * 100
        if pd.notna(last["ma20"]) and last["ma20"] != 0 else np.nan
    )

    trend_view = (
        "우호" if stage in ("바닥 확인", "상승추세")
        else "관찰" if stage == "바닥 형성 관찰"
        else "경계"
    )
    momentum_view = (
        "과열 경계" if rsi >= 70
        else "우호" if rsi >= 45 and last["macd_hist"] > 0
        else "반등 관찰" if rsi >= 30
        else "과매도·추세확인 필요"
    )
    rs_view = (
        "시장 대비 우위" if pd.notna(rs20) and rs20 > 0
        else "시장 대비 열위" if pd.notna(rs20)
        else "자료 없음"
    )
    activity_view = (
        "수요 확인" if volume_ratio >= 1.3 and obv_change > 0
        else "매도 압력" if volume_ratio >= 1.3 and obv_change < 0
        else "활동 보통"
    )
    risk_view = (
        "변동성 높음" if pd.notna(atr_pct) and atr_pct >= 5
        else "변동성 보통" if pd.notna(atr_pct)
        else "자료 없음"
    )

    rows = [
        {
            "분석축": "가격 추세·위치",
            "판정": trend_view,
            "근거": (
                f"{stage} · MA20 대비 {distance_ma20:+.2f}% · "
                f"진입점수 {entry['score']}/100"
            ),
        },
        {
            "분석축": "모멘텀",
            "판정": momentum_view,
            "근거": (
                f"RSI14 {rsi:.1f} · MACD 히스토그램 "
                f"{last['macd_hist']:+,.2f}"
            ),
        },
        {
            "분석축": "현물 거래량·OBV",
            "판정": activity_view,
            "근거": (
                f"거래량/20일 {volume_ratio:.2f}배 · "
                f"OBV 5일 {obv_change:+,.0f}"
            ),
        },
        {
            "분석축": "상대강도",
            "판정": rs_view,
            "근거": (
                f"{benchmark_name} 대비 20일 {rs20:+.2f}%p"
                if pd.notna(rs20) else "기준지수 표본 부족"
            ),
        },
        {
            "분석축": "현물 외국인·기관",
            "판정": flow.get("label", "데이터 없음"),
            "근거": (
                f"5일 합계 {flow['combined5']:+,.0f}주"
                if flow.get("available") else "자료 없음"
            ),
        },
        {
            "분석축": "개별주식선물 종합",
            "판정": futures_flow.get(
                "integrated_label", "데이터 없음"
            ),
            "근거": (
                f"{futures_flow.get('relation_label', '연계 판정 불가')} · "
                f"{futures_flow.get('position_label', '판정 불가')}"
                if futures_flow.get("available")
                else "자료 없음"
            ),
        },
        {
            "분석축": "시장 선물 환경",
            "판정": futures_flow.get("market_futures", {}).get(
                "label", "데이터 없음"
            ),
            "근거": (
                f"KOSPI200 외국인 5일 "
                f"{futures_flow['market_futures']['foreign5']:+,.0f}계약"
                if futures_flow.get("market_futures", {}).get("available")
                else "시장 보조자료 없음"
            ),
        },
        {
            "분석축": "공매도 압력",
            "판정": short_pressure.get("label", "데이터 없음"),
            "근거": (
                f"5일 공매도 비중 {short_pressure['avg5_ratio']:.2f}% · "
                f"잔고 변화 {short_pressure['balance_change_pct']:+.2f}%"
                if short_pressure.get("available")
                and pd.notna(short_pressure.get("avg5_ratio"))
                and pd.notna(short_pressure.get("balance_change_pct"))
                else "공매도 비중·잔고 일부 또는 전체 자료 없음"
            ),
        },
        {
            "분석축": "변동성·추격 위험",
            "판정": risk_view,
            "근거": (
                f"ATR14/종가 {atr_pct:.2f}% · "
                f"5일 수익률 {entry['return5']:+.2f}%"
                if pd.notna(atr_pct) else "ATR 표본 부족"
            ),
        },
    ]
    conclusion = (
        f"{entry['status']} — {entry['reason']} 각 분석축은 확정 신호가 아니라 "
        "가격·현물수급·파생 포지션·위험지표 사이의 교차 확인 근거입니다."
    )
    return rows, conclusion


def _signed_text(value, unit: str = ""):
    """표 표시용 부호 포함 문자열.

    v3.6 #10: st.column_config.NumberColumn(format=...)은 sprintf 규격을
    따르는데 쉼표 플래그가 없어 "%+,.0f"는 렌더 오류를 낸다. 파이썬에서
    미리 문자열로 만들어 넣는다.
    """
    if value is None or pd.isna(value):
        return "—"
    return f"{float(value):+,.0f}{unit}"


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
    market_futures_data: pd.DataFrame,
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

    # v3.6 #8: 두 번째 조건에도 상한을 둔다. 첫 조건만 60 상한이 있어
    # "10일 내 RSI<30 → 현재 RSI 90"도 '과매도 반등'으로 통과했다.
    rsi_rebound = bool(
        (35 <= rsi <= 60 and rsi > df["rsi14"].iloc[-4])
        or ((df["rsi14"].tail(10).min() < 30) and 30 < rsi < 70)
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
    market_futures = evaluate_market_futures_flow(market_futures_data)
    futures_flow = evaluate_stock_futures_context(
        stock_futures, raw_history, flow, market_futures
    )
    futures_flow.update({
        key: value
        for key, value in (stock_futures_meta or {}).items()
        if key in {
            "status", "source", "product_id", "product_name",
            "match_score", "filename",
        }
    })
    futures_available = futures_flow["flow_available"]

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

    # v3.6 #7: 신호 개수에 비례한 고정 비율로 통일한다. 기존 식은
    # formation 5→40%, 6→50%, 7→43% / uptrend 4→50%, 5→60%, 6→50%로
    # 신호가 늘수록 문턱 비율이 낮아져(= 판정이 쉬워져) 선물 CSV를
    # 올리는 것만으로 단계가 올라갈 수 있었다.
    form_threshold = max(2, math.ceil(formation_max * 0.5))
    up_threshold = max(2, math.ceil(uptrend_max * 0.6))

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
    integrated_evidence, integrated_conclusion = build_integrated_evidence(
        stage, df, rsi, rs20, benchmark_name, flow, futures_flow,
        short_pressure, entry,
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
        "integrated_evidence": integrated_evidence,
        "integrated_conclusion": integrated_conclusion,
    }
    return result


# ──────────────────────────────────────────────────────────────
# 3. 화면
# ──────────────────────────────────────────────────────────────
st.title("📈 개별종목 상승추세·매수구간 분석기")
st.caption(
    "검색에서 선택한 종목 한 개의 바닥·상승추세, 눌림목·돌파 가격, "
    "추격 위험을 판정합니다. "
    "한국은 현물수급과 개별주식선물의 수급·베이시스·거래량·미결제약정, "
    "지수선물·공매도·기술지표를 교차 분석하고, 미국은 가격·거래량·상대강도 "
    "기반으로 자동 판정합니다."
)

default_watchlist = _secret(
    "WATCHLIST",
    "KR:005930,KR:000660,KR:005380,US:NVDA,US:AVGO,US:GOOGL",
)
krx_auth_key = _secret("KRX_AUTH_KEY")
krx_login_id = _secret("KRX_ID")
krx_login_pw = _secret("KRX_PW")

query_candidates = parse_watchlist(
    st.query_params.get("stock", "")
    or st.query_params.get("stocks", "")
)
default_candidates = parse_watchlist(default_watchlist)
if "active_uid" not in st.session_state:
    legacy_watchlist = st.session_state.get("watchlist_uids", [])
    st.session_state["active_uid"] = (
        query_candidates[0]
        if query_candidates
        else legacy_watchlist[0]
        if legacy_watchlist
        else default_candidates[0]
        if default_candidates
        else "KR:005930"
    )
if "stock_labels" not in st.session_state:
    st.session_state["stock_labels"] = {}


def sync_active_stock_url():
    active = st.session_state.get("active_uid", "")
    if active:
        st.query_params["stock"] = active
    if "stocks" in st.query_params:
        del st.query_params["stocks"]


def uid_display(uid: str):
    market, symbol = split_uid(uid)
    label = st.session_state["stock_labels"].get(uid)
    flag = "🇰🇷" if market == MARKET_KR else "🇺🇸"
    return f"{flag} {label} ({symbol})" if label else f"{flag} {symbol}"


active_uid = st.session_state["active_uid"]
active_market, active_symbol = split_uid(active_uid)
futures_flow_uploads = []
short_selling_uploads = []
short_upload_targets = []


with st.sidebar:
    st.header("🔎 분석 종목 선택")
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
        if st.button("이 종목 분석", type="primary"):
            picked = result_map[picked_symbol]
            uid = make_uid(picked["market"], picked["symbol"])
            st.session_state["active_uid"] = uid
            st.session_state["stock_labels"][uid] = picked["name"]
            sync_active_stock_url()
            st.rerun()
    elif search_query.strip():
        label = "KOSPI·KOSDAQ" if market_choice == MARKET_KR else "미국 상장"
        st.info(f"{label} 종목 검색 결과가 없습니다.")

    st.divider()
    st.subheader("현재 분석 종목")
    st.info(uid_display(active_uid))

    st.divider()
    if active_market == MARKET_KR:
        if krx_auth_key:
            st.success("KRX Open API 키 설정됨 · 종가·주식선물 자동조회")
        else:
            st.info(
                "KRX Open API 키 미설정 · 주식선물 가격·거래량·OI 자동조회 불가"
            )
        st.caption(
            "선물·공매도 CSV를 올리면 현재 분석 종목에 바로 적용합니다."
        )

        st.subheader("📄 개별주식선물 자료")
        futures_flow_uploads = st.file_uploader(
            "선물 CSV(여러 파일 병합)",
            type=["csv"],
            accept_multiple_files=True,
            help=(
                "현재 종목의 투자자별 수급·선물시세 CSV를 함께 올릴 수 "
                "있습니다. 일자를 기준으로 자동 병합합니다."
            ),
            key=f"futures_csv_{active_uid}",
        )
        futures_template = pd.DataFrame({
            "종목코드": [active_symbol, active_symbol],
            "일자": ["2026-07-28", "2026-07-29"],
            "외국인순매수": [1200, -350],
            "기관순매수": [-400, 600],
            "현물종가": [150000, 151200],
            "선물종가": [150200, 151000],
            "선물거래량": [28600, 33100],
            "미결제약정": [105000, 106500],
            "만기일": ["2026-09-10", "2026-09-10"],
        }).to_csv(index=False).encode("utf-8-sig")
        st.download_button(
            "선물 CSV 양식",
            futures_template,
            file_name=f"{active_symbol}_stock_futures_template.csv",
            mime="text/csv",
        )
        st.caption(
            "KRX 조회구분은 '일별추이'로 내려받으세요. 업로드 자료는 현재 "
            "분석 종목에 적용됩니다."
        )

        st.subheader("📄 KRX 공매도 자료")
        short_selling_uploads = st.file_uploader(
            "공매도 종합정보 CSV(여러 파일 병합)",
            type=["csv"],
            accept_multiple_files=True,
            help=(
                "KRX 개별종목 공매도 종합정보에서 내려받은 CSV를 올리세요. "
                "공매도 거래량과 순보유잔고를 일자별로 병합합니다."
            ),
            key=f"short_csv_{active_uid}",
        )
        short_upload_targets = [active_uid] * len(short_selling_uploads)
        short_template = pd.DataFrame({
            "일자": ["2026-07-28", "2026-07-29"],
            "공매도 거래량": [125000, 142000],
            "업틱룰 적용 거래량": [120000, 137000],
            "업틱룰 예외 거래량": [5000, 5000],
            "순보유잔고 수량": [3200000, 3150000],
            "공매도 거래대금": [18750000000, 21400000000],
            "순보유잔고 금액": [480000000000, 476000000000],
        }).to_csv(index=False).encode("utf-8-sig")
        st.download_button(
            "공매도 CSV 양식",
            short_template,
            file_name=f"{active_symbol}_short_selling_template.csv",
            mime="text/csv",
        )
        st.caption(
            "KRX 정보데이터시스템 → 공매도 → 개별종목 공매도 종합정보 → "
            "기간 조회 → CSV 다운로드 순서입니다. v3.5부터 공매도 "
            "자동수집은 사용하지 않으므로, CSV를 올리지 않으면 공매도 축은 "
            "중립으로 계산합니다."
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

uids = [active_uid]

futures_upload_datasets, futures_upload_errors = (
    parse_stock_futures_uploads(futures_flow_uploads)
)
if futures_upload_errors:
    st.warning(
        "개별주식선물 CSV 일부를 읽지 못했습니다: "
        + " / ".join(futures_upload_errors)
    )
short_upload_datasets, short_upload_errors = (
    parse_short_selling_uploads(
        short_selling_uploads, short_upload_targets
    )
)
if short_upload_errors:
    st.warning(
        "공매도 CSV 일부를 읽지 못했습니다: "
        + " / ".join(short_upload_errors)
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
        f"개별주식선물 CSV {len(futures_upload_datasets)}개 데이터 묶음을 "
        "우선 반영합니다."
    )
elif kr_stock_count and not futures_auto_access:
    st.caption(
        f"KRX 개별주식선물 투자자 통계 자동조회 제한({futures_auto_status}) · "
        "필요한 종목의 KRX·HTS CSV를 업로드하면 분석됩니다."
    )
if short_upload_datasets:
    uploaded_short = short_upload_datasets.get(active_uid, {})
    st.caption(
        f"공매도 CSV {len(uploaded_short.get('filenames', []))}개를 "
        "현재 종목에 우선 반영합니다."
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

kospi200_futures_flow = pd.DataFrame(
    columns=["foreign", "institution"]
)
if MARKET_KR in markets_present:
    try:
        kospi200_futures_flow = fetch_kospi200_futures_investor_flow()
    except Exception:
        pass

empty_benchmark = pd.DataFrame(columns=["close"])
labels = st.session_state["stock_labels"]
analyses, failures = {}, {}
futures_skip_notes = []
with st.spinner("선택 종목 분석 중..."):
    with ThreadPoolExecutor(max_workers=min(8, len(uids))) as pool:
        future_map = {
            pool.submit(
                fetch_bundle,
                uid,
                labels.get(uid, ""),
                krx_login_id,
                krx_login_pw,
                krx_auth_key,
                True,  # skip_short: v3.5부터 공매도는 CSV 업로드만 사용
            ): uid
            for uid in uids
        }
        for future in as_completed(future_map):
            uid = future_map[future]
            market, symbol = split_uid(uid)
            try:
                basic, history, investor, short_selling = future.result()
                uploaded_short = short_upload_datasets.get(uid)
                if uploaded_short is not None:
                    short_selling = uploaded_short["frame"].copy()
                    short_selling.attrs.update({
                        "status": "업로드 정상",
                        "source": uploaded_short["source"],
                        "filenames": ", ".join(
                            uploaded_short["filenames"]
                        ),
                    })
                stock_futures = pd.DataFrame()
                stock_futures_meta = {
                    "status": "해당 없음",
                    "source": "",
                }
                if market == MARKET_KR:
                    source_names = []
                    status_notes = []
                    uploaded_match, skipped_futures = (
                        match_uploaded_stock_futures(
                            futures_upload_datasets,
                            symbol,
                            basic.get("name", labels.get(uid, symbol)),
                            kr_stock_count,
                        )
                    )
                    if skipped_futures:
                        futures_skip_notes.extend(skipped_futures)
                    if uploaded_match is not None:
                        stock_futures = uploaded_match["frame"].copy()
                        source_names.append(uploaded_match["source"])
                        status_notes.append("업로드 정상")
                        stock_futures_meta.update({
                            "filename": uploaded_match["filename"],
                            "product_name": (
                                uploaded_match.get("name")
                                or basic.get("name", symbol)
                            ),
                        })
                    elif futures_auto_access:
                        flow_frame, flow_meta = (
                            fetch_stock_futures_flow_auto(
                                basic.get("name", labels.get(uid, symbol))
                            )
                        )
                        if not flow_frame.empty:
                            stock_futures = flow_frame.copy()
                            source_names.append(
                                flow_meta.get("source", "KRX 투자자통계")
                            )
                        status_notes.append(
                            "투자자수급 " + flow_meta.get("status", "확인불가")
                        )
                    else:
                        status_notes.append(
                            f"투자자수급 {futures_auto_status}"
                        )

                    market_frame, market_meta = (
                        fetch_stock_futures_market_openapi(
                            krx_auth_key,
                            basic.get("name", labels.get(uid, symbol)),
                            basic.get("sosok", ""),
                        )
                    )
                    if not market_frame.empty:
                        # 공식 시세가 업로드 값보다 우선하고 수급 열은 보존한다.
                        if stock_futures.empty:
                            stock_futures = market_frame.copy()
                        else:
                            stock_futures = stock_futures.reindex(
                                stock_futures.index.union(market_frame.index)
                            )
                            for column in market_frame.columns:
                                official = market_frame[column]
                                if column in stock_futures:
                                    stock_futures[column] = (
                                        official.combine_first(
                                            stock_futures[column]
                                        )
                                    )
                                else:
                                    stock_futures = stock_futures.join(
                                        official.rename(column), how="outer"
                                    )
                        stock_futures = stock_futures.sort_index()
                        source_names.append("KRX Open API")
                        for key in (
                            "product_id", "product_name",
                        ):
                            if market_meta.get(key):
                                stock_futures_meta[key] = market_meta[key]
                    status_notes.append(
                        "선물시세 " + market_meta.get("status", "확인불가")
                    )
                    stock_futures_meta.update({
                        "status": " / ".join(status_notes),
                        "source": " + ".join(dict.fromkeys(source_names))
                        or "KRX 자동조회",
                    })
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
                    kospi200_futures_flow,
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
                            kospi200_futures_flow,
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

if futures_skip_notes:
    st.warning(
        "다른 종목으로 표시된 선물 CSV는 적용하지 않았습니다: "
        + " / ".join(dict.fromkeys(futures_skip_notes))
        + " — 현재 분석 종목의 자료만 올리세요."
    )
if failures:
    st.warning(
        "분석 제외: "
        + " / ".join(f"{code}({message})" for code, message in failures.items())
    )
if not analyses:
    st.error("분석 가능한 종목이 없습니다.")
    st.stop()

selected_uid = active_uid
if selected_uid not in analyses:
    st.error("현재 선택 종목을 분석하지 못했습니다.")
    st.stop()
selected = analyses[selected_uid]
if selected["basic"]["name"] != split_uid(selected_uid)[1]:
    st.session_state["stock_labels"][selected_uid] = selected["basic"]["name"]
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
    "현·선물 종합",
    futures_flow["integrated_label"]
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
    key: f"{value}/{entry['component_max'].get(key, '—')}"
    for key, value in entry["components"].items()
}
st.dataframe(
    pd.DataFrame([component_row], index=["진입점수 구성"]),
    width="stretch",
)
st.caption(
    f"진입점수 {entry['score']}/100 · {entry.get('score_basis', '—')} — "
    "해당 시장에 존재하지 않는 축은 중립값으로 채우지 않고 배점에서 빼고 "
    "100점으로 환산합니다(v3.6). 한국인데 응답만 없는 일시적 결측은 "
    "기존대로 중립 50으로 둡니다."
)
st.markdown("### 종합 교차분석 근거")
st.dataframe(
    pd.DataFrame(selected["integrated_evidence"]),
    width="stretch",
    hide_index=True,
)
st.info(selected["integrated_conclusion"])
st.caption(
    "가격 추세를 1차 축으로 두고 모멘텀·현물 거래활동·시장 대비 상대강도, "
    "현물과 선물 수급, 베이시스·미결제약정, 지수선물·공매도·ATR 위험을 "
    "교차 확인합니다. 어느 한 지표만으로 매수·매도를 확정하지 않습니다."
)
if sel_market == MARKET_US:
    st.caption(
        "미국 종목은 현물 외국인·기관 구분 수급, KRX 공매도, 개별주식선물이 "
        "구조적으로 없어 점수 축에서 제외하고 추세·가격위치·거래량 65점을 "
        "100점으로 환산합니다. v3.5까지는 없는 축을 중립 50으로 채워 상한이 "
        "83점에 갇혔고, 임계값 70/65/55는 시장 공통이라 미국이 불리했습니다."
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
            "최근 5일(주)": _signed_text(flow["foreign5"]),
            "최근 10일(주)": _signed_text(flow["foreign10"]),
            "최근 변화": flow["foreign_momentum"],
        },
        {
            "주체": "기관",
            "최근 5일(주)": _signed_text(flow["institution5"]),
            "최근 10일(주)": _signed_text(flow["institution10"]),
            "최근 변화": flow["institution_momentum"],
        },
        {
            "주체": "합계",
            "최근 5일(주)": _signed_text(flow["combined5"]),
            "최근 10일(주)": _signed_text(flow["combined10"]),
            "최근 변화": _flow_momentum(
                selected["investor"]["foreign"].fillna(0)
                + selected["investor"]["institution"].fillna(0)
            ),
        },
    ])
    f1, f2 = st.columns([1, 2])
    with f1:
        st.metric("줄다리기 판정", flow["label"])
        st.metric("수급점수", f"{flow['score']}/100")
        st.caption(
            f"최근 반영일: {fmt_date(flow['latest_date'])}"
        )
    with f2:
        st.dataframe(flow_table, width="stretch", hide_index=True)
    flow_chart = selected["investor"][["foreign", "institution"]].tail(20).rename(
        columns={"foreign": "외국인", "institution": "기관"}
    )
    st.bar_chart(flow_chart, height=220)
else:
    st.info("투자자별 수급 응답이 없어 가격·거래량만으로 진입점수를 계산했습니다.")

st.markdown("### 개별주식선물·현물 연계 종합분석")
if not sel_meta["has_stock_futures_flow"]:
    st.info("미국 종목은 KRX 개별주식선물 수급 분석 대상이 아닙니다.")
elif futures_flow["available"]:
    ff1, ff2, ff3, ff4, ff5, ff6 = st.columns(6)
    ff1.metric("종합판정", futures_flow["integrated_label"])
    ff2.metric("선물 종합점수", f"{futures_flow['score']}/100")
    ff3.metric("현·선물 관계", futures_flow["relation_label"])
    ff4.metric(
        "베이시스(S-F)",
        (
            f"{futures_flow['basis_latest']:+,.2f}"
            f" ({futures_flow['basis_pct_latest']:+.3f}%)"
            if futures_flow["basis_available"]
            else futures_flow["basis_label"]
        ),
    )
    ff5.metric(
        "선물 거래활동",
        (
            f"5일/20일 {futures_flow['volume_ratio20']:.2f}배"
            if pd.notna(futures_flow["volume_ratio20"])
            else (
                f"5일 평균 {futures_flow['volume_avg5']:,.0f}"
                if futures_flow["volume_available"] else "자료 없음"
            )
        ),
    )
    ff6.metric(
        "미결제약정 5일",
        (
            f"{futures_flow['oi_change']:+,.0f}계약"
            f" ({futures_flow['oi_change_pct']:+.2f}%)"
            if futures_flow["oi_available"]
            else (
                f"최근 {futures_flow['oi_latest']:,.0f}계약"
                if pd.notna(futures_flow["oi_latest"])
                else "자료 없음"
            )
        ),
    )

    st.dataframe(
        pd.DataFrame(futures_flow["diagnostics"]),
        width="stretch",
        hide_index=True,
    )

    futures_series = futures_flow["series"].copy()
    if futures_flow["flow_available"]:
        futures_table = pd.DataFrame([
            {
                "주체": "외국인",
                "최근 5일(계약)": _signed_text(futures_flow["foreign5"]),
                "최근 10일(계약)": _signed_text(futures_flow["foreign10"]),
                "최근 변화": futures_flow["foreign_momentum"],
            },
            {
                "주체": "기관",
                "최근 5일(계약)": _signed_text(futures_flow["institution5"]),
                "최근 10일(계약)": _signed_text(futures_flow["institution10"]),
                "최근 변화": futures_flow["institution_momentum"],
            },
            {
                "주체": "합계",
                "최근 5일(계약)": _signed_text(futures_flow["combined5"]),
                "최근 10일(계약)": _signed_text(futures_flow["combined10"]),
                "최근 변화": _flow_momentum(
                    futures_series["foreign"].fillna(0)
                    + futures_series["institution"].fillna(0)
                ),
            },
        ])
        fc1, fc2 = st.columns([1, 2])
        with fc1:
            st.metric("개별선물 수급", futures_flow["label"])
            st.metric("가격×OI", futures_flow["position_label"])
            st.metric(
                "외국인 5일",
                f"{futures_flow['foreign5']:+,.0f}계약",
            )
            st.metric(
                "기관 5일",
                f"{futures_flow['institution5']:+,.0f}계약",
            )
        with fc2:
            st.dataframe(futures_table, width="stretch", hide_index=True)
        flow_chart = (
            futures_series[["foreign", "institution"]]
            .dropna(how="all")
            .tail(20)
            .rename(columns={"foreign": "외국인", "institution": "기관"})
        )
        if not flow_chart.empty:
            st.markdown("#### 개별주식선물 투자자 순매수")
            st.bar_chart(flow_chart, height=220)
    else:
        st.info(
            "선물 시세·거래량·미결제약정은 분석했지만 투자자별 순매수 열은 "
            "없습니다. KRX 투자자별 일별추이 CSV를 추가하면 현·선물 수급 "
            "관계까지 판정합니다."
        )

    chart_columns = []
    if futures_flow["basis_available"] and "basis" in futures_series:
        chart_columns.append(("베이시스(S-F)", "basis", "line"))
    if futures_flow["volume_available"] and "futures_volume" in futures_series:
        chart_columns.append(("선물 거래량", "futures_volume", "bar"))
    if pd.notna(futures_flow["oi_latest"]) and "open_interest" in futures_series:
        chart_columns.append(("미결제약정", "open_interest", "line"))
    if chart_columns:
        chart_slots = st.columns(len(chart_columns))
        for slot, (title, column, kind) in zip(chart_slots, chart_columns):
            with slot:
                st.markdown(f"#### {title}")
                chart_frame = futures_series[[column]].dropna().tail(40)
                if kind == "bar":
                    st.bar_chart(chart_frame, height=220)
                else:
                    st.line_chart(chart_frame, height=220)

    st.info(futures_flow["integrated_interpretation"])
    if not futures_flow["market_data_available"]:
        st.warning(
            "현재는 투자자 수급 중심 분석입니다. 선물종가·거래량·미결제약정 "
            "일별 CSV를 추가하면 베이시스, 신규계약/청산, 거래활동을 "
            "함께 판정합니다."
        )
    if futures_flow["rollover_suspected"]:
        st.warning(
            "만기 근접과 미결제약정 급감이 겹쳤습니다. 방향성 청산보다 "
            "차근월물 롤오버 가능성을 먼저 확인하세요."
        )
    source = futures_flow.get("source") or "출처 확인불가"
    product = futures_flow.get("product_name") or basic["name"]
    latest = futures_flow["latest_date"]
    filename = futures_flow.get("filename")
    st.caption(
        f"기초자산·상품: {product} · 최근 반영일: "
        f"{fmt_date(latest, '확인불가')}"
        f" · 출처: {source} · 수집상태: "
        f"{futures_flow.get('status', '확인불가')}"
        + (f" ({filename})" if filename else "")
    )
    st.caption(
        "방법론: Hull, Options, Futures, and Other Derivatives 9판 Ch.2·3·5. "
        "베이시스는 S-F로 계산하며 만기에 가까워질수록 현·선물 가격이 "
        "수렴합니다. 거래량은 당일 체결 계약 수, 미결제약정은 남아 있는 "
        "계약 수이므로 서로 대체할 수 없습니다. 배당·금리·잔존만기가 "
        "베이시스에 영향을 주기 때문에 부호 하나만으로 방향을 단정하지 않습니다."
    )
else:
    status = futures_flow.get("status") or "응답 없음"
    st.info(
        f"개별주식선물 데이터 없음 ({status}). KRX·HTS에서 일별추이로 "
        "내려받은 투자자별 순매수 CSV와 선물종가·거래량·미결제약정 CSV를 "
        "왼쪽 업로더에 넣으면 자동 병합해 분석과 진입점수에 반영합니다."
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
        f"{fmt_date(trade_date)} · "
        "잔고 공시 최근일 "
        f"{fmt_date(balance_date)} · "
        "KRX+NXT 전체 당일 거래는 통상 18:10 이후, 공매도 잔고는 T+2 지연 반영"
        + stale_note
    )
    st.caption(
        f"출처: {short_pressure.get('source', 'KRX Data Marketplace')} · "
        f"수집상태: {short_pressure.get('status', '정상')}"
    )
else:
    st.markdown("### KRX 공매도 압력")
    short_status = short_pressure.get("status", "응답 없음")
    if short_status == "공매도 CSV 미업로드":
        st.info(
            "공매도 CSV가 아직 업로드되지 않았습니다. 왼쪽의 KRX 공매도 "
            "자료에 CSV를 올리기 전까지 공매도 항목은 중립값으로 계산합니다."
        )
    else:
        st.warning(
            f"공매도 CSV 처리 실패: {short_status}. "
            "공매도 항목은 중립값으로 계산했습니다."
        )
    # v3.6 #11: 자동수집이 제거된 v3.5 이후 '로그인 필요'·'HTTP 403'
    # 상태는 발생할 수 없다. 실제로 나올 수 있는 CSV 파싱 실패만 안내한다.
    if short_status != "공매도 CSV 미업로드":
        st.caption(
            "CSV는 KRX 화면에서 조회를 끝낸 뒤 내려받아야 합니다. 조회 전 "
            "받은 파일은 CSV가 아니라 HTML이라 열 구조를 찾지 못합니다. "
            "'일자'와 '공매도 거래량' 또는 '순보유잔고 수량' 열이 있어야 "
            "합니다."
        )

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
        # v3.6 #1: close·change_pct가 None이면 이전 판은 f-string에서
        # TypeError로 페이지 전체가 죽었다. 또한 "대조 정상"이라고만
        # 적고 실제 비교는 하지 않았으므로 네이버 일봉과 실대조한다.
        krx_close = krx.get("close")
        krx_change = krx.get("change_pct")
        base_text = (
            f"KRX 공식 확정치 {fmt_date(krx.get('date'))} · 종가 "
            f"{_money(krx_close, MARKET_KR) if krx_close is not None else '—'}"
            f" / 등락률 "
            f"{f'{krx_change:+.2f}%' if krx_change is not None else '—'}"
        )
        krx_stamp = pd.Timestamp(krx["date"]) if krx.get("date") else None
        naver_close = (
            float(history.loc[krx_stamp, "close"])
            if krx_stamp is not None and krx_stamp in history.index
            else None
        )
        if naver_close is not None and krx_close is not None:
            tolerance = max(1.0, abs(krx_close) * 0.001)
            if abs(naver_close - krx_close) <= tolerance:
                st.success(base_text + " · 네이버 일봉과 일치")
            else:
                st.warning(
                    base_text
                    + f" · 네이버 일봉({_money(naver_close, MARKET_KR)})과 "
                    "불일치 — 수정주가·기준일 차이 가능성, 원천 확인 필요"
                )
        else:
            st.info(base_text + " · 같은 일자의 일봉이 없어 대조는 못 했습니다")
    else:
        st.caption(f"KRX 공식 확정치: {krx.get('status', '확인불가')}")
else:
    st.caption("미국 종목: 야후 파이낸스 수정주가 기준 (KRX 대조 없음)")

source_note = (
    "네이버 장중/일봉·현물 투자자 수급·KOSPI200 선물 수급, "
    "KRX Open API 개별주식선물 시세·거래량·미결제약정, "
    "KRX/HTS 개별주식선물 투자자 수급, 업로드 KRX 공매도 통계와 "
    "확정 일별 통계를 대조·가공"
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
