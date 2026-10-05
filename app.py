import json
import datetime
import streamlit as st
import hashlib
import pandas as pd
from streamlit_gsheets import GSheetsConnection

IS_PAUSED = True

if IS_PAUSED:
    st.title("停止中")
    st.stop()  

DIAPLAY_NUM_MAX = 50

# ---------------------------------------------------------
# 0. ページ設定
# ---------------------------------------------------------
st.set_page_config(
    page_title="映画評価アンケート",
    page_icon="🎬",
    layout="wide"
)

# ---------------------------------------------------------
# セッション状態の初期化（アプリ最上部で一括管理）
# ---------------------------------------------------------
if "current_ratings" not in st.session_state:
    st.session_state.current_ratings = {}

if "global_reset_count" not in st.session_state:
    st.session_state.global_reset_count = 0

if "movie_reset_counters" not in st.session_state:
    st.session_state.movie_reset_counters = {}

if "search_kw" not in st.session_state:
    st.session_state.search_kw = ""

# ---------------------------------------------------------
# 1. JSONデータの読み込み & データ準備
# ---------------------------------------------------------
with open('movie.json', 'r', encoding='utf-8') as f:
    movie_data = json.load(f)

# ジャンルの抽出
all_genres = set()
for m_key, details in movie_data.items():
    if "genre" in details:
        for genre in details["genre"].split(","):
            all_genres.add(genre.strip())

genres = ["すべて"] + sorted(list(all_genres))


def hash_student_id(raw_id, salt_key):
    """学籍番号を不可逆なハッシュIDに変換"""
    if not raw_id:
        return ""
    clean_id = raw_id.strip().lower()
    return hashlib.sha256(f"{clean_id}_{salt_key}".encode('utf-8')).hexdigest()[:12]

# ---------------------------------------------------------
# カウンター・リセット関連関数
# ---------------------------------------------------------
def get_movie_counter(movie_id):
    return st.session_state.movie_reset_counters.get(movie_id, 0) + st.session_state.global_reset_count

def increment_movie_counter(movie_id):
    st.session_state.movie_reset_counters[movie_id] = st.session_state.movie_reset_counters.get(movie_id, 0) + 1

def reset_all_ratings():
    st.session_state.current_ratings = {}
    st.session_state.global_reset_count += 1

    keys_to_delete = [
        k for k in list(st.session_state.keys()) 
        if k.startswith("star_") or k.startswith("sb_select_")
    ]
    for k in keys_to_delete:
        del st.session_state[k]

def remove_single_rating(movie_id):
    st.session_state.current_ratings.pop(movie_id, None)
    increment_movie_counter(movie_id)
    
    keys_to_delete = [
        k for k in list(st.session_state.keys()) 
        if k.startswith(f"star_{movie_id}_") or k.startswith(f"sb_select_{movie_id}_")
    ]
    for k in keys_to_delete:
        del st.session_state[k]

# --- コールバック関数 ---
def update_rating_from_main(movie_id, movie_title, star_key):
    val = st.session_state.get(star_key)
    if val is not None:
        st.session_state.current_ratings[movie_id] = {
            "title": movie_title,
            "rating": val + 1
        }
    else:
        st.session_state.current_ratings.pop(movie_id, None)

def update_rating_from_sidebar(movie_id, movie_title, sb_key):
    new_val = st.session_state.get(sb_key)
    if new_val is not None:
        st.session_state.current_ratings[movie_id] = {
            "title": movie_title,
            "rating": new_val
        }
        increment_movie_counter(movie_id)

# ---------------------------------------------------------
# データ送信処理用関数
# ---------------------------------------------------------
def submit_data(hashed_id, ratings):
    with st.spinner("データをスプレッドシートへ送信中... しばらくお待ちください ⏳"):
        conn = st.connection("gsheets", type=GSheetsConnection)
        sheet_url = st.secrets["connections"]["gsheets"]["spreadsheet"]
        
        existing_data = conn.read(spreadsheet=sheet_url, ttl=0)
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        new_rows = []
        for m_id, item in ratings.items():
            new_rows.append({
                "user_id": hashed_id,
                "movie_id": m_id,
                "movie_title": item["title"],
                "rating": item["rating"],
                # "timestamp": now
            })
        
        new_df = pd.DataFrame(new_rows)
        updated_df = pd.concat([existing_data, new_df], ignore_index=True)
        conn.update(spreadsheet=sheet_url, data=updated_df)

