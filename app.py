import streamlit as st
import json
import os
import random
import base64
from PIL import Image
import io
import google.generativeai as genai

st.set_page_config(page_title="英単語帳スキャンアプリ", layout="wide")

# --- 画像を安全にJPEG形式に変換する関数 ---
def convert_to_jpeg(img_bytes):
    try:
        try:
            from pillow_heif import register_heif_opener
            register_heif_opener()
        except ImportError:
            pass
        
        image = Image.open(io.BytesIO(img_bytes))
        image = image.convert("RGB")
        output = io.BytesIO()
        image.save(output, format="JPEG")
        return output.getvalue()
    except Exception:
        return img_bytes

# --- データ保存・読み込み処理 ---
def get_user_file_path(email):
    safe_email = email.replace("@", "_at_").replace(".", "_")
    return f"user_data_{safe_email}.json"

def load_user_data(email):
    filepath = get_user_file_path(email)
    if os.path.exists(filepath):
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"api_key": "", "files": {}, "wrong_words": []}

def save_user_data(email):
    filepath = get_user_file_path(email)
    data = {
        "api_key": st.session_state.get("api_key", ""),
        "files": st.session_state.get("files", {}),
        "wrong_words": st.session_state.get("wrong_words", [])
    }
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# --- 画像からのOCR読み取り処理 (利用可能なモデルを自動取得) ---
def process_image_with_ocr(image_bytes, api_key):
    if not api_key:
        return None
    
    try:
        genai.configure(api_key=api_key)
        
        # 利用可能なモデル一覧を自動取得
        available_models = [
            m.name for m in genai.list_models() 
            if 'generateContent' in m.supported_generation_methods
        ]
        
        # flashモデルを優先的に探して自動選択
        target_model = None
        for m_name in available_models:
            if 'flash' in m_name.lower():
                target_model = m_name
                break
        
        if not target_model and available_models:
            target_model = available_models[0]
            
        if not target_model:
            target_model = 'gemini-1.5-flash'
            
        model = genai.GenerativeModel(target_model)
        image = Image.open(io.BytesIO(image_bytes))
        
        prompt = """
        この画像は英単語帳のページです。画像に含まれるすべての英単語、その日本語訳、および例文を抽出し、以下のJSON配列形式のみで出力してください。他の説明文やMarkdownの装飾は一切含めないでください。
        [
          {
            "word": "英単語",
            "meaning": "日本語訳",
            "example": "英文の例文（単語を含む）"
          }
        ]
        """
        
        response = model.generate_content([prompt, image])
        res_text = response.text.strip()
        
        if "```json" in res_text:
            res_text = res_text.split("```json")[1].split("```")[0].strip()
        elif "```" in res_text:
            res_text = res_text.split("```")[1].split("```")[0].strip()
            
        data = json.loads(res_text)
        if isinstance(data, dict):
            for val in data.values():
                if isinstance(val, list):
                    return val
        return data
    except Exception as e:
        st.error(f"Gemini OCR解析エラー: {e}")
        return None

# --- セッション状態の初期化 ---
if "user_email" not in st.session_state:
    st.session_state.user_email = None
if "api_key" not in st.session_state:
    st.session_state.api_key = ""
if "test_state" not in st.session_state:
    st.session_state.test_state = None

# --- 1. ログイン画面 ---
if not st.session_state.user_email:
    st.title("🔑 英単語学習アプリ - ログイン")
    
    email_input = st.text_input("メールアドレスを入力してください")
    
    saved_key = ""
    if email_input:
        existing_data = load_user_data(email_input)
        saved_key = existing_data.get("api_key", "")
    
    if saved_key:
        st.success("✅ 保存済みのAPIキーを検出しました。そのままログインできます。")
        api_key_input = st.text_input("API Key（変更する場合のみ入力）", value=saved_key, type="password")
    else:
        api_key_input = st.text_input("Gemini API Key（初回のみ入力・自動保存されます）", type="password")
    
    if st.button("ログイン", type="primary"):
        if email_input:
            st.session_state.user_email = email_input
            loaded_data = load_user_data(email_input)
            
            final_key = api_key_input.strip() if api_key_input.strip() else loaded_data.get("api_key", "")
            
            st.session_state.api_key = final_key
            st.session_state.files = loaded_data.get("files", {})
            st.session_state.wrong_words = loaded_data.get("wrong_words", [])
            
            save_user_data(email_input)
            st.rerun()
        else:
            st.warning("メールアドレスを入力してください。")
    st.stop()

# --- 2. メイン画面 ---
st.sidebar.title("メニュー")
st.sidebar.write(f"👤 **{st.session_state.user_email}**")
if st.sidebar.button("ログアウト"):
    st.session_state.user_email = None
    st.rerun()

page = st.sidebar.radio("ページ移動", ["学習", "テスト", "間違えた問題"])

