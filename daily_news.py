import os, re, requests, smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timedelta
from googletrans import Translator

# 환경 변수 로드
NEWS_API_KEY = os.getenv("NEWS_API_KEY")
GMAIL_USER = os.getenv("GMAIL_USER")
GMAIL_APP_PW = os.getenv("GMAIL_APP_PW")
RECEIVER_EMAIL = "sjkim@mbc.co.kr"

translator = Translator()

# ──────────────────────────────────────────────
# 1. 신뢰할 수 있는 출처 (Tier별 가중치)
# ──────────────────────────────────────────────
TIER1_SOURCES = {
    'reuters.com', 'apnews.com', 'bloomberg.com', 'wsj.com',
    'nytimes.com', 'ft.com', 'bbc.com', 'bbc.co.uk',
}
TIER2_SOURCES = {
    'techcrunch.com', 'theverge.com', 'arstechnica.com', 'wired.com',
    'cnbc.com', 'fortune.com', 'businessinsider.com',
    'tomshardware.com', 'anandtech.com', 'semianalysis.com',
}
TIER3_SOURCES = {
    'zdnet.com', 'cnet.com', 'engadget.com', 'venturebeat.com',
    'theinformation.com', 'protocol.com', 'thenextweb.com',
    'macrumors.com', '9to5mac.com', 'electrek.co',
}

# ──────────────────────────────────────────────
# 2. 관련성 키워드 (카테고리별 가중치)
# ──────────────────────────────────────────────
HIGH_VALUE_KEYWORDS = [
    'earnings', 'revenue', 'acquisition', 'merger', 'antitrust',
    'regulation', 'breakthrough', 'launch', 'partnership',
    'quarterly results', 'guidance', 'forecast',
]
CORE_TECH_KEYWORDS = [
    'AI', 'artificial intelligence', 'generative AI', 'LLM',
    'GPU', 'semiconductor', 'chip', 'foundry', 'HBM',
    'data center', 'cloud computing', 'autonomous driving',
    'quantum computing', 'robotics', 'humanoid',
]

# ──────────────────────────────────────────────
# 3. 투자자 영향도 키워드 (가중치별 분류)
# ──────────────────────────────────────────────
# 주가·시가총액에 직접 영향을 주는 이벤트
INVESTOR_HIGH_IMPACT = [
    'earnings', 'quarterly results', 'revenue miss', 'revenue beat',
    'profit warning', 'guidance', 'forecast', 'downgrade', 'upgrade',
    'price target', 'stock split', 'buyback', 'share repurchase',
    'dividend', 'IPO', 'delisting', 'SEC', 'investigation',
    'class action', 'insider trading', 'short selling',
]
# 중장기 투자 판단에 영향을 주는 구조적 이벤트
INVESTOR_MID_IMPACT = [
    'acquisition', 'merger', 'takeover', 'antitrust', 'regulation',
    'tariff', 'sanction', 'export ban', 'supply chain',
    'market share', 'market cap', 'valuation', 'analyst',
    'hedge fund', 'institutional investor', 'activist investor',
    'bond', 'credit rating', 'bankruptcy', 'restructuring',
]
# 시장 심리·매크로 환경
INVESTOR_SENTIMENT = [
    'bull market', 'bear market', 'rally', 'sell-off', 'crash',
    'volatility', 'inflation', 'interest rate', 'fed', 'recession',
    'GDP', 'unemployment', 'consumer spending', 'yield curve',
]

# ──────────────────────────────────────────────
# 4. 스팸/광고 필터 패턴
# ──────────────────────────────────────────────
SPAM_PATTERNS = [
    r'(?i)\b(buy now|discount|coupon|promo code|limited offer)\b',
    r'(?i)\b(click here|subscribe now|sign up free)\b',
    r'(?i)\b(sponsored|advertisement|paid content|partner content)\b',
    r'(?i)\b(horoscope|lottery|casino|crypto airdrop)\b',
    r'(?i)^\d+\s+(best|top)\s+',  # "10 best ..." 리스트형 낚시 기사
]


def _source_domain(article):
    """기사 URL에서 도메인 추출"""
    url = article.get('url', '')
    match = re.search(r'https?://(?:www\.)?([^/]+)', url)
    return match.group(1).lower() if match else ''


