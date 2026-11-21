import streamlit as st
import json
import os
import random
import base64
import time
import re
import concurrent.futures
from PIL import Image
import io
from google import genai
from google.genai import types
from streamlit_option_menu import option_menu

# ページ全体の初期設定
st.set_page_config(page_title="英単語マスター", page_icon="📘", layout="wide")

# --- カスタムCSS ---
st.markdown("""
<style>
    .stApp { background-color: #f8fafc; color: #1e293b; }
    .header-box { background: #ffffff; padding: 1.2rem 1.5rem; border-radius: 14px; border: 1px solid #e2e8f0; box-shadow: 0 2px 6px rgba(15, 23, 42, 0.04); display: flex; justify-content: space-between; align-items: center; margin-bottom: 1rem; }
    .header-title { font-size: 1.5rem; font-weight: 700; color: #0f172a; margin: 0; }
    .count-badge { background: #eef2ff; color: #4f46e5; font-weight: 700; padding: 0.35rem 0.9rem; border-radius: 999px; font-size: 0.95rem; border: 1px solid #c7d2fe; }
    
    .flip-container { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 15px; margin-top: 10px; }
    .flip-card { background-color: transparent; height: 180px; perspective: 1000px; cursor: pointer; }
    .flip-card-inner { position: relative; width: 100%; height: 100%; text-align: center; transition: transform 0.4s ease-in-out; transform-style: preserve-3d; }
    .flip-card-front, .flip-card-back { position: absolute; width: 100%; height: 100%; backface-visibility: hidden; border-radius: 12px; display: flex; flex-direction: column; justify-content: center; padding: 15px; box-shadow: 0 4px 10px rgba(15, 23, 42, 0.05); }
    .flip-card-front { background-color: #ffffff; color: #0f172a; font-size: 1.6rem; font-weight: 700; border: 2px solid #e2e8f0; align-items: center; }
    .flip-card-back { background-color: #ffffff; color: #1e293b; transform: rotateY(180deg); border: 2px solid #6366f1; align-items: flex-start; text-align: left; }
    
    .quiz-card { background: #ffffff; border: 1px solid #e2e8f0; border-radius: 16px; padding: 1.8rem; box-shadow: 0 4px 12px rgba(15, 23, 42, 0.05); margin: 1rem 0 1.2rem 0; }
    .quiz-hint-text { margin-top: 0.9rem; padding-top: 0.8rem; border-top: 1px dashed #cbd5e1; color: #475569; font-size: 1rem; }
    .quiz-question-text { font-size: 1.35rem; font-weight: 700; color: #0f172a; line-height: 1.6; }
</style>
""", unsafe_allow_html=True)

# --- 画像の強力な軽量化 ---
def compress_image_for_ai(img_bytes):
    try:
        image = Image.open(io.BytesIO(img_bytes)).convert("RGB")
        image.thumbnail((1200, 1200)) # 画像サイズを縮小してAPI制限を回避
        output = io.BytesIO()
        image.save(output, format="JPEG", quality=70)
        return output.getvalue()
    except Exception:
        return img_bytes

# --- データ保存・読み込み処理 ---
def get_user_file_path(email):
    return f"user_data_{email.replace('@', '_at_').replace('.', '_')}.json"

def load_user_data(email):
    filepath = get_user_file_path(email)
    if os.path.exists(filepath):
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"api_key": "", "files": {}, "wrong_words": []}