# ---------------------------------------------------------
# ページ1: 学習
# ---------------------------------------------------------
if page == "学習":
    st.title("📖 単語学習")
    
    with st.expander("📷 新しいフォルダを作成（画像から単語登録）"):
        uploaded_files = st.file_uploader(
            "ファイルを選択を押して、写真を選んでください（複数枚選択可）", 
            type=["png", "jpg", "jpeg", "heic"], 
            accept_multiple_files=True
        )
        file_name = st.text_input("作成するフォルダ名を入力（例: Chapter1_名詞）")
        
        if st.button("スキャンしてフォルダに保存"):
            if uploaded_files and file_name:
                all_parsed_words = []
                b64_images = []
                
                with st.spinner(f"Gemini AIが{len(uploaded_files)}枚の画像を無料解析中..."):
                    for uploaded_file in uploaded_files:
                        raw_bytes = uploaded_file.read()
                        jpeg_bytes = convert_to_jpeg(raw_bytes)
                        b64_img = base64.b64encode(jpeg_bytes).decode('utf-8')
                        b64_images.append(b64_img)
                        
                        parsed = process_image_with_ocr(jpeg_bytes, st.session_state.api_key)
                        if parsed:
                            all_parsed_words.extend(parsed)
                
                if not all_parsed_words:
                    st.warning("OCR解析に失敗したため、サンプル単語を作成しました。")
                    all_parsed_words = [
                        {"word": "example", "meaning": "例", "example": "This is an example sentence."},
                        {"word": "study", "meaning": "勉強する", "example": "I study English every day."}
                    ]
                
                st.session_state.files[file_name] = {
                    "images": b64_images,
                    "words": all_parsed_words
                }
                save_user_data(st.session_state.user_email)
                st.success(f"フォルダ「{file_name}」を作成し、{len(uploaded_files)} 枚の写真を解析・保存しました！")
                st.rerun()
            else:
                st.warning("写真（1枚以上）とフォルダ名の両方を指定してください。")

    file_list = list(st.session_state.files.keys())
    if file_list:
        with st.expander("🗑️ フォルダの削除・整理"):
            target_del = st.selectbox("削除したいフォルダを選択", file_list)
            if st.button(f"「{target_del}」を削除する", type="primary"):
                del st.session_state.files[target_del]
                save_user_data(st.session_state.user_email)
                st.success(f"フォルダ「{target_del}」を削除しました。")
                st.rerun()

    st.write("---")
    
    if not file_list:
        st.info("まだ保存されたフォルダがありません。上のメニューから作成してください。")
    else:
        selected_files = st.multiselect("学習するフォルダを選択（複数可）", file_list, default=file_list)
        
        with st.expander("📥 選択したフォルダの写真を表示・ダウンロード"):
            for f_name in selected_files:
                f_data = st.session_state.files[f_name]
                st.write(f"📁 **フォルダ名: {f_name}**")
                
                images = f_data.get("images", [])
                if not images and "image" in f_data:
                    images = [f_data["image"]]
                
                cols = st.columns(min(len(images), 3) if images else 1)
                for idx, b64_img in enumerate(images):
                    img_data = base64.b64decode(b64_img)
                    with cols[idx % 3]:
                        try:
                            st.image(img_data, caption=f"ページ {idx + 1}", use_container_width=True)
                        except Exception:
                            st.caption(f"ページ {idx + 1} (画像表示非対応)")
                        
                        st.download_button(
                            label=f"ページ {idx + 1} をダウンロード",
                            data=img_data,
                            file_name=f"{f_name}_p{idx + 1}.jpg",
                            mime="image/jpeg",
                            key=f"dl_{f_name}_{idx}"
                        )

        st.subheader("🂠 単語カード")
        all_cards = []
        for f_name in selected_files:
            for item in st.session_state.files[f_name].get("words", []):
                all_cards.append(item)
                
        for idx, item in enumerate(all_cards):
            card_key = f"card_state_{idx}_{item['word']}"
            if card_key not in st.session_state:
                st.session_state[card_key] = False
            
            if not st.session_state[card_key]:
                if st.button(f"🇬🇧  {item['word']}  (タップで裏返す)", key=f"btn_{card_key}", use_container_width=True):
                    st.session_state[card_key] = True
                    st.rerun()
            else:
                with st.container():
                    st.markdown(f"### 🇯🇵 **{item['meaning']}**")
                    st.write(f"📝 **例文:** {item.get('example', '')}")
                    if st.button("↩️ 表に戻す", key=f"btn_back_{card_key}"):
                        st.session_state[card_key] = False
                        st.rerun()
            st.write("")