def _source_score(article):
    """출처 신뢰도 점수 (0~25)"""
    domain = _source_domain(article)
    if any(s in domain for s in TIER1_SOURCES):
        return 25
    if any(s in domain for s in TIER2_SOURCES):
        return 17
    if any(s in domain for s in TIER3_SOURCES):
        return 8
    return 0


def _relevance_score(article):
    """키워드 관련성 점수 (0~25)"""
    text = f"{article.get('title', '')} {article.get('description', '')}".lower()
    score = 0
    for kw in HIGH_VALUE_KEYWORDS:
        if kw.lower() in text:
            score += 4
    for kw in CORE_TECH_KEYWORDS:
        if kw.lower() in text:
            score += 3
    return min(score, 25)


def _investor_impact_score(article):
    """투자자 영향도 점수 (0~30)"""
    text = f"{article.get('title', '')} {article.get('description', '')}".lower()
    score = 0
    # 직접 영향 이벤트 (가장 높은 가중치)
    for kw in INVESTOR_HIGH_IMPACT:
        if kw.lower() in text:
            score += 5
    # 구조적 이벤트 (중간 가중치)
    for kw in INVESTOR_MID_IMPACT:
        if kw.lower() in text:
            score += 3
    # 시장 심리·매크로 (낮은 가중치)
    for kw in INVESTOR_SENTIMENT:
        if kw.lower() in text:
            score += 2
    return min(score, 30)


def _recency_score(article):
    """최신성 점수 (0~15) — 최근 6시간 이내 기사 우대"""
    published = article.get('publishedAt', '')
    try:
        pub_dt = datetime.strptime(published, '%Y-%m-%dT%H:%M:%SZ')
        hours_ago = (datetime.utcnow() - pub_dt).total_seconds() / 3600
        if hours_ago <= 6:
            return 15
        elif hours_ago <= 12:
            return 11
        elif hours_ago <= 24:
            return 7
        return 3
    except (ValueError, TypeError):
        return 3


def _is_spam(article):
    """스팸/광고성 기사 판별"""
    text = f"{article.get('title', '')} {article.get('description', '')}"
    return any(re.search(p, text) for p in SPAM_PATTERNS)


def _is_duplicate(article, seen_titles):
    """제목 유사도 기반 중복 기사 판별"""
    title = article.get('title', '').lower().strip()
    if not title:
        return True
    # 제목에서 핵심 단어만 추출하여 비교 (짧은 공통 단어 제거)
    words = set(re.findall(r'[a-z]{4,}', title))
    for seen in seen_titles:
        overlap = words & seen
        # 핵심 단어의 60% 이상이 겹치면 중복으로 판단
        if words and len(overlap) / len(words) >= 0.6:
            return True
    seen_titles.append(words)
    return False


def _total_score(article):
    """종합 점수 = 출처(25) + 관련성(25) + 투자자영향도(30) + 최신성(15) + 보너스(5)"""
    score = (
        _source_score(article)
        + _relevance_score(article)
        + _investor_impact_score(article)
        + _recency_score(article)
    )
    # 이미지가 있고 설명이 충분한 기사에 소폭 보너스
    if article.get('urlToImage'):
        score += 3
    desc = article.get('description', '') or ''
    if len(desc) >= 100:
        score += 2
    return score


