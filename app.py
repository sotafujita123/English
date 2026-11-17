import streamlit as st
import json
import os
import random
import base64
import time
from PIL import Image
import io
from google import genai
from google.genai import types

st.set_page_config(page_title="英単語帳スキャンアプリ", layout="wide")

# --- Secrets（裏設定）からAPIキーを取得する関数 ---
def get_secret_api_key():
    try:
        return st.secrets.get("GEMINI_API_KEY", "")
    except Exception:
        return ""

# --- 画像を軽量化してJPEG形式に変換する関数 ---
def convert_to_jpeg(img_bytes):
    try:
        try:
            from pillow_heif import register_heif_opener
            register_heif_opener()
        except ImportError:
            pass
        
        image = Image.open(io.BytesIO(img_bytes))
        image = image.convert("RGB")
        # 通信エラー防止のため長辺1600px以内にリサイズ（文字は十分読めます）
        image.thumbnail((1600, 1600))
        output = io.BytesIO()
        image.save(output, format="JPEG", quality=85)
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

# --- APIキーの接続テスト関数 ---
def test_gemini_connection(api_key):
    clean_key = api_key.strip()
    if not clean_key:
        return False, "APIキーが空です。"
    try:
        client = genai.Client(api_key=clean_key)
        for model_name in ["gemini-3.8-flash", "gemini-3.5-flash-lite", "gemini-2.5-flash"]:
            try:
                res = client.models.generate_content(
                    model=model_name,
                    contents="Reply with OK"
                )
                if res.text:
                    return True, f"接続成功！（使用モデル: {model_name}）"
            except Exception:
                continue
        return False, "APIキーは認識されましたが、利用可能なモデルが見つかりませんでした。"
    except Exception as e:
        return False, f"APIキーが無効または通信エラーです: {e}"

# --- 画像からのOCR読み取り処理 (最新 google-genai SDK) ---
def process_image_with_ocr(image_bytes, api_key):
    clean_key = api_key.strip()
    if not clean_key:
        st.error("APIキーが設定されていません。")
        return None
    
    client = genai.Client(api_key=clean_key)
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
    
    # 最新モデルから順に自動試行
    candidate_models = ["gemini-3.8-flash", "gemini-3.5-flash-lite", "gemini-2.5-flash"]
    last_error = None
    
    for model_name in candidate_models:
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=[
                    types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"),
                    prompt
                ]
            )
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
            last_error = e
            continue
            
    st.error(f"Gemini OCR解析エラー: {last_error}")
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
    
    secret_key = get_secret_api_key()
    saved_key = ""
    if email_input:
        existing_data = load_user_data(email_input)
        saved_key = existing_data.get("api_key", "")
    
    default_key = secret_key or saved_key
    
    if default_key:
        st.success("✅ APIキーを自動検出しました。そのままログインできます。")
        api_key_input = st.text_input("Gemini API Key（変更する場合のみ入力）", value=default_key, type="password")
    else:
        api_key_input = st.text_input("Gemini API Key（AIzaSy... で始まるキー）", type="password")
    
    col1, col2 = st.columns([1, 2])
    with col1:
        login_clicked = st.button("ログイン", type="primary", use_container_width=True)
    with col2:
        if st.button("🔍 入力したAPIキーが使えるかテストする"):
            ok, msg = test_gemini_connection(api_key_input)
            if ok:
                st.success(msg)
            else:
                st.error(msg)
                
    if login_clicked:
        if email_input:
            st.session_state.user_email = email_input
            loaded_data = load_user_data(email_input)
            final_key = api_key_input.strip() if api_key_input.strip() else default_key
            
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
    
    with st.expander("📷 新しいフォルダを作成（画像から単語登録）", expanded=True):
        uploaded_files = st.file_uploader(
            "写真を選んでください（最初は1枚ずつ試すのがおすすめです）", 
            type=["png", "jpg", "jpeg", "heic"], 
            accept_multiple_files=True
        )
        file_name = st.text_input("作成するフォルダ名を入力（例: Chapter1_名詞）")
        
        if st.button("スキャンしてフォルダに保存", type="primary"):
            if uploaded_files and file_name:
                all_parsed_words = []
                b64_images = []
                
                progress_bar = st.progress(0)
                with st.spinner(f"Gemini AIが{len(uploaded_files)}枚の画像を解析中..."):
                    for i, uploaded_file in enumerate(uploaded_files):
                        raw_bytes = uploaded_file.read()
                        jpeg_bytes = convert_to_jpeg(raw_bytes)
                        b64_img = base64.b64encode(jpeg_bytes).decode('utf-8')
                        b64_images.append(b64_img)
                        
                        parsed = process_image_with_ocr(jpeg_bytes, st.session_state.api_key)
                        if parsed:
                            all_parsed_words.extend(parsed)
                        
                        progress_bar.progress((i + 1) / len(uploaded_files))
                        # 連続アクセス制限を防ぐため少し待機
                        if i < len(uploaded_files) - 1:
                            time.sleep(1.5)
                
                if not all_parsed_words:
                    st.error("単語を読み取れませんでした。上のエラー内容またはAPIキーを確認してください。")
                else:
                    st.session_state.files[file_name] = {
                        "images": b64_images,
                        "words": all_parsed_words
                    }
                    save_user_data(st.session_state.user_email)
                    st.success(f"フォルダ「{file_name}」を作成し、{len(all_parsed_words)}個の単語を登録しました！")
                    time.sleep(1)
                    st.rerun()
            else:
                st.warning("写真（1枚以上）とフォルダ名の両方を指定してください。")

    file_list = list(st.session_state.files.keys())
    if file_list:
        with st.expander("🗑️ フォルダの削除・整理"):
            target_del = st.selectbox("削除したいフォルダを選択", file_list)
            if st.button(f"「{target_del}」を削除する"):
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
                cols = st.columns(min(len(images), 3) if images else 1)
                for idx, b64_img in enumerate(images):
                    img_data = base64.b64decode(b64_img)
                    with cols[idx % 3]:
                        st.image(img_data, caption=f"ページ {idx + 1}", use_container_width=True)
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
            word_txt = item.get("word", "")
            meaning_txt = item.get("meaning", "")
            example_txt = item.get("example", "")
            
            card_key = f"card_state_{idx}_{word_txt}"
            if card_key not in st.session_state:
                st.session_state[card_key] = False
            
            if not st.session_state[card_key]:
                if st.button(f"🇬🇧  {word_txt}  (タップで裏返す)", key=f"btn_{card_key}", use_container_width=True):
                    st.session_state[card_key] = True
                    st.rerun()
            else:
                with st.container():
                    st.markdown(f"### 🇯🇵 **{meaning_txt}**")
                    st.write(f"📝 **例文:** {example_txt}")
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
                    if item.get("example") and item.get("word", "").lower() in item.get("example", "").lower():
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
            word_txt = item.get("word", "")
            meaning_txt = item.get("meaning", "")
            example_txt = item.get("example", "")
            
            card_key = f"wrong_card_{idx}_{word_txt}"
            if card_key not in st.session_state:
                st.session_state[card_key] = False
                
            if not st.session_state[card_key]:
                if st.button(f"🇬🇧 {word_txt} (タップで裏返す)", key=f"btn_{card_key}", use_container_width=True):
                    st.session_state[card_key] = True
                    st.rerun()
            else:
                with st.container():
                    st.markdown(f"### 🇯🇵 **{meaning_txt}**")
                    st.write(f"📝 **例文:** {example_txt}")
                    if st.button("↩️ 表に戻す", key=f"btn_back_{card_key}"):
                        st.session_state[card_key] = False
                        st.rerun()
            st.write("")