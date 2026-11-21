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
            model="gemini-1.5-flash",
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
                    st.session_state.files[file_name] = {"images": b64_images, "words": all_parsed_words}
                    save_user_data(st.session_state.user_email)
                    st.success(f"{len(all_parsed_words)}単語を登録しました！")
                    time.sleep(1.5)
                    st.rerun()
                else:
                    st.error("⚠️ 画像の解析に失敗しました。")
                    if error_messages:
                        st.info("【AIからのエラー内容】")
                        st.code(error_messages[0])
                        st.write("💡 ログアウトして **正しいAPIキー** を入れ直すか、画像枚数を減らして再試行してください。")
            else:
                st.warning("写真とフォルダ名の両方を指定してください。")

    if file_list:
        with st.expander("🗑️ フォルダを完全に削除"):
            del_folder = st.selectbox("削除するフォルダを選択", file_list)
            if st.button("このフォルダを削除", type="primary"):
                del st.session_state.files[del_folder]
                if st.session_state.selected_folders and del_folder in st.session_state.selected_folders:
                    st.session_state.selected_folders.remove(del_folder)
                save_user_data(st.session_state.user_email)
                st.success(f"「{del_folder}」を削除しました。")
                time.sleep(1)
                st.rerun()

    file_list = list(st.session_state.files.keys())
    if not file_list:
        st.stop()

    if st.session_state.selected_folders is None:
        default_files = file_list
    else:
        default_files = [f for f in st.session_state.selected_folders if f in file_list]

    selected_files = st.multiselect("表示するフォルダ", file_list, default=default_files)
    st.session_state.selected_folders = selected_files
    
    search_query = st.text_input("🔍 単語・意味を検索")
    
    all_cards = [w for f in selected_files for w in st.session_state.files[f].get("words", []) 
                 if not search_query or search_query.lower() in w.get("word","").lower() or search_query in w.get("meaning","")]

    st.markdown(f'<div class="header-box"><div class="header-title">📖 学習カード</div><div class="count-badge">全 {len(all_cards)} 単語</div></div>', unsafe_allow_html=True)
    
    tab1, tab2 = st.tabs(["🃏 フラッシュカード", "📋 フォルダ中身一覧"])
    
    with tab1:
        st.caption("💡 カードをタップすると一瞬で裏返ります。")
        cards_html = '<div class="flip-container">\n'
        for item in all_cards:
            w = item.get("word", "")
            m = item.get("meaning", "")
            e = item.get("example", "")
            cards_html += f"""<div class="flip-card">
<div class="flip-card-inner" onclick="this.style.transform = this.style.transform === 'rotateY(180deg)' ? 'rotateY(0deg)' : 'rotateY(180deg)'">
<div class="flip-card-front">🇬🇧 {w}</div>
<div class="flip-card-back">
<div style="font-size:0.9rem; color:#64748b; font-weight:bold;">🇬🇧 {w}</div>
<div style="font-size:1.3rem; font-weight:800; color:#0f172a; margin:4px 0;">🇯🇵 {m}</div>
<div style="font-size:0.9rem; color:#475569; background:#f1f5f9; padding:8px; border-radius:6px; margin-top:8px;">📝 {e}</div>
</div>
</div>
</div>\n"""
        cards_html += '</div>'
        st.markdown(cards_html, unsafe_allow_html=True)

    with tab2:
        st.caption("💡 選択中のフォルダに入っている単語のリストです。")
        if not all_cards:
            st.write("単語が見つかりません。")
        else:
            for item in all_cards:
                with st.container(border=True):
                    st.markdown(f"**🇬🇧 {item.get('word', '')}** ＝ 🇯🇵 {item.get('meaning', '')}")
                    if item.get('example'):
                        st.caption(f"📝 {item.get('example', '')}")