def get_tech_news():
    # ── 검색 쿼리: M7 + 반도체 + 기술 트렌드 ──
    m7 = 'NVIDIA OR Apple OR Microsoft OR Tesla OR Meta OR Amazon OR Alphabet'
    chips = 'TSMC OR "Samsung Electronics" OR "SK Hynix" OR ASML OR Intel'
    tech_trends = 'AI OR "Generative AI" OR GPU OR Semiconductor OR "Data Center"'

    combined_query = f"({m7} OR {chips}) AND ({tech_trends} OR Investment OR Market OR Earnings)"

    # 넉넉하게 50개를 가져온 뒤 필터링·스코어링으로 상위 10개 선별
    url = (
        f"https://newsapi.org/v2/everything?"
        f"q={combined_query}&sortBy=publishedAt&pageSize=50"
        f"&language=en&apiKey={NEWS_API_KEY}"
    )

    try:
        res = requests.get(url)
        data = res.json()
        articles = data.get('articles', [])
    except Exception as e:
        print(f"API 요청 에러: {e}")
        return []

    # ── 필터링 파이프라인 ──
    # 1단계: 스팸/광고 제거
    articles = [a for a in articles if not _is_spam(a)]

    # 2단계: [Removed] 표기 기사 제거 (News API에서 삭제된 기사)
    articles = [a for a in articles if a.get('title') and '[Removed]' not in a['title']]

    # 3단계: 중복 기사 제거
    seen_titles = []
    unique_articles = []
    for a in articles:
        if not _is_duplicate(a, seen_titles):
            unique_articles.append(a)
    articles = unique_articles

    # 4단계: 종합 점수 기반 정렬
    articles.sort(key=_total_score, reverse=True)

    # 상위 10개 선별
    top_articles = articles[:10]
    print(f"[선별 결과] 전체 {len(data.get('articles', []))}건 → 필터링 후 {len(articles)}건 → 최종 {len(top_articles)}건")
    for i, a in enumerate(top_articles, 1):
        print(f"  {i}. [{_total_score(a)}점] {a.get('title', '')[:60]}... ({_source_domain(a)})")

    return top_articles
        
def translate_text(text):
    try:
        if not text: return "내용 없음"
        return translator.translate(text, src='en', dest='ko').text
    except:
        return text

if __name__ == "__main__":
    articles = get_tech_news()
    
    msg = MIMEMultipart()
    msg['Subject'] = f"[Tech 24h] {datetime.now().strftime('%m/%d')} 핵심 뉴스레터"
    msg['From'] = f"Tech Bot <{GMAIL_USER}>"
    msg['To'] = RECEIVER_EMAIL

    if articles:
        items_html = ""
        for i, art in enumerate(articles, 1):
            ko_title = translate_text(art['title'])
            ko_desc = translate_text(art.get('description', '본문 내용 없음'))
            source_name = art.get('source', {}).get('name', '알 수 없음')
            score = _total_score(art)
            inv_score = _investor_impact_score(art)
            # 점수 구간별 뱃지 색상
            if score >= 60:
                badge_color, badge_text = '#d93025', '🔴 TOP'
            elif score >= 40:
                badge_color, badge_text = '#f9a825', '🟡 주목'
            else:
                badge_color, badge_text = '#aaa', '⚪ 일반'
            # 투자자 영향도 뱃지
            if inv_score >= 20:
                inv_badge = '<span style="background:#d93025; color:#fff; padding:2px 6px; border-radius:10px; font-size:10px; margin-left:5px;">📈 투자영향 높음</span>'
            elif inv_score >= 10:
                inv_badge = '<span style="background:#f9a825; color:#fff; padding:2px 6px; border-radius:10px; font-size:10px; margin-left:5px;">📊 투자영향 중간</span>'
            else:
                inv_badge = ''
            items_html += f"""
            <div style='margin-bottom:25px; border-bottom:1px solid #eee; padding-bottom:15px;'>
                <div style='display:flex; align-items:center; flex-wrap:wrap; margin-bottom:8px;'>
                    <span style='background:{badge_color}; color:#fff; padding:2px 8px; border-radius:10px; font-size:11px; margin-right:8px;'>{badge_text}</span>
                    <span style='color:#999; font-size:12px;'>{source_name} · 종합 {score}점</span>
                    {inv_badge}
                </div>
                <h3 style='color:#1a73e8; margin:0 0 10px 0;'>{ko_title}</h3>
                <p style='color:#555; font-size:14px; margin:0 0 10px 0;'>{ko_desc}</p>
                <a href='{art["url"]}' style='color:#1a73e8; text-decoration:none; font-size:13px;'>원문보기(EN) →</a>
            </div>
            """
        body = f"<html><body><h2 style='color:#333;'>지난 24시간 주요 테크 뉴스 (AI 선별)</h2>{items_html}</body></html>"
    else:
        body = "<html><body><h2>최근 24시간 내에 수집된 뉴스가 없습니다.</h2><p>검색 범위를 조정하거나 다음 실행을 기다려주세요.</p></body></html>"

    msg.attach(MIMEText(body, 'html'))

    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(GMAIL_USER, GMAIL_APP_PW)
            server.send_message(msg)
        print("24시간 한정 뉴스레터 발송 완료!")
    except Exception as e:
        print(f"메일 발송 에러: {e}")

