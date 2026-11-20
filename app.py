import streamlit as st
import json
import os
import random
import base64
import time
import re
from PIL import Image
import io
from google import genai
from google.genai import types

st.set_page_config(page_title="英単語マスター", page_icon="📘", layout="wide")

# --- 明るいライトテーマ用のカスタムCSS ---
st.markdown("""
<style>
    /* 全体の背景を明るく清潔感のある色合いに */
    .stApp {
        background-color: #f8fafc;
        color: #1e293b;
    }
    /* ヘッダーバッジ */
    .header-box {
        background: #ffffff;
        padding: 1.2rem 1.5rem;
        border-radius: 14px;
        border: 1px solid #e2e8f0;
        box-shadow: 0 2px 6px rgba(15, 23, 42, 0.04);
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 1rem;
    }
    .header-title {
        font-size: 1.5rem;
        font-weight: 700;
        color: #0f172a;
        margin: 0;
    }
    .count-badge {
        background: #eef2ff;
        color: #4f46e5;
        font-weight: 700;
        padding: 0.35rem 0.9rem;
        border-radius: 999px;
        font-size: 0.95rem;
        border: 1px solid #c7d2fe;
    }
    /* 単語カード（裏面表示用） */
    .flashcard-back {
        background: #ffffff;
        border: 2px solid #6366f1;
        border-radius: 12px;
        padding: 1rem 1.2rem;
        box-shadow: 0 4px 10px rgba(99, 102, 241, 0.08);
        margin-bottom: 0.5rem;
    }
    .flashcard-word-small {
        font-size: 0.85rem;
        color: #64748b;
        font-weight: 600;
    }
    .flashcard-meaning {
        font-size: 1.2rem;
        font-weight: 700;
        color: #1e293b;
        margin: 0.25rem 0 0.5rem 0;
    }
    .flashcard-example {
        font-size: 0.92rem;
        color: #475569;
        background: #f1f5f9;
        padding: 0.5rem 0.75rem;
        border-radius: 8px;
    }
    /* テスト問題カード */
    .quiz-card {
        background: #ffffff;
        border: 1px solid #e2e8f0;
        border-radius: 16px;
        padding: 1.8rem;
        box-shadow: 0 4px 12px rgba(15, 23, 42, 0.05);
        margin: 1rem 0 1.2rem 0;
    }
    .quiz-badge {
        display: inline-block;
        background: #e0e7ff;
        color: #4338ca;
        font-size: 0.8rem;
        font-weight: 700;
        padding: 0.25rem 0.7rem;
        border-radius: 6px;
        margin-bottom: 0.8rem;
    }
    .quiz-question-text {
        font-size: 1.35rem;
        font-weight: 700;
        color: #0f172a;
        line-height: 1.6;
    }
    .quiz-hint-text {
        margin-top: 0.9rem;
        padding-top: 0.8rem;
        border-top: 1px dashed #cbd5e1;
        color: #475569;
        font-size: 1rem;
    }
    /* 結果カード */
    .result-card {
        background: #ffffff;
        border: 1px solid #e2e8f0;
        border-radius: 16px;
        padding: 2.2rem;
        text-align: center;
        box-shadow: 0 4px 14px rgba(15, 23, 42, 0.06);
        margin-bottom: 1.2rem;
    }
    .result-score {
        font-size: 2.4rem;
        font-weight: 800;
        color: #4f46e5;
        margin: 0.5rem 0;
    }
</style>
""", unsafe_allow_html=True)

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
    st.title("📘 英単語マスター - ログイン")
    
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

# --- 2. サイドバーナビゲーション ---
st.sidebar.markdown("## 📘 英単語マスター")
st.sidebar.caption(f"👤 {st.session_state.user_email}")

page = st.sidebar.radio(
    "メニュー",
    ["📖 勉強用 (カード一覧)", "✍️ 穴埋め・単語テスト", "⚠️ 間違えた問題の復習"],
    label_visibility="collapsed"
)

st.sidebar.write("---")
if st.sidebar.button("ログアウト", use_container_width=True):
    st.session_state.user_email = None
    st.rerun()