# ---------------------------------------------------------
# モーダルダイアログ定義
# ---------------------------------------------------------
@st.dialog("送信完了")
def completion_dialog():
    st.success("評価の送信が正常に完了しました！")
    st.write("ご協力いただき、誠にありがとうございました。")
    st.caption("※「閉じる」を押して、ブラウザを閉じて終了してください。")
    
    if st.button("閉じる", type="primary", use_container_width=True):
        reset_all_ratings()
        st.session_state.show_completion_dialog = False
        st.rerun()

@st.dialog("送信内容の最終確認")
def confirm_submission_dialog(user_id, ratings):
    st.write(f"**ユーザーID:** `{user_id}`")
    st.write(f"**合計評価件数:** {len(ratings)} 件")
    
    st.caption("評価内訳:")
    preview_df = pd.DataFrame([
        {"映画タイトル": item["title"], "評価": f"★{item['rating']}"} 
        for m_id, item in ratings.items()
    ])
    st.dataframe(preview_df, use_container_width=True, height=180)
    
    st.warning("この内容でスプレッドシートへ送信します。よろしいですか？")
    
    col_yes, col_no = st.columns(2)
    with col_yes:
        if st.button("はい、送信します", type="primary", use_container_width=True):
            hashed_id = hash_student_id(user_id, st.secrets["connections"]["gsheets"]["salt_key"])
            submit_data(hashed_id, ratings)
            st.session_state.show_completion_dialog = True
            st.rerun()
            
    with col_no:
        if st.button("キャンセル", use_container_width=True):
            st.rerun()

# 送信完了モーダルチェック
if st.session_state.get("show_completion_dialog", False):
    completion_dialog()

# ---------------------------------------------------------
# サイドバー：評価状況 & 送信エリア
# ---------------------------------------------------------
with st.sidebar:
    st.header("あなたの評価状況")
    
    if st.session_state.get("submitted", False):
        st.success("評価を送信しました！ご協力ありがとうございました。")
        st.session_state.submitted = False
        reset_all_ratings()
        st.rerun()

    ratings_dict = st.session_state.current_ratings
    total_count = len(ratings_dict)
    
    high_count = sum(1 for item in ratings_dict.values() if item["rating"] in [4, 5])
    mid_count = sum(1 for item in ratings_dict.values() if item["rating"] == 3)
    low_count = sum(1 for item in ratings_dict.values() if item["rating"] in [1, 2])

    st.metric("現在の合計評価数", f"{total_count} 件")
    
    col_h, col_m, col_l = st.columns(3)
    col_h.metric("高(★4-5)", f"{high_count}件")
    col_m.metric("中(★3)", f"{mid_count}件")
    col_l.metric("低(★1-2)", f"{low_count}件")

    st.divider()

    user_id = st.text_input("ユーザーID", placeholder="例: al21114", key="sidebar_user_id")

    st.divider()

    if total_count > 0:
        st.subheader("評価済みの作品一覧・変更")
        
        for m_id, item in reversed(list(ratings_dict.items())):
            movie_name = item["title"]
            score = item["rating"]
            
            st.markdown(f"**{movie_name}**")
            
            sb_col1, sb_col2 = st.columns([3, 1])
            counter = get_movie_counter(m_id)
            sb_key = f"sb_select_{m_id}_{counter}"
            
            with sb_col1:
                st.selectbox(
                    label=f"{movie_name}の評価変更",
                    options=[5, 4, 3, 2, 1],
                    index=[5, 4, 3, 2, 1].index(score),
                    format_func=lambda x: f"★{x} ({'高' if x>=4 else '中' if x==3 else '低'})",
                    key=sb_key,
                    on_change=update_rating_from_sidebar,
                    args=(m_id, movie_name, sb_key),
                    label_visibility="collapsed"
                )

            with sb_col2:
                if st.button("🗑️️", key=f"del_{m_id}_{counter}", help="この評価を削除"):
                    remove_single_rating(m_id)
                    st.rerun()

            st.caption("---")

        if st.button("すべての評価をリセット", use_container_width=True, type="secondary"):
            reset_all_ratings()
            st.rerun()
    else:
        st.info("まだ評価された映画はありません。")

# ---------------------------------------------------------
# メイン画面
# ---------------------------------------------------------
st.title("映画の視聴履歴収集")

