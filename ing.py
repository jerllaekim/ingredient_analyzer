import streamlit as st
import requests
import json
import pdfplumber
import os
import re
import pandas as pd

st.set_page_config(page_title="Food Info Helper", layout="wide")
st.title("🍱 식품 정보 통합 검색 도우미")
st.info("제품명을 입력하면 엑셀 데이터와 PDF 지침서를 대조하여 결과를 반환합니다.")

API_KEY = st.secrets.get("GEMINI_API_KEY")

# 1. 엑셀 데이터 로드 (C열: 제품명, A열: 식품유형, E열: 비고)
@st.cache_data
def load_excel_data():
    file_path = "data/product_list.xlsx" # 엑셀 파일 경로
    if os.path.exists(file_path):
        df = pd.read_excel(file_path)
        # 열 인덱스로 접근하거나 이름을 맞추세요 (A=0, C=2, E=4)
        return df
    return None

# 2. PDF 데이터 로드
@st.cache_resource
def load_pdf_data():
    data_dir = "data"
    pdf_pages = []
    if not os.path.exists(data_dir): return []
    
    files = [f for f in os.listdir(data_dir) if f.endswith('.pdf')]
    for file in files:
        try:
            with pdfplumber.open(os.path.join(data_dir, file)) as pdf:
                for i, page in enumerate(pdf.pages):
                    text = page.extract_text()
                    if text:
                        pdf_pages.append({"source": file, "page": i+1, "content": text})
        except: continue
    return pdf_pages

df_excel = load_excel_data()
all_pdf_pages = load_pdf_data()

# 3. 모델 설정 (기존 코드 유지)
@st.cache_resource
def get_working_model():
    list_url = f"https://generativelanguage.googleapis.com/v1beta/models?key={API_KEY}"
    try:
        res = requests.get(list_url)
        models_data = res.json()
        if 'models' in models_data:
            supported_models = [m['name'] for m in models_data['models'] if 'generateContent' in m['supportedGenerationMethods']]
            for target in ['models/gemini-1.5-flash', 'models/gemini-pro']:
                if target in supported_models: return target
            return supported_models[0] if supported_models else None
    except: return None
    return None

target_model_path = get_working_model()
API_URL = f"https://generativelanguage.googleapis.com/v1beta/{target_model_path}:generateContent?key={API_KEY}"

# --- 메인 로직 ---

if "messages" not in st.session_state: st.session_state.messages = []
for m in st.session_state.messages:
    with st.chat_message(m["role"]): st.markdown(m["content"])

if prompt := st.chat_input("검색할 제품명을 입력하세요 (예: 불닭볶음면)"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"): st.markdown(prompt)

    with st.chat_message("assistant"):
        # A. 엑셀에서 검색 (C열이 제품명이라고 가정)
        # columns: A(0), B(1), C(2), D(3), E(4)
        excel_info = ""
        search_keywords = [prompt]
        
        if df_excel is not None:
            # C열(제품명)에서 검색 (포함하는 단어 찾기)
            match = df_excel[df_excel.iloc[:, 2].str.contains(prompt, na=False, case=False)]
            
            if not match.empty:
                row = match.iloc[0]
                food_type = row.iloc[0]  # A열: 식품유형
                product_name = row.iloc[2] # C열: 제품명
                note = row.iloc[4] # E열: 비고
                
                excel_info = f"찾은 제품: {product_name}\n식품유형: {food_type}\n비고: {note}"
                search_keywords.extend([str(food_type), str(note)])
                st.sidebar.success(f"엑셀 매칭 완료: {product_name}")
            else:
                excel_info = "엑셀 파일에서 해당 제품을 찾을 수 없습니다."

        # B. PDF에서 관련 내용 검색 (엑셀에서 얻은 키워드 활용)
        context = ""
        scored_pages = []
        for p in all_pdf_pages:
            score = sum(3 if kw in p['content'] else 0 for kw in search_keywords if len(str(kw)) > 1)
            if score > 0:
                scored_pages.append((score, p))
        
        scored_pages.sort(key=lambda x: x[0], reverse=True)
        for _, res in scored_pages[:10]: # 상위 10페이지
            context += f"\n[문서: {res['source']}, 페이지: {res['page']}]\n{res['content']}\n"

        # C. Gemini API 호출
        payload = {
            "contents": [{
                "parts": [{
                    "text": f"""시스템: 당신은 식품 법규 및 가이드라인 전문가입니다.
                    제시된 [엑셀 정보]와 [PDF 컨텍스트]를 바탕으로 사용자의 질문에 답하세요.
                    
                    [엑셀 정보]
                    {excel_info}
                    
                    [PDF 컨텍스트]
                    {context}
                    
                    질문: {prompt}에 대한 식품유형, 비고 및 관련 규정 내용을 정리해줘.
                    
                    조건:
                    1. 반드시 한국어로 답변할 것.
                    2. PDF에 내용이 없다면 엑셀 정보 위주로 답변할 것.
                    3. 출처는 마지막에 [SOURCE: 파일명, 페이지] 형태로 적을 것.
                    """
                }]
            }]
        }

        try:
            with st.spinner("데이터 분석 중..."):
                response = requests.post(API_URL, headers={'Content-Type': 'application/json'}, data=json.dumps(payload))
                result = response.json()
                
                if response.status_code == 200:
                    answer = result['candidates'][0]['content']['parts'][0]['text']
                    st.markdown(answer)
                    st.session_state.messages.append({"role": "assistant", "content": answer})
                else:
                    st.error("API 응답 오류가 발생했습니다.")
        except Exception as e:
            st.error(f"에러 발생: {e}")