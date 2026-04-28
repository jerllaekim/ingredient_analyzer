import streamlit as st
import requests
import json
import pdfplumber
import os
import re
import pandas as pd

# 앱 설정
st.set_page_config(page_title="Food Product & Law Helper", layout="wide")
st.title("🍱 식품 정보 및 규정 검색기")
API_KEY = st.secrets.get("GEMINI_API_KEY")

# 1. 엑셀 데이터 로드 (폴더명 data2 반영)
@st.cache_data
def load_excel_info():
    # 폴더명 수정: data2
    file_path = "data2/product_list.xlsx"
    if os.path.exists(file_path):
        try:
            df = pd.read_excel(file_path)
            return df
        except Exception as e:
            st.error(f"엑셀 로드 에러: {e}")
            return None
    return None

# 2. PDF 데이터 로드 (폴더명 data2 반영)
@st.cache_resource
def load_pdf_pages():
    # 폴더명 수정: data2
    data_dir = "data2"
    pdf_pages = []
    if not os.path.exists(data_dir):
        return []
    
    files = [f for f in os.listdir(data_dir) if f.endswith('.pdf')]
    for file in files:
        try:
            with pdfplumber.open(os.path.join(data_dir, file)) as pdf:
                for i, page in enumerate(pdf.pages):
                    text = page.extract_text()
                    if text:
                        pdf_pages.append({"source": file, "page": i+1, "content": text})
        except:
            continue
    return pdf_pages

# 데이터 로드 실행
df_product = load_excel_info()
all_pdf_data = load_pdf_pages()

# 3. Gemini 모델 설정 (기존 로직 유지)
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

# 채팅 UI
if "messages" not in st.session_state:
    st.session_state.messages = []

for m in st.session_state.messages:
    with st.chat_message(m["role"]):
        st.markdown(m["content"])

if prompt := st.chat_input("검색할 제품명을 입력하세요 (예: 비타민C)"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        excel_context = ""
        keywords_for_pdf = [prompt]
        
        # STEP A: 엑셀 검색 (C열 기준)
        if df_product is not None:
            match = df_product[df_product.iloc[:, 2].astype(str).str.contains(prompt, na=False, case=False)]
            
            if not match.empty:
                row = match.iloc[0]
                food_type = str(row.iloc[0])   # A열: 식품유형
                product_name = str(row.iloc[2]) # C열: 제품명
                remarks = str(row.iloc[4])      # E열: 비고
                
                excel_context = f"제품명: {product_name}, 식품유형: {food_type}, 비고: {remarks}"
                keywords_for_pdf.extend([food_type, remarks])
                st.sidebar.success(f"매칭됨: {product_name}")
            else:
                excel_context = f"제품명 '{prompt}'을(를) 엑셀에서 찾을 수 없습니다."

        # STEP B: PDF 검색 (data2 내 파일들)
        pdf_context = ""
        scored_pages = []
        for p in all_pdf_data:
            score = sum(2 if str(kw).lower() in p['content'].lower() else 0 for kw in keywords_for_pdf if len(str(kw)) > 1)
            if score > 0:
                scored_pages.append((score, p))
        
        scored_pages.sort(key=lambda x: x[0], reverse=True)
        for _, res in scored_pages[:10]:
            pdf_context += f"\n[문서: {res['source']}, 페이지: {res['page']}]\n{res['content']}\n"

        # STEP C: Gemini 응답 생성
        payload = {
            "contents": [{
                "parts": [{
                    "text": f"""식품 정보 전문가로서 답하세요.
                    
                    [사용자 검색어]: {prompt}
                    [엑셀 기초 데이터]: {excel_context}
                    [PDF 참조 내용]: {pdf_context}

                    작성 지침:
                    1. 엑셀에 있는 식품유형과 비고 내용을 먼저 설명하세요.
                    2. 식품유형과 비고에 따른 실험 규격을 설명해주세요
                    3. 한국어로 정중하게 답변하고 마지막에 출처를 표시하세요. [출처: 파일명, Page X]
                    """
                }]
            }]
        }

        try:
            with st.spinner("data2 폴더의 데이터를 분석 중..."):
                response = requests.post(API_URL, headers={'Content-Type': 'application/json'}, data=json.dumps(payload))
                result = response.json()
                
                if response.status_code == 200:
                    answer = result['candidates'][0]['content']['parts'][0]['text']
                    st.markdown(answer)
                    st.session_state.messages.append({"role": "assistant", "content": answer})
                else:
                    st.error("API 호출 중 문제가 발생했습니다.")
        except Exception as e:
            st.error(f"오류 발생: {e}")