# ---------------------------------------------------------
# ページ2: 単語テスト
# ---------------------------------------------------------
elif page == "✍️ 単語テスト":
    file_list = list(st.session_state.files.keys())
    if not file_list: st.stop()
        
    if st.session_state.test_state is None:
        st.markdown('<div class="header-box"><div class="header-title">✍️ テスト設定</div></div>', unsafe_allow_html=True)
        
        if st.session_state.selected_folders is None:
            default_files = file_list
        else:
            default_files = [f for f in st.session_state.selected_folders if f in file_list]
            
        selected_files = st.multiselect("出題範囲", file_list, default=default_files)
        st.session_state.selected_folders = selected_files

        col1, col2 = st.columns(2)
        with col1:
            test_dir = st.radio("出題方向", ["日 → 英（穴埋め）", "英 → 日"])
            num_q = st.selectbox("出題数", [5, 10, 15, 20], index=1)
        with col2:
            test_type = st.radio("形式", ["選択式 (4択)", "記述式"])
            show_hint = st.toggle("ヒントを表示", value=True)
        
        if st.button("🚀 テスト開始", type="primary", use_container_width=True):
            qs = [w for f in selected_files for w in st.session_state.files[f].get("words", []) if w.get("word") and w.get("meaning")]
            random.shuffle(qs)
            st.session_state.test_state = {"questions": qs[:num_q], "idx": 0, "score": 0, "dir": test_dir, "type": test_type, "hint": show_hint, "ans": False, "opts": []}
            st.rerun()
    else:
        ts = st.session_state.test_state
        if ts["idx"] >= len(ts["questions"]):
            st.markdown(f'<div class="header-box"><div class="header-title">🏆 結果: {ts["score"]} / {len(ts["questions"])} 正解</div></div>', unsafe_allow_html=True)
            if st.button("🔄 終了して戻る", type="primary", use_container_width=True):
                st.session_state.test_state = None
                st.rerun()
            st.stop()
            
        q = ts["questions"][ts["idx"]]
        is_en_to_ja = "英 → 日" in ts["dir"]
        
        st.progress(ts["idx"] / len(ts["questions"]))
        st.markdown(f"**第 {ts['idx'] + 1} 問** (正解: {ts['score']})")

        if is_en_to_ja:
            st.markdown(f'<div class="quiz-card"><div class="quiz-question-text">{q["word"]}</div></div>', unsafe_allow_html=True)
        else:
            blank = re.sub(re.escape(q["word"]), "[ ______ ]", q.get("example",""), flags=re.IGNORECASE) if q.get("example") else q["meaning"]
            hint = f'<div class="quiz-hint-text">💡 意味: {q["meaning"]}</div>' if ts["hint"] else ""
            st.markdown(f'<div class="quiz-card"><div class="quiz-question-text">{blank}</div>{hint}</div>', unsafe_allow_html=True)

        if "選択式" in ts["type"]:
            if not ts["opts"]:
                pool = [w["meaning"] if is_en_to_ja else w["word"] for f in st.session_state.files for w in st.session_state.files[f].get("words", [])]
                correct = q["meaning"] if is_en_to_ja else q["word"]
                dummy = list(set([x for x in pool if x != correct]))
                random.shuffle(dummy)
                ts["opts"] = dummy[:3] + [correct]
                random.shuffle(ts["opts"])
            
            if not ts["ans"]:
                cols = st.columns(2)
                for i, opt in enumerate(ts["opts"]):
                    if cols[i%2].button(opt, use_container_width=True):
                        ts["ans"] = True
                        if opt == (q["meaning"] if is_en_to_ja else q["word"]):
                            ts["score"] += 1
                        else:
                            if q not in st.session_state.wrong_words: st.session_state.wrong_words.append(q)
                            save_user_data(st.session_state.user_email)
                        st.rerun()
            else:
                st.success(f"正解は: {q['word']} ＝ {q['meaning']}")
                if st.button("次へ ➡️", type="primary", use_container_width=True):
                    ts["idx"] += 1
                    ts["ans"] = False
                    ts["opts"] = []
                    st.rerun()

# ---------------------------------------------------------
# ページ3: 復習リスト
# ---------------------------------------------------------
elif page == "⚠️ 復習リスト":
    wrongs = st.session_state.wrong_words
    st.markdown(f'<div class="header-box"><div class="header-title">⚠️ 復習リスト</div><div class="count-badge">{len(wrongs)} 単語</div></div>', unsafe_allow_html=True)

    if not wrongs:
        st.success("間違えた問題はありません！")
    else:
        if st.button("🗑️ すべてクリア"):
            st.session_state.wrong_words = []
            save_user_data(st.session_state.user_email)
            st.rerun()
            
        cols = st.columns(2)
        for idx, item in enumerate(wrongs):
            with cols[idx % 2]:
                with st.container(border=True):
                    st.markdown(f"**🇬🇧 {item['word']}**")
                    st.markdown(f"🇯🇵 {item['meaning']}")
                    st.caption(f"📝 {item.get('example','')}")
                    if st.button("✅ 覚えた", key=f"del_{idx}"):
                        st.session_state.wrong_words.pop(idx)
                        save_user_data(st.session_state.user_email)
                        st.rerun()