st.info("""
**【ご協力のおねがい】**  
検索やジャンル絞り込みを使い、見たことある映画に評価（★1〜5）をつけてください。\n
評価はできる限り多くしていただけると助かりますが、少なくても以下の数だけ評価していただきたいです。

**評価値の個数**
- 高評価(★5, ★4): 12個
- 中評価(★3): 6個
- 低評価(★2, ★1): 4個


**評価値の基準**
- (★5): とても満足できた
- (★4): 満足できた
- (★3): 普通だった
- (★2): やや期待外れだった
- (★1): 期待外れだった   

評価値の変更はサイドバーでも行えます。評価の削除は★マークをもう一度押すかサイドバーでも行えます。作業終了後は「評価送信」ボタンを押して結果を送信してください\n
「映画タイトルで検索」では入力後、Enterまたは検索ボタンを押すことで検索できます。「ジャンルで絞り込み」は変更後に自動で反映されます。

""")

main_top_col1, main_top_col2 = st.columns([3, 1])
with main_top_col1:
    st.subheader("映画を探して評価する")
with main_top_col2:
    if st.button("評価送信（確認へ）", type="primary", use_container_width=True, key="main_top_submit"):
        if not st.session_state.get("sidebar_user_id", "").strip():
            st.error("サイドバーでユーザーIDを入力してください。")
        elif total_count == 0:
            st.warning("評価（★）を1つ以上選択してください。")
        else:
            confirm_submission_dialog(st.session_state.sidebar_user_id, ratings_dict)

st.divider()

# ---------------------------------------------------------
# 検索・絞り込みエリア
# ---------------------------------------------------------
col_genre, col_search_input, col_search_btn = st.columns([2, 3, 1])

with col_genre:
    selected_genre = st.selectbox("ジャンルで絞り込み", genres)

with col_search_input:
    search_input_val = st.text_input("映画タイトルで検索", value=st.session_state.search_kw, placeholder="例: 千尋、ハリー")

with col_search_btn:
    st.markdown("<div style='margin-top: 28px;'></div>", unsafe_allow_html=True)
    search_clicked = st.button("検索", use_container_width=True, type="primary")

if search_clicked or (search_input_val != st.session_state.search_kw and search_input_val != ""):
    st.session_state.search_kw = search_input_val
elif search_input_val == "" and st.session_state.search_kw != "":
    st.session_state.search_kw = ""

search_kw = st.session_state.search_kw

# ---------------------------------------------------------
# フィルタ条件変更時のリセット判定
# ---------------------------------------------------------
filter_state_key = f"{selected_genre}_{search_kw}"
if st.session_state.get("last_filter") != filter_state_key:
    st.session_state.display_limit = DIAPLAY_NUM_MAX
    st.session_state.last_filter = filter_state_key

# ---------------------------------------------------------
# フィルタリング処理
# ---------------------------------------------------------
filtered_movies = []
for m_id, details in movie_data.items():
    title = details.get("title", "")
    raw_genres = [g.strip() for g in details.get("genre", "").split(",") if g.strip()]
    
    genre_match = (selected_genre == "すべて") or (selected_genre in raw_genres)
    search_match = (search_kw == "") or (search_kw.lower() in title.lower())
    
    if genre_match and search_match:
        filtered_movies.append({"movie_id": m_id, "title": title})

display_movies = filtered_movies[:st.session_state.display_limit]

st.subheader(f"映画一覧（該当: {len(filtered_movies)}件 / 表示中: {len(display_movies)}件）")

if not filtered_movies:
    st.warning("該当する映画が見つかりませんでした。")

# 映画リストの表示と評価UI
for movie in display_movies:
    c1, c2 = st.columns([3, 1])
    movie_id = movie.get("movie_id")
    title = movie.get("title")

    with c1:
        st.write(f"・**{title}**")
        
    with c2:
        counter = get_movie_counter(movie_id)
        star_key = f"star_{movie_id}_{counter}"
        
        current_item = st.session_state.current_ratings.get(movie_id)
        current_score = current_item["rating"] if current_item else None
        
        if current_score is not None and star_key not in st.session_state:
            st.session_state[star_key] = current_score - 1

        st.feedback(
            "stars",
            key=star_key,
            on_change=update_rating_from_main,
            args=(movie_id, title, star_key)
        )

# --- 「もっと見る」ボタン ---
remaining_count = len(filtered_movies) - len(display_movies)
if remaining_count > 0:
    st.markdown("---")
    if st.button(f"➕ さらに表示する（残り {remaining_count} 件）", use_container_width=True, type="secondary"):
        st.session_state.display_limit += DIAPLAY_NUM_MAX
        st.rerun()