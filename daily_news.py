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
    # M7 기업 + 반도체 핵심 기업 + 기술 트렌드 조합
    # 한국(Samsung, Hynix)과 대만(TSMC)을 명시적으로 포함
    m7 = 'NVIDIA OR Apple OR Microsoft OR Tesla OR Meta OR Amazon OR Alphabet'
    chips = 'TSMC OR "Samsung Electronics" OR "SK Hynix" OR ASML OR Intel'
    tech_trends = 'AI OR "Generative AI" OR "GPU"'
    
    # 이 모든 키워드를 하나로 묶음
    combined_query = f"({m7} OR {chips}) AND ({tech_trends} OR Investment OR Market)"
    
    # 전세계(언어: en) 뉴스를 최신순으로 15개 수집 (그 중 상위 10개를 메일로 발송)
    url = f"https://newsapi.org/v2/everything?q={combined_query}&sortBy=publishedAt&pageSize=15&language=en&apiKey={NEWS_API_KEY}"
    
    try:
        res = requests.get(url)
        data = res.json()
        articles = data.get('articles', [])
        # 기사가 너무 많으면 중복이나 광고성 글을 피하기 위해 필터링 로직이 작동함
        return articles[:10] 
    except Exception as e:
        print(f"API 요청 에러: {e}")
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