# ---------------------------------------------------------
# ページ2: テスト
# ---------------------------------------------------------
elif page == "テスト":
    st.title("✍️ テスト")
    
    file_list = list(st.session_state.files.keys())
    if not file_list:
        st.warning("フォルダが登録されていません。学習ページで追加してください。")
        st.stop()
        
    if st.session_state.test_state is None:
        selected_files = st.multiselect("テスト範囲（フォルダ）を選択", file_list, default=file_list)
        num_questions = st.selectbox("問題数", [5, 10, 15])
        test_type = st.radio("解答形式", ["記述式", "選択式 (4択)"])
        
        if st.button("テストを開始する"):
            questions = []
            for f_name in selected_files:
                for item in st.session_state.files[f_name].get("words", []):
                    if item.get("example") and item["word"].lower() in item.get("example", "").lower():
                        questions.append(item)
            
            if not questions:
                st.error("テストを作成できる例文付きの単語が見つかりませんでした。")
            else:
                random.shuffle(questions)
                selected_q = questions[:min(num_questions, len(questions))]
                st.session_state.test_state = {
                    "questions": selected_q,
                    "current_index": 0,
                    "test_type": test_type,
                    "answered": False,
                    "user_choice": None,
                    "is_correct": False,
                    "options": []
                }
                st.rerun()

    else:
        ts = st.session_state.test_state
        q_idx = ts["current_index"]
        questions = ts["questions"]
        
        if q_idx >= len(questions):
            st.success("🎉 テスト終了です！お疲れ様でした。")
            if st.button("はじめから選択する"):
                st.session_state.test_state = None
                st.rerun()
            st.stop()
            
        current_q = questions[q_idx]
        word = current_q["word"]
        meaning = current_q["meaning"]
        example = current_q["example"]
        
        blank_example = example.replace(word, "_______").replace(word.capitalize(), "_______")
        
        st.markdown(f"### 問題 {q_idx + 1} / {len(questions)}")
        st.info(f"📝 穴埋め英文:\n\n**{blank_example}**\n\n(意味: {meaning})")
        
        if st.button("やめる"):
            st.session_state.test_state = None
            st.rerun()
            
        st.write("---")
        
        if "記述式" in ts["test_type"]:
            user_input = st.text_input("英単語を入力してください", key=f"q_input_{q_idx}")
            
            if not ts["answered"]:
                if st.button("回答する"):
                    ts["answered"] = True
                    if user_input.strip().lower() == word.lower():
                        ts["is_correct"] = True
                    else:
                        ts["is_correct"] = False
                        if current_q not in st.session_state.wrong_words:
                            st.session_state.wrong_words.append(current_q)
                            save_user_data(st.session_state.user_email)
                    st.rerun()
            else:
                if ts["is_correct"]:
                    st.success(f"⭕ 正解！ ({word})")
                else:
                    st.error(f"❌ 不正解... 正解は: **{word}**")
                
                if st.button("次へ"):
                    ts["current_index"] += 1
                    ts["answered"] = False
                    st.rerun()

        else:
            if not ts["options"]:
                all_words = [item["word"] for f_name in st.session_state.files for item in st.session_state.files[f_name].get("words", [])]
                dummy_choices = list(set([w for w in all_words if w.lower() != word.lower()]))
                random.shuffle(dummy_choices)
                choices = dummy_choices[:3] + [word]
                random.shuffle(choices)
                ts["options"] = choices
            
            if not ts["answered"]:
                user_choice = st.radio("選択肢を選んでください", ts["options"], key=f"radio_{q_idx}")
                if st.button("回答する"):
                    ts["answered"] = True
                    ts["user_choice"] = user_choice
                    if user_choice == word:
                        ts["is_correct"] = True
                    else:
                        ts["is_correct"] = False
                        if current_q not in st.session_state.wrong_words:
                            st.session_state.wrong_words.append(current_q)
                            save_user_data(st.session_state.user_email)
                    st.rerun()
            else:
                for opt in ts["options"]:
                    if opt == word:
                        st.markdown(f"🟢 **{opt} (正解)**")
                    elif opt == ts["user_choice"] and not ts["is_correct"]:
                        st.markdown(f"🔴 ~~{opt}~~ (あなたの回答)")
                    else:
                        st.write(opt)
                
                if st.button("次へ"):
                    ts["current_index"] += 1
                    ts["answered"] = False
                    ts["options"] = []
                    st.rerun()

# ---------------------------------------------------------
# ページ3: 間違えた問題
# ---------------------------------------------------------
elif page == "間違えた問題":
    st.title("⚠️ 間違えた問題")
    
    if not st.session_state.wrong_words:
        st.success("現在、間違えた問題はありません！")
    else:
        if st.button("間違えたリストをクリア"):
            st.session_state.wrong_words = []
            save_user_data(st.session_state.user_email)
            st.rerun()
            
        st.write("---")
        for idx, item in enumerate(st.session_state.wrong_words):
            card_key = f"wrong_card_{idx}_{item['word']}"
            if card_key not in st.session_state:
                st.session_state[card_key] = False
                
            if not st.session_state[card_key]:
                if st.button(f"🇬🇧 {item['word']} (タップで裏返す)", key=f"btn_{card_key}", use_container_width=True):
                    st.session_state[card_key] = True
                    st.rerun()
            else:
                with st.container():
                    st.markdown(f"### 🇯🇵 **{item['meaning']}**")
                    st.write(f"📝 **例文:** {item.get('example', '')}")
                    if st.button("↩️ 表に戻す", key=f"btn_back_{card_key}"):
                        st.session_state[card_key] = False
                        st.rerun()
            st.write("")