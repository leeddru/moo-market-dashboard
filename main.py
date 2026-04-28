import yfinance as yf
from fredapi import Fred
import os
# import google.generativeai as genai
from google import genai
import datetime
import json
from datetime import timedelta, timezone
import fear_and_greed


# 차트에 올렸을 때 보이는 날짜 : 연도도 같이 표시
# 기간이 너무 긴 차트는 최대 1년으로 줄이기
# 각 데이터 별 최신 날짜 적기
# 마지막에 이 사이트가 언제 업데이트 되었는지 보여주기
# 구리, 비트코인 추가

# 1. API 설정 (보안을 위해 실제 배포시에는 변수 처리 권장)
FRED_API_KEY = os.getenv("FRED_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# 키가 잘 불러와졌는지 확인하는 안전장치
if not FRED_API_KEY or not GEMINI_API_KEY:
    print("오류: API 키를 찾을 수 없습니다. 환경 변수 설정을 확인하세요.")

fred = Fred(api_key=FRED_API_KEY)
client = genai.Client(api_key=GEMINI_API_KEY)


# 2. 데이터 수집 함수
def get_market_data():
    # 1. FRED에서 가져올 지표들 (ID: 이름)
    fred_map = {
        "DGS10": "미국채 10년",
        "DGS2": "미국채 2년",
        # "DGS3MO": "T-Bill (3M)",
        # "DGS30": "T-Bond (30Y)",
        "T10Y2Y": "장단기(10년-2년)금리차",
        "FEDFUNDS": "미 기준금리",
        "SOFR": "SOFR",
        "WALCL": "Fed 자산",
        "RRPONTSYD": "RRP (역레포)",
        "WTREGEN": "TGA 잔고",
        "M2SL": "M2 통화량",
        "TOTRESNS": "지급준비금",
        "WMMFNS": "MMF 잔액",
        "BAMLH0A0HYM2": "하이일드 스프레드"
    }

    # 2. Yahoo Finance에서 가져올 지표들 (Ticker: 이름)
    yf_map = {
        "^GSPC": "S&P 500",
        "^IXIC": "나스닥",
        "DX-Y.NYB": "달러인덱스",
        "KRW=X": "원/달러 환율",
        "^VIX": "공포지수 (VIX)",
        "GC=F": "금 값",
        "SI=F": "은 값",
        "CL=F": "WTI유",
        "BTC-USD": "비트코인",  # 비트코인 추가
        "HG=F": "구리"       # 구리 추가
    }

    all_data = {}

    # FRED 데이터 수집
    for code, name in fred_map.items():
        try:
            df = fred.get_series(code).dropna() # 결측치 제거
            if len(df) < 2: continue
            
            latest_val = df.iloc[-1]
            prev_val = df.iloc[-2]
            
            # 등락률 계산
            if code in ['DGS10','DGS2','T10Y2Y','FEDFUNDS']:
                change_rate = (latest_val - prev_val) * 100
            else:
                change_rate = ((latest_val - prev_val) / prev_val) * 100
            color = "#ff4d4d" if change_rate > 0 else "#4d79ff" if change_rate < 0 else "#888888"
            sign = "▲" if change_rate > 0 else "▼" if change_rate < 0 else "-"

            if code in ['DGS10','DGS2','T10Y2Y','FEDFUNDS']:
                change_rate = f"{sign} {abs(change_rate):.2f}bp"
            else:
                change_rate = f"{sign} {abs(change_rate):.2f}%"

            # 몇 개월치씩 보여줄건지
            dateCnt = 90
            if code == "FEDFUNDS":
                dateCnt = 6
            elif code == "WALCL" or code == "WTREGEN":
                dateCnt = 48
            elif code == "M2SL"  or code == "TOTRESNS":
                dateCnt = 12

            all_data[name] = {
                "date": df.tail(dateCnt).index.strftime('%Y-%m-%d').tolist(),
                "value": df.tail(dateCnt).round(2).tolist(),
                "latest": round(latest_val, 2),
                "change_rate": change_rate,
                "change_color": color,
                "data_date": df.index[-1].strftime('%Y-%m-%d')
            }
        except: continue

    # Yahoo 데이터 수집
    for ticker, name in yf_map.items():
        try:
            df = yf.Ticker(ticker).history(period="95d") # 등락률 계산 위해 조금 더 넉넉히 가져옴
            if len(df) < 2: continue
            
            latest_val = df['Close'].iloc[-1]
            prev_val = df['Close'].iloc[-2]
            
            # 등락률 계산
            change_rate = ((latest_val - prev_val) / prev_val) * 100
            color = "#ff4d4d" if change_rate > 0 else "#4d79ff" if change_rate < 0 else "#888888"
            sign = "▲" if change_rate > 0 else "▼" if change_rate < 0 else "-"

            # 몇 개월치씩 보여줄건지
            dateCnt = 90
            if code == "FEDFUNDS":
                dateCnt = 6
            elif code == "WALCL" or code == "WTREGEN":
                dateCnt = 48
            elif code == "M2SL"  or code == "TOTRESNS":
                dateCnt = 12

            all_data[name] = {
                "date": df.index.strftime('%Y-%m-%d').tolist()[-dateCnt:], # 마지막 90일만
                "value": df['Close'].round(2).tolist()[-dateCnt:],
                "latest": round(latest_val, 2),
                "change_rate": f"{sign} {abs(change_rate):.2f}%",
                "change_color": color,
                "data_date": df.index[-1].strftime('%Y-%m-%d')
            }
        except: continue

    return all_data


# 3. Gemini AI 분석 요청
def get_ai_analysis(market_data):

    prompt = f"""
    너는 경제 전문가 Moo야. 다음 지표를 보고 현재 시장 상황을 분석해줘: {market_data}
    먼저 간단하게 한 줄로 시장 상황을 표현해줘. 그리고 현재 시장에 영향을 줄 만한 주요 뉴스를 2-3줄 정도로 알려줘.
    1. 유동성의 3대 측면에서(연준,재무부,시장) 현재 시장 분석
    2. 미래의 시장 흐름 예측
    3. 투자 시 유의사항 (2줄)    
    한글로 쉽고 친절하게 설명해줘.
    """
    
    try:
        response = client.models.generate_content(
            model='models/gemini-2.5-flash',
            contents=prompt
        )
        # print(response.text)
        return response.text
    except Exception as e:
        return f"AI 분석 중 오류가 발생했습니다: {e}"


def get_fng_data():
    try:
        fng = fear_and_greed.get()
        value = fng.value
        description = fng.description # 'Extreme Fear', 'Fear', 'Neutral', 'Greed', 'Extreme Greed'
        return int(value), description
    except:
        return 50, "Neutral" # 실패 시 중간값


# 4. 메인 실행 부분
if __name__ == "__main__":
    # 데이터 가져오기
    all_data = get_market_data()

    # AI 분석 받기
    ai_insight = get_ai_analysis(all_data)
    ai_insight = ai_insight.replace("---", "\n").replace("###", "\n💡").replace("** ", "\n").replace("**", "\n").replace(" * ", "\n").replace("*", "").replace(". ",".\n")

    # fear and greed index
    fng_value, fng_desc = get_fng_data()

    # f-string 안에서 사용할 변수 처리
    fng_sections = ["Extreme Fear", "Fear", "Neutral", "Greed", "Extreme Greed"]
    fng_colors = ["#ff4d4d", "#ffad33", "#e6e6e6", "#99cc33", "#009900"] # 빨강, 주황, 회색, 연두, 초록

    fng_html = f"""
    <div class="fng-container" style="margin: 20px 0; padding: 20px; background: #fff; border-radius: 12px; border: 1px solid #eee;">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px;">
            <span style="font-weight: bold; font-size: 1.1rem;">공포 탐욕 지수</span>
            <span style="font-size: 1.5rem; font-weight: 900; color: #333;">{fng_value}</span>
        </div>
        
        <div class="fng-bar" style="display: flex; gap: 5px; height: 35px; width: 100%;">
    """

    for i, section in enumerate(fng_sections):
        # 현재 등급(fng_desc)과 일치하는 칸만 색칠, 나머지는 연한 회색
        is_active = section.lower() == fng_desc.lower()
        bg_color = fng_colors[i] if is_active else "#f2f2f2"
        text_color = "#fff" if is_active else "#ccc"
        font_weight = "900" if is_active else "normal"
        
        fng_html += f"""
            <div style="flex: 1; background: {bg_color}; display: flex; align-items: center; justify-content: center; 
                        font-size: 0.7rem; color: {text_color}; font-weight: {font_weight}; border-radius: 4px; transition: all 0.3s;">
                {section if is_active else ""}
            </div>
        """

    fng_html += """
        </div>
        <div style="display: flex; justify-content: space-between; margin-top: 8px; font-size: 0.7rem; color: #999;">
            <span>0 (Extreme Fear)</span>
            <span>100 (Extreme Greed)</span>
        </div>
    </div>
    """

    # HTML 생성용 변수들 만들기 (반복문 활용)
    sections_html = ""
    charts_js = ""

    # 지표 구성 정의 (순서 및 그룹화)
    metrics_config = [
        ("주요 지수", [("S&P 500", "SPY"), ("나스닥", "^IXIC")]),
        ("통화/환율", [("달러인덱스", "DX-Y.NYB"), ("원/달러 환율", "KRW=X")]),
        ("국채 금리", [("미국채 10년", "DGS10"), ("미국채 2년", "DGS2"), ("미 기준금리", "FEDFUNDS"), ("장단기(10년-2년)금리차", "T10Y2Y")]),
        ("유동성", [("SOFR", "SOFR"), ("Fed 자산", "WALCL"), ("RRP (역레포)", "RRPONTSYD"), ("TGA 잔고", "WTREGEN"), ("M2 통화량", "M2SL"), ("지급준비금", "TOTRESNS"), ("MMF 잔액", "WMMFNS")]),
        ("위험/심리", [("하이일드 스프레드", "BAMLH0A0HYM2"), ("공포지수 (VIX)", "^VIX")]),
        ("원자재", [("금 값", "GC=F"), ("은 값", "SI=F"), ("구리", "HG=F"), ("WTI유", "CL=F")]),
        ("기타", [("비트코인", "BTC-USD")])
    ]

    # 지표별 1줄 요약 설명
    metric_descriptions = {
        "S&P 500": "미국 대형주 500개의 흐름을 나타내는 대표 지수",
        "나스닥": "기술주와 성장주 중심의 시장 지수",
        "달러인덱스": "주요국 통화 대비 달러의 가치",
        "원/달러 환율": "한화 대비 달러 가치 (환율이 올랐다 = 한화 가치가 떨어졌다)",
        "미국채 10년": "글로벌 장기 금리의 기준점 (할인율의 기초)",
        "미국채 2년": "통화 정책 방향에 민감하게 반응하는 단기 금리",
        "미 기준금리": "연준(Fed)의 정책 금리 결정치",
        "장단기(10년-2년)금리차": "🔴마이너스 시 경기 침체 전조<br>🔴역전(-)되었다가 급하게 정상화될 때 침체 예상",
        "SOFR": "금융기관 간 초단기 금리 (실질 자금 경색 확인)",
        "Fed 자산": "연준의 자산 규모 (양적 완화/긴축의 척도)",
        "RRP (역레포)": "연준의 저금통에 맡긴 단기 자금 (시장 입장에선 자고 있는 돈)<br>◾ RRP가 줄어들었다 = 잠재적 유동성이 깨어났다<br>◾ RRP가 바닥이다 = 시장에 풀릴 돈이 없다",
        "TGA 잔고": "미 재무부의 현금 잔고 (세금이 들어오고 정부의 지출이 있는 곳)<br>이 돈이 시장으로 나왔다가 들어갔다가 하는 것<br>◾ 수치가 감소했다 = 돈이 시장에 풀렸다(유동성 증가)",
        "M2 통화량": "시중에 풀린 전체 돈의 양",
        "지급준비금": "은행이 연준에 예치한 자금 (유동성 최후 보루)",
        "MMF 잔액": "시중의 대기성 자금 규모",
        "하이일드 스프레드": "🔴상승하면 기업들의 부도 위험 증가",
        "공포지수 (VIX)": "😨 높을수록 시장이 불안하다는 뜻",
        "금 값": "대표적인 안전 자산이자 인플레이션 헤지 수단",
        "은 값": "산업용 수요와 안전 자산 성격이 혼재된 금속",
        "WTI유": "물가에 영향을 주는 에너지 가격<br>🔴100 넘으면 인플레이션 경고등",
        "비트코인": "◾ 구리랑 함께 상승 시 실물 경기 회복 + 위험자산 선호<br>◾ 구리 그대로, 비트코인만 오르면 유동성 장세",
        "구리": "닥터 코퍼(Dr. Copper)/ 실물 경기 회복과 인프라 수요의 척도"
        # "T-Bill (3M)": "초단기 안전 자산 금리",
        # "T-Bond (30Y)": "초장기 기대 인플레이션과 경제 성장을 반영"
    }

    for group_name, items in metrics_config:
        sections_html += f'<div class="section"><h2>{group_name}</h2><div class="data-grid">'
        for name, code in items:
            if name in all_data:
                # 설명 문구 가져오기 (없으면 공백)
                desc = metric_descriptions.get(name, "")
                
                latest_val = all_data[name]["latest"]
                dates_json = json.dumps(all_data[name]["date"])
                values_json = json.dumps(all_data[name]["value"])
                canvas_id = f"chart_{name.replace(' ', '_').replace('/', '_')}"
                
                sections_html += f"""
                <div class="card">
                    <div class="card-header">
                        <div class="title-group">
                            <span class="metric-name">{name}</span>
                            <div class="metric-desc">{desc}</div>
                        </div>
                        <div class="value-group" style="text-align: right;">
                            <div class="metric-value">{latest_val:,.2f}</div>
                            <div class="metric-change" style="color: {all_data[name]['change_color']}; font-size: 0.85rem; font-weight: bold;">
                                {all_data[name]['change_rate']}
                            </div>
                        </div>
                    </div>
                    <div class="chart-container">
                        <canvas id="{canvas_id}"></canvas>
                    </div>
                    <div style="font-size: 0.65rem; color: #bbb; text-align: right; margin-top: 5px;">
                        날짜: {all_data[name]['data_date']}
                    </div>
                </div>
                """
                
                # JS 코드 생성 (중괄호 이스케이프 주의)
                charts_js += f"""
                new Chart(document.getElementById('{canvas_id}'), {{
                    type: 'line',
                    data: {{
                        labels: {dates_json},
                        datasets: [{{
                            label: '{name}',
                            data: {values_json},
                            borderColor: '#3e95cd',
                            borderWidth: 2.5,     /* 선 두께를 살짝 두껍게 */
                            pointRadius: 0,       /* 평소엔 점을 숨김 */
                            pointHoverRadius: 5,  /* 마우스 올렸을 때만 점 표시 */
                            fill: true,           /* 선 아래 색상 채우기 */
                            backgroundColor: 'rgba(62, 149, 205, 0.05)',
                            tension: 0.15
                        }}]
                    }},
                    options: {{
                        responsive: true,
                        maintainAspectRatio: false,
                        interaction: {{
                            mode: 'index',
                            intersect: false,
                        }},
                        plugins: {{ 
                            tooltip: {{
                                callbacks: {{
                                    title: function(context) {{
                                        return context[0].label; // 여기서 전체 날짜(YYYY-MM-DD)가 표시됩니다.
                                    }}
                                }}
                            }},
                            legend: {{ display: false }} 
                        }},
                        scales: {{ 
                            x: {{ 
                                display: true,   /* 차트가 커졌으므로 X축 날짜도 표시 */
                                ticks: {{ 
                                    maxRotation: 0, 
                                    autoSkip: true, 
                                    maxTicksLimit: 8, /* 날짜가 겹치지 않게 8개 내외로 표시 */
                                    font: {{ size: 10 }} 
                                }},
                                grid: {{ display: false }}
                            }}, 
                            y: {{ 
                                display: true,
                                ticks: {{ font: {{ size: 11 }} }},
                                grid: {{ color: '#f0f0f0' }}
                            }} 
                        }}
                    }}
                }});
                """
        sections_html += '</div></div>'

    # 1. 한국 표준시(KST) 시간대 정의
    KST = timezone(timedelta(hours=9))

    # 2. 서버 시간이 아닌 한국 시간 기준으로 현재 날짜 가져오기
    current_time_kst = datetime.datetime.now(KST)
    today_date = current_time_kst.strftime('%Y-%m-%d')
    update_time = current_time_kst.strftime('%H:%M:%S')

    html_template = f"""
    <html>
    <head>
        <meta charset="UTF-8">
        <title>미국 유동성 지표</title>
        <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
        <style>
            body {{ font-family: 'Malgun Gothic', sans-serif; background: #f0f2f5; color: #333; padding: 20px; }}
            .container {{ max-width: 1200px; margin: auto; }}
            .section {{ margin-bottom: 40px; }}
            .section h2 {{ 
                border-left: 6px solid #3e95cd; 
                padding-left: 15px; 
                margin: 40px 0 20px 0; 
                font-size: 1.6rem; 
                color: #2c3e50;
            }}
            .data-grid {{ 
                display: grid; 
                /* 1fr 1fr로 설정하여 가로를 정확히 반반씩 나누되, 화면이 작아지면 1줄로 바뀝니다 */
                grid-template-columns: repeat(auto-fit, minmax(450px, 1fr)); 
                gap: 25px; 
                margin-top: 20px;
            }}
            .card {{ 
                background: white; border-radius: 12px; padding: 20px; 
                box-shadow: 0 2px 8px rgba(0,0,0,0.05); display: flex; flex-direction: column;
            }}
            .card:hover {{
                transform: translateY(-5px); /* 마우스를 올리면 살짝 들리는 효과 */
            }}
            .card-header {{ 
                display: flex; 
                justify-content: space-between; 
                align-items: flex-start; /* 위쪽 정렬로 변경 */
                margin-bottom: 10px; 
            }}
            .title-group {{ display: flex; flex-direction: column; }} /* 이름과 설명을 세로로 */
            .metric-name {{ font-weight: bold; color: #333; font-size: 1rem; }}
            .metric-desc {{ 
                font-size: 0.75rem; 
                color: #888; 
                margin-top: 2px; 
                letter-spacing: -0.5px; 
            }}
            .metric-value {{ font-size: 1.3rem; font-weight: 800; color: #2c3e50;line-height: 1.1; }}
            .chart-container {{ height: 280px; position: relative; margin-top: 10px; }}
            .ai-box {{ 
                background: #ffffff; padding: 25px; border-radius: 15px; 
                border: 2px solid #3e95cd; margin-top: 30px; line-height: 1.8;
            }}
            .value-group {{
                display: flex;
                flex-direction: column;
                align-items: flex-end;
            }}
            .metric-change {{
                margin-top: 4px;
                letter-spacing: -0.5px;
            }}

        </style>
    </head>
    <body>
        <div class="container">
            <h1>👀 오늘의 미국 시장 지표 <small style="font-size: 0.5em; color: #888;">{today_date + " " + update_time + "업데이트됨"} 📌데이터는 전 날 종가 기준</small></h1>
            {fng_html}
            {sections_html}

            <div class="ai-box">
                <h2 style="margin-top:0; color:#3e95cd;">🤖 Gemini AI 시장 분석</h2>
                <p>{ai_insight.replace('\\n', '<br>')}</p>
            </div>
        </div>

        <script>
            {charts_js}
        </script>
    </body>
    </html>
    """

    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html_template)