# ---------------------------------------------------------
# ページ1: 勉強用 (カード一覧)
# ---------------------------------------------------------
if page == "📖 勉強用 (カード一覧)":
    file_list = list(st.session_state.files.keys())
    
    # フォルダ管理・新規スキャンエリア
    with st.expander("📷 新しいフォルダを作成（画像スキャン）・管理", expanded=(len(file_list) == 0)):
        tab_add, tab_del = st.tabs(["➕ 写真から単語を追加", "🗑️ フォルダ削除"])
        with tab_add:
            uploaded_files = st.file_uploader(
                "単語帳の写真を選んでください（複数枚可）", 
                type=["png", "jpg", "jpeg", "heic"], 
                accept_multiple_files=True
            )
            file_name = st.text_input("作成するフォルダ名（例: Target1200_1151-1200）")
            
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
                            if i < len(uploaded_files) - 1:
                                time.sleep(1.5)
                    
                    if not all_parsed_words:
                        st.error("単語を読み取れませんでした。エラー内容やAPIキーを確認してください。")
                    else:
                        st.session_state.files[file_name] = {
                            "images": b64_images,
                            "words": all_parsed_words
                        }
                        save_user_data(st.session_state.user_email)
                        st.success(f"フォルダ「{file_name}」を作成し、{len(all_parsed_words)}単語を登録しました！")
                        time.sleep(1)
                        st.rerun()
                else:
                    st.warning("写真（1枚以上）とフォルダ名の両方を指定してください。")
        
        with tab_del:
            if file_list:
                target_del = st.selectbox("削除するフォルダを選択", file_list)
                if st.button(f"「{target_del}」を削除する"):
                    del st.session_state.files[target_del]
                    save_user_data(st.session_state.user_email)
                    st.success(f"「{target_del}」を削除しました。")
                    st.rerun()
            else:
                st.info("削除できるフォルダがありません。")

    if not file_list:
        st.info("まだ保存されたフォルダがありません。上のメニューから単語帳の写真をスキャンしてください。")
        st.stop()

    # フォルダ絞り込み＆検索バー
    col_f, col_s = st.columns([2, 1])
    with col_f:
        selected_files = st.multiselect("表示するフォルダ", file_list, default=file_list)
    with col_s:
        search_query = st.text_input("🔍 単語・意味を検索", placeholder="例: achieve / 達成する")

    all_cards = []
    for f_name in selected_files:
        for item in st.session_state.files[f_name].get("words", []):
            w = item.get("word", "")
            m = item.get("meaning", "")
            if not search_query or search_query.lower() in w.lower() or search_query in m:
                all_cards.append(item)

    # サイト風ヘッダー（タイトル + 全◯単語バッジ）
    st.markdown(f"""
    <div class="header-box">
        <div class="header-title">📖 勉強用 (カード一覧)</div>
        <div class="count-badge">全 {len(all_cards)} 単語</div>
    </div>
    """, unsafe_allow_html=True)

    st.caption("💡 カードをタップすると裏返り、日本語訳と例文が表示されます。")

    # 登録済み写真の確認・ダウンロード
    with st.expander("🖼️ スキャンした元の写真を表示・ダウンロード"):
        for f_name in selected_files:
            f_data = st.session_state.files[f_name]
            st.write(f"📁 **{f_name}**")
            images = f_data.get("images", [])
            cols = st.columns(min(len(images), 3) if images else 1)
            for idx, b64_img in enumerate(images):
                img_data = base64.b64decode(b64_img)
                with cols[idx % 3]:
                    st.image(img_data, caption=f"ページ {idx + 1}", use_container_width=True)
                    st.download_button(
                        label=f"ページ {idx + 1} を保存",
                        data=img_data,
                        file_name=f"{f_name}_p{idx + 1}.jpg",
                        mime="image/jpeg",
                        key=f"dl_{f_name}_{idx}"
                    )

    # 2列カードグリッド表示
    grid_cols = st.columns(2)
    for idx, item in enumerate(all_cards):
        word_txt = item.get("word", "")
        meaning_txt = item.get("meaning", "")
        example_txt = item.get("example", "")
        
        card_key = f"card_state_{idx}_{word_txt}"
        if card_key not in st.session_state:
            st.session_state[card_key] = False
        
        with grid_cols[idx % 2]:
            if not st.session_state[card_key]:
                if st.button(f"🇬🇧  {word_txt}", key=f"btn_{card_key}", use_container_width=True):
                    st.session_state[card_key] = True
                    st.rerun()
            else:
                st.markdown(f"""
                <div class="flashcard-back">
                    <div class="flashcard-word-small">🇬🇧 {word_txt}</div>
                    <div class="flashcard-meaning">🇯🇵 {meaning_txt}</div>
                    <div class="flashcard-example">📝 {example_txt if example_txt else '（例文なし）'}</div>
                </div>
                """, unsafe_allow_html=True)
                if st.button("↩️ 表に戻す", key=f"btn_back_{card_key}", use_container_width=True):
                    st.session_state[card_key] = False
                    st.rerun()