def save_user_data(email):
    data = {"api_key": st.session_state.api_key, "files": st.session_state.files, "wrong_words": st.session_state.wrong_words}
    with open(get_user_file_path(email), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# --- OCR処理 ---
def process_image_with_ocr(image_bytes, api_key):
    client = genai.Client(api_key=api_key.strip())
    prompt = """
    この画像は英単語帳のページです。画像に含まれるすべての英単語と日本語訳を抽出し、以下のルールでJSON配列として出力してください。
1. 画像内に例文がある場合は、その例文を抽出して "example" に入れてください。
2. 画像内に例文がない場合は、その英単語を使った自然な例文を新しく作成して "example" に入れてください。
3. 例文内の英単語部分は [ ______ ] のように穴埋め形式にしてください。
    出力形式: [{"word": "英単語", "meaning": "日本語訳", "example": "例文"}]
    他の説明文やMarkdownの装飾は一切含めないでください。
    """
    try:
        response = client.models.generate_content(
            model="gemini-1.5-flash",  # ここを正しいモデル名に修正しました！
            contents=[types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"), prompt]
        )
        res_text = response.text.strip()
        if "```json" in res_text: res_text = res_text.split("```json")[1].split("```")[0].strip()
        elif "```" in res_text: res_text = res_text.split("```")[1].split("```")[0].strip()
        data = json.loads(res_text)
        result_list = list(data.values())[0] if isinstance(data, dict) else data
        return result_list, None
    except Exception as e:
        return None, str(e)

def process_single_image_task(img_bytes, api_key):
    jpeg_bytes = compress_image_for_ai(img_bytes)
    b64 = base64.b64encode(jpeg_bytes).decode('utf-8')
    parsed, error = process_image_with_ocr(jpeg_bytes, api_key)
    return b64, parsed, error

# --- セッション状態の初期化 ---
if "user_email" not in st.session_state: st.session_state.user_email = None
if "api_key" not in st.session_state: st.session_state.api_key = ""
if "test_state" not in st.session_state: st.session_state.test_state = None
if "selected_folders" not in st.session_state: st.session_state.selected_folders = None

# --- 1. ログイン画面 ---
if not st.session_state.user_email:
    st.title("📘 英単語マスター - ログイン")
    st.write("ブラウザのパスワード保存機能（Face IDや指紋認証）が使えます。")
    
    with st.form("login_form"):
        email_input = st.text_input("メールアドレス", autocomplete="email")
        api_key_input = st.text_input("Gemini API Key", type="password", autocomplete="current-password")
        submitted = st.form_submit_button("ログイン", type="primary", use_container_width=True)
        
        if submitted:
            if email_input and api_key_input:
                st.session_state.user_email = email_input
                st.session_state.api_key = api_key_input
                loaded_data = load_user_data(email_input)
                st.session_state.files = loaded_data.get("files", {})
                st.session_state.wrong_words = loaded_data.get("wrong_words", [])
                save_user_data(email_input)
                st.rerun()
            else:
                st.warning("両方入力してください。")
    st.stop()

# --- 2. サイドバー ---
with st.sidebar:
    st.caption(f"👤 {st.session_state.user_email}")
    page = option_menu(
        menu_title=None, 
        options=["📖 学習カード", "✍️ 単語テスト", "⚠️ 復習リスト"], 
        icons=["book", "pencil", "exclamation-triangle"],
        default_index=0,
        styles={"container": {"padding": "0!important"}, "nav-link": {"font-size": "15px", "text-align": "left", "margin": "5px"}}
    )
    st.write("---")
    if st.button("ログアウト", use_container_width=True):
        st.session_state.user_email = None
        st.rerun()

# ---------------------------------------------------------
# ページ1: 学習カード
# ---------------------------------------------------------
if page == "📖 学習カード":
    file_list = list(st.session_state.files.keys())
    
    with st.expander("📷 写真から単語を追加", expanded=(len(file_list) == 0)):
        uploaded_files = st.file_uploader("単語帳の写真", type=["png", "jpg", "jpeg", "heic"], accept_multiple_files=True)
        file_name = st.text_input("保存するフォルダ名")
        
        if st.button("スキャン実行", type="primary"):
            if uploaded_files and file_name:
                all_parsed_words = []
                b64_images = []
                error_messages = []
                
                with st.spinner("AIが画像を解析中...（数十秒かかる場合があります）"):
                    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                        futures = [executor.submit(process_single_image_task, f.getvalue(), st.session_state.api_key) for f in uploaded_files]
                        for future in concurrent.futures.as_completed(futures):
                            b64_img, parsed, err = future.result()
                            if b64_img: b64_images.append(b64_img)
                            if parsed: all_parsed_words.extend(parsed)
                            if err: error_messages.append(err)
                
                if all_parsed_words:
                    st.session_state.files[file_name] = {"images": b64_images,