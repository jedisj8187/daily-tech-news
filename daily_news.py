import os, requests, smtplib
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

def get_tech_news():
    # 1. 현재 시간 기준으로 24시간 전 시간 계산 (UTC 기준)
    time_24_hours_ago = (datetime.utcnow() - timedelta(days=1)).isoformat()
    
    # 2. 검색 쿼리 설정
    query = "(semiconductor OR NVIDIA OR TSMC OR 'Samsung Electronics' OR AI)"
    
    # 3. 'from' 파라미터에 24시간 전 시간 추가
    url = (
        f"https://newsapi.org/v2/everything?q={query}"
        f"&from={time_24_hours_ago}"
        f"&sortBy=publishedAt&pageSize=10&language=en&apiKey={NEWS_API_KEY}"
    )
    
    try:
        res = requests.get(url)
        articles = res.json().get('articles', [])
        return articles
    except Exception as e:
        print(f"뉴스 수집 중 오류: {e}")
        return []

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
        for art in articles:
            ko_title = translate_text(art['title'])
            ko_desc = translate_text(art.get('description', '본문 내용 없음'))
            items_html += f"""
            <div style='margin-bottom:25px; border-bottom:1px solid #eee; padding-bottom:15px;'>
                <h3 style='color:#1a73e8; margin-bottom:10px;'>{ko_title}</h3>
                <p style='color:#555; font-size:14px;'>{ko_desc}</p>
                <a href='{art['url']}' style='color:#1a73e8; text-decoration:none; font-size:13px;'>원문보기(EN) →</a>
            </div>
            """
        body = f"<html><body><h2 style='color:#333;'>지난 24시간 주요 테크 뉴스</h2>{items_html}</body></html>"
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