# ---------------------------------------------------------
# ページ2: 穴埋め・単語テスト
# ---------------------------------------------------------
elif page == "✍️ 穴埋め・単語テスト":
    file_list = list(st.session_state.files.keys())
    if not file_list:
        st.warning("フォルダが登録されていません。「📖 勉強用」ページで追加してください。")
        st.stop()
        
    # --- A. テスト設定画面 ---
    if st.session_state.test_state is None:
        st.markdown("""
        <div class="header-box">
            <div class="header-title">✍️ 穴埋め・単語テスト設定</div>
            <div class="count-badge">テストモード</div>
        </div>
        """, unsafe_allow_html=True)

        with st.container(border=True):
            st.write("例文の空欄 `[ ______ ]` や意味から正しい英単語・日本語を選択してください。")
            
            selected_files = st.multiselect("出題範囲（フォルダ）を選択", file_list, default=file_list)
            
            col1, col2 = st.columns(2)
            with col1:
                test_direction = st.radio("出題方向", ["日 → 英（穴埋め・意味から英単語）", "英 → 日（英単語から意味）"])
                num_questions = st.selectbox("出題数", [5, 10, 15, 20], index=1)
            with col2:
                test_type = st.radio("解答形式", ["選択式 (4択)", "記述式"])
                show_hint = st.toggle("英文の下に日本語訳（ヒント）を表示", value=True, help="出題時にヒントとして日本語訳を表示します")
            
            st.write("")
            if st.button("🚀 テストを開始する", type="primary", use_container_width=True):
                questions = []
                for f_name in selected_files:
                    for item in st.session_state.files[f_name].get("words", []):
                        if item.get("word") and item.get("meaning"):
                            questions.append(item)
                
                if not questions:
                    st.error("テストを作成できる単語が見つかりませんでした。")
                else:
                    random.shuffle(questions)
                    selected_q = questions[:min(num_questions, len(questions))]
                    st.session_state.test_state = {
                        "questions": selected_q,
                        "current_index": 0,
                        "score": 0,
                        "direction": test_direction,
                        "test_type": test_type,
                        "show_hint": show_hint,
                        "answered": False,
                        "user_choice": None,
                        "is_correct": False,
                        "options": []
                    }
                    st.rerun()

    # --- B. テスト進行・結果画面 ---
    else:
        ts = st.session_state.test_state
        q_idx = ts["current_index"]
        questions = ts["questions"]
        total_q = len(questions)
        is_en_to_ja = "英 → 日" in ts.get("direction", "")
        
        # テスト終了（結果画面）
        if q_idx >= total_q:
            score = ts["score"]
            rate = (score / total_q) * 100
            if rate >= 80:
                feedback = "素晴らしい成果です！この調子で学習を続けましょう。"
            elif rate >= 50:
                feedback = "よく頑張りました！間違えた単語を復習して完璧を目指しましょう。"
            else:
                feedback = "まずはカード一覧で意味と例文を確認してから再挑戦しましょう！"

            st.markdown(f"""
            <div class="result-card">
                <div style="font-size: 3rem;">🏆</div>
                <h2 style="margin: 0.3rem 0; color: #0f172a;">テスト終了！</h2>
                <div class="result-score">{score} / {total_q} 正解</div>
                <p style="color: #475569; font-size: 1.05rem;">{feedback}</p>
            </div>
            """, unsafe_allow_html=True)

            col_r1, col_r2 = st.columns(2)
            with col_r1:
                if st.button("🔄 設定に戻ってもう一度", type="primary", use_container_width=True):
                    st.session_state.test_state = None
                    st.rerun()
            with col_r2:
                if st.button("🔁 同じ設定で再テスト", use_container_width=True):
                    random.shuffle(ts["questions"])
                    ts["current_index"] = 0
                    ts["score"] = 0
                    ts["answered"] = False
                    ts["options"] = []
                    st.rerun()
            st.stop()
            
        current_q = questions[q_idx]
        word = current_q.get("word", "")
        meaning = current_q.get("meaning", "")
        example = current_q.get("example", "")
        
        # 上部プログレスバー＆ライブスコア
        col_p1, col_p2 = st.columns([3, 1])
        with col_p1:
            st.markdown(f"**第 {q_idx + 1} / {total_q} 問**")
        with col_p2:
            st.markdown(f"<div style='text-align:right; font-weight:700; color:#4f46e5;'>正解: {ts['score']}</div>", unsafe_allow_html=True)
        
        st.progress((q_idx) / total_q)

        # 問題カード表示
        if is_en_to_ja:
            hint_html = f"<div class='quiz-hint-text'>📝 例文: {example}</div>" if (ts["show_hint"] and example) else ""
            st.markdown(f"""
            <div class="quiz-card">
                <div class="quiz-badge">Word Meaning (英 → 日)</div>
                <div class="quiz-question-text">{word}</div>
                {hint_html}
            </div>
            """, unsafe_allow_html=True)
        else:
            if example and word.lower() in example.lower():
                blank_example = re.sub(re.escape(word), "[ ______ ]", example, flags=re.IGNORECASE)
                hint_html = f"<div class='quiz-hint-text'>💡 ヒント（日本語訳）: <b>{meaning}</b></div>" if ts["show_hint"] else ""
                st.markdown(f"""
                <div class="quiz-card">
                    <div class="quiz-badge">Fill in the blank (穴埋め)</div>
                    <div class="quiz-question-text">{blank_example}</div>
                    {hint_html}
                </div>
                """, unsafe_allow_html=True)
            else:
                st.markdown(f"""
                <div class="quiz-card">
                    <div class="quiz-badge">Translate to English (日 → 英)</div>
                    <div class="quiz-question-text">{meaning}</div>
                </div>
                """, unsafe_allow_html=True)

        # --- 解答エリア：選択式 (2×2 パネルグリッド) ---
        if "選択式" in ts["test_type"]:
            if not ts["options"]:
                if is_en_to_ja:
                    all_meanings = [
                        item["meaning"] for f_name in st.session_state.files 
                        for item in st.session_state.files[f_name].get("words", []) 
                        if item.get("meaning")
                    ]
                    dummy_choices = list(set([m for m in all_meanings if m != meaning]))
                    random.shuffle(dummy_choices)
                    choices = dummy_choices[:3] + [meaning]
                else:
                    all_words = [
                        item["word"] for f_name in st.session_state.files 
                        for item in st.session_state.files[f_name].get("words", []) 
                        if item.get("word")
                    ]
                    dummy_choices = list(set([w for w in all_words if w.lower() != word.lower()]))
                    random.shuffle(dummy_choices)
                    choices = dummy_choices[:3] + [word]
                
                random.shuffle(choices)
                ts["options"] = choices
            
            correct_answer = meaning if is_en_to_ja else word
            
            if not ts["answered"]:
                # 2×2のボタングリッドでタップ即回答
                row1 = st.columns(2)
                row2 = st.columns(2)
                grid_btns = [row1[0], row1[1], row2[0], row2[1]]
                
                for i, opt in enumerate(ts["options"]):
                    with grid_btns[i % 4]:
                        if st.button(opt, key=f"opt_{q_idx}_{i}", use_container_width=True):
                            ts["answered"] = True
                            ts["user_choice"] = opt
                            if opt == correct_answer:
                                ts["is_correct"] = True
                                ts["score"] += 1
                            else:
                                ts["is_correct"] = False
                                if current_q not in st.session_state.wrong_words:
                                    st.session_state.wrong_words.append(current_q)
                                    save_user_data(st.session_state.user_email)
                            st.rerun()
            else:
                if ts["is_correct"]:
                    st.success(f"⭕ 正解！ **{word}** ＝ **{meaning}**")
                else:
                    st.error(f"❌ 不正解...（あなたの選択: {ts['user_choice']}） 正解は **{word}** ＝ **{meaning}**")
                
                if example:
                    st.info(f"📝 完成例文: {example}")
                
                if st.button("次の問題へ ➡️", type="primary", use_container_width=True):
                    ts["current_index"] += 1
                    ts["answered"] = False
                    ts["options"] = []
                    st.rerun()

        # --- 解答エリア：記述式 ---
        else:
            if not is_en_to_ja:
                user_input = st.text_input("英単語を入力してください", key=f"q_input_{q_idx}")
                if not ts["answered"]:
                    if st.button("回答する", type="primary", use_container_width=True):
                        ts["answered"] = True
                        if user_input.strip().lower() == word.strip().lower():
                            ts["is_correct"] = True
                            ts["score"] += 1
                        else:
                            ts["is_correct"] = False
                            if current_q not in st.session_state.wrong_words:
                                st.session_state.wrong_words.append(current_q)
                                save_user_data(st.session_state.user_email)
                        st.rerun()
                else:
                    if ts["is_correct"]:
                        st.success(f"⭕ 正解！ **{word}**（{meaning}）")
                    else:
                        st.error(f"❌ 不正解... 正解は: **{word}**（{meaning}）")
                    if example:
                        st.info(f"📝 完成例文: {example}")
                    if st.button("次の問題へ ➡️", type="primary", use_container_width=True):
                        ts["current_index"] += 1
                        ts["answered"] = False
                        st.rerun()
            else:
                user_input = st.text_input("日本語の意味を入力してください", key=f"q_input_{q_idx}")
                if not ts["answered"]:
                    if st.button("答えを見る", type="primary", use_container_width=True):
                        ts["answered"] = True
                        ts["user_choice"] = user_input
                        st.rerun()
                else:
                    st.write(f"あなたの回答: **{ts['user_choice'] or '（未入力）'}**")
                    st.success(f"正解の意味: **{meaning}**")
                    if example:
                        st.info(f"📝 例文: {example}")
                    col1, col2 = st.columns(2)
                    with col1:
                        if st.button("⭕ 正解として次へ", type="primary", use_container_width=True):
                            ts["score"] += 1
                            ts["current_index"] += 1
                            ts["answered"] = False
                            st.rerun()
                    with col2:
                        if st.button("❌ 不正解（復習に追加）", use_container_width=True):
                            if current_q not in st.session_state.wrong_words:
                                st.session_state.wrong_words.append(current_q)
                                save_user_data(st.session_state.user_email)
                            ts["current_index"] += 1
                            ts["answered"] = False
                            st.rerun()

        st.write("")
        if st.button("テストを中断して設定に戻る"):
            st.session_state.test_state = None
            st.rerun()

# ---------------------------------------------------------
# ページ3: 間違えた問題の復習
# ---------------------------------------------------------
elif page == "⚠️ 間違えた問題の復習":
    wrong_list = st.session_state.wrong_words
    
    st.markdown(f"""
    <div class="header-box">
        <div class="header-title">⚠️ 間違えた問題の復習</div>
        <div class="count-badge">復習対象 {len(wrong_list)} 単語</div>
    </div>
    """, unsafe_allow_html=True)

    if not wrong_list:
        st.success("🎉 現在、間違えた問題はありません！テストを受けて苦手な単語を見つけましょう。")
    else:
        st.caption("テストで間違えた単語が集約されます。タップして意味と例文を確認しましょう。")
        if st.button("🗑️ 間違えたリストをすべてクリア"):
            st.session_state.wrong_words = []
            save_user_data(st.session_state.user_email)
            st.rerun()
            
        st.write("")
        grid_cols = st.columns(2)
        for idx, item in enumerate(wrong_list):
            word_txt = item.get("word", "")
            meaning_txt = item.get("meaning", "")
            example_txt = item.get("example", "")
            
            card_key = f"wrong_card_{idx}_{word_txt}"
            if card_key not in st.session_state:
                st.session_state[card_key] = False
                
            with grid_cols[idx % 2]:
                if not st.session_state[card_key]:
                    if st.button(f"🇬🇧  {word_txt}", key=f"btn_{card_key}", use_container_width=True):
                        st.session_state[card_key] = True
                        st.rerun()
                else:
                    st.markdown(f"""
                    <div class="flashcard-back">
                        <div class="flashcard-word-small">🇬🇧 {word_txt}</div>
                        <div class="flashcard-meaning">🇯🇵 {meaning_txt}</div>
                        <div class="flashcard-example">📝 {example_txt if example_txt else '（例文なし）'}</div>
                    </div>
                    """, unsafe_allow_html=True)
                    col_b1, col_b2 = st.columns(2)
                    with col_b1:
                        if st.button("↩️ 表に戻す", key=f"btn_back_{card_key}", use_container_width=True):
                            st.session_state[card_key] = False
                            st.rerun()
                    with col_b2:
                        if st.button("✅ 覚えた（削除）", key=f"btn_del_{card_key}", use_container_width=True):
                            st.session_state.wrong_words.pop(idx)
                            save_user_data(st.session_state.user_email)
                            st.rerun()