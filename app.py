import json
import datetime
import streamlit as st
import hashlib
import pandas as pd
from pathlib import Path
import random 
import time
from supabase import create_client, Client

IS_PAUSED = False
if IS_PAUSED:
    st.title("修正のため一時停止中")
    st.stop()  

DIAPLAY_NUM_MAX = 100

# ---------------------------------------------------------
# 0. ページ設定
# ---------------------------------------------------------
st.set_page_config(
    page_title="映画評価アンケート",
    page_icon="🎬",
    layout="wide"
)

# ---------------------------------------------------------
# セッション状態の初期化
# ---------------------------------------------------------
if "current_ratings" not in st.session_state:
    st.session_state.current_ratings = {}

if "persisted_movie_ids" not in st.session_state:
    st.session_state.persisted_movie_ids = set()

if "deleted_movie_ids" not in st.session_state:
    st.session_state.deleted_movie_ids = set()

if "search_kw" not in st.session_state:
    st.session_state.search_kw = ""

# ---------------------------------------------------------
# 1. JSONデータの読み込み & アプリ起動時に一度だけシャッフルして固定
# ---------------------------------------------------------
with open('movie.json', 'r', encoding='utf-8') as f:
    movie_data = json.load(f)

if "FIXED_SHUFFLED_KEYS" not in st.session_state:
    keys = list(movie_data.keys())
    random.shuffle(keys)
    st.session_state.FIXED_SHUFFLED_KEYS = keys

# ジャンルの抽出
all_genres = set()
for m_key, details in movie_data.items():
    if "genre" in details:
        for genre in details["genre"].split(","):
            all_genres.add(genre.strip())

genres = ["すべて"] + sorted(list(all_genres))

all_years = sorted(
    {details["year"] for details in movie_data.values() if details.get("year")},
    reverse=True
)
years = ["すべて"] + all_years

# ---------------------------------------------------------
# リセット関連関数
# ---------------------------------------------------------
def reset_all_ratings():
    keys_to_delete = [
        k for k in list(st.session_state.keys()) 
        if k.startswith("eval_") or k.startswith("sb_select_")
    ]
    for k in keys_to_delete:
        del st.session_state[k]
    st.session_state.current_ratings = {}
    st.session_state.persisted_movie_ids = set()
    st.session_state.deleted_movie_ids = set()

def remove_single_rating(movie_id):
    normalized_movie_id = int(movie_id)
    if normalized_movie_id in st.session_state.persisted_movie_ids:
        st.session_state.deleted_movie_ids.add(normalized_movie_id)
    st.session_state.current_ratings.pop(movie_id, None)
    st.session_state.pop(f"eval_{movie_id}", None)
    st.session_state.pop(f"sb_select_{movie_id}", None)

# --- コールバック関数（メイン画面の評価変更用） ---
def update_rating_from_main(movie_id, movie_title):
    eval_key = f"eval_{movie_id}"
    score = st.session_state.get(eval_key)
    if score is not None:
        st.session_state.deleted_movie_ids.discard(int(movie_id))
        st.session_state.current_ratings[movie_id] = {
            "title": movie_title,
            "rating": score
        }
        st.session_state[f"sb_select_{movie_id}"] = score
    else:
        if int(movie_id) in st.session_state.persisted_movie_ids:
            st.session_state.deleted_movie_ids.add(int(movie_id))
        st.session_state.current_ratings.pop(movie_id, None)
        st.session_state.pop(f"sb_select_{movie_id}", None)

# --- コールバック関数（サイドバーの変更用） ---
def update_rating_from_sidebar(movie_id, movie_title):
    sb_key = f"sb_select_{movie_id}"
    score = st.session_state.get(sb_key)
    if score is not None:
        st.session_state.deleted_movie_ids.discard(int(movie_id))
        st.session_state.current_ratings[movie_id] = {
            "title": movie_title,
            "rating": score
        }
        st.session_state[f"eval_{movie_id}"] = score

# ---------------------------------------------------------
# データ送信・復元処理用関数（Supabase版）
# ---------------------------------------------------------
def submit_data(user_id, ratings):
    with st.spinner("データを送信中... しばらくお待ちください"):
        try:
            supabase_url = st.secrets["supabase"]["url"]
            supabase_key = st.secrets["supabase"]["key"]
            supabase: Client = create_client(supabase_url, supabase_key)
            
            # Delete only ratings explicitly removed after restoring them.
            movie_ids_to_delete = st.session_state.deleted_movie_ids
            if movie_ids_to_delete:
                supabase.table("ratings").delete().eq("user_id", user_id).in_("movie_id", list(movie_ids_to_delete)).execute()
            
            # 4. 手元にある評価をUPSERT（新規なら追加、既存なら最新に更新）
            if ratings:
                rows_to_upsert = []
                for movie_id, item in ratings.items():
                    rows_to_upsert.append({
                        "user_id": user_id,
                        "movie_id": int(movie_id),
                        "title": item["title"],
                        "rating": int(item["rating"]),
                    })
                
                supabase.table("ratings").upsert(
                    rows_to_upsert, 
                    on_conflict="user_id,movie_id"
                ).execute()
            
            st.session_state.show_completion_dialog = True
            st.rerun()
            
        except Exception as e:
            st.error(f"データの送信に失敗しました: {e}")

def restore_ratings(raw_user_id):
    """Supabaseから指定した学籍番号の既存評価を読み込んで復元する"""
    if not raw_user_id or not raw_user_id.strip():
        st.sidebar.error("学籍番号を入力してください。")
        return

    with st.spinner("データを検索中..."):
        try:
            clean_id = raw_user_id.strip().lower()
            
            supabase_url = st.secrets["supabase"]["url"]
            supabase_key = st.secrets["supabase"]["key"]
            supabase: Client = create_client(supabase_url, supabase_key)
            
            response = supabase.table("ratings").select("movie_id, title, rating").eq("user_id", clean_id).execute()
            data = response.data
            
            if not data:
                st.sidebar.warning("該当する保存データが見つかりませんでした。")
                return
            
            reset_all_ratings()
            
            restored_dict = {}
            for row in data:
                m_id = row["movie_id"]
                score = row["rating"]
                restored_dict[m_id] = {
                    "title": row["title"],
                    "rating": score
                }
                # メインのピルボタンとサイドバー双方のステートに直接数値を代入
                st.session_state[f"eval_{m_id}"] = score
                st.session_state[f"sb_select_{m_id}"] = score

            st.session_state.current_ratings = restored_dict
            st.session_state.persisted_movie_ids = {int(row["movie_id"]) for row in data}
            st.sidebar.success(f"{len(restored_dict)}件の評価を復元しました！")
            time.sleep(0.5)
            st.rerun()
            
        except Exception as e:
            st.sidebar.error(f"復元に失敗しました: {e}")

# ---------------------------------------------------------
# モーダルダイアログ定義
# ---------------------------------------------------------
@st.dialog("送信完了")
def completion_dialog():
    st.success("評価の送信が完了しました")
    st.write("ご協力いただき、ありがとうございました。")
    st.caption("ブラウザを閉じて終了してください。")
    
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
    
    st.warning("この内容で送信します。よろしいですか？（同じ作品の評価は上書きされ、復元後に削除した評価だけが削除されます）")
    
    col_yes, col_no = st.columns(2)
    with col_yes:
        if st.button("送信する", type="primary", use_container_width=True):
            clean_id = user_id.strip().lower()
            submit_data(clean_id, ratings)
            st.session_state.show_completion_dialog = True
            st.rerun()
            
    with col_no:
        if st.button("送信しない", use_container_width=True):
            st.rerun()

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

    user_id = st.text_input("学籍番号(alの部分は小文字)", placeholder="例: al21114", key="sidebar_user_id")

    if st.button("これまでの評価を読み込む", use_container_width=True, help="入力した学籍番号で既に送信したデータがあれば読み込みます"):
        restore_ratings(user_id)

    st.divider()

    if total_count > 0:
        st.subheader("評価済みの作品一覧・変更")
        
        for m_id, item in reversed(list(ratings_dict.items())):
            movie_name = item["title"]
            score = item["rating"]
            
            st.markdown(f"**{movie_name}**")
            
            sb_col1, sb_col2 = st.columns([3, 1])
            sb_key = f"sb_select_{m_id}"
            
            if sb_key not in st.session_state:
                st.session_state[sb_key] = score
            
            with sb_col1:
                st.selectbox(
                    label=f"{movie_name}の評価変更",
                    options=[5, 4, 3, 2, 1],
                    index=[5, 4, 3, 2, 1].index(score),
                    format_func=lambda x: f"★{x} ({'高' if x>=4 else '中' if x==3 else '低'})",
                    key=sb_key,
                    on_change=update_rating_from_sidebar,
                    args=(m_id, movie_name),
                    label_visibility="collapsed"
                )

            with sb_col2:
                if st.button("🗑", key=f"del_{m_id}", help="この評価を削除"):
                    remove_single_rating(m_id)
                    st.rerun()

            st.caption("---")

        # if st.button("すべての評価をリセット", use_container_width=True, type="secondary"):
        #     reset_all_ratings()
        #     st.rerun()
    else:
        st.info("まだ評価された映画はありません。")

# ---------------------------------------------------------
# メイン画面
# ---------------------------------------------------------
st.title("映画の視聴履歴収集")

st.info("""
**【ご協力のおねがい】**\n 
始める時はサイドバーで学籍番号を入力しておいてください。\n 
途中から再開する場合は、学籍番号を入力して「以前の評価を復元する」を押してください\n\n
検索やジャンル・邦画/洋画・年代での絞り込みを使い、見たことある映画に評価（★1〜5）をつけてください。\n
評価はできる限り多くしていただけると助かりますが、少なくても以下の数だけ評価していただきたいです。\n
最低20件なので、それより多く評価していただけると助かります。\n
もし、必要数だけ評価できなくても、結果は送信してください。

**必要な評価数(最低20個**
- 高評価(★5, ★4): **11個**
- 中評価(★3): **5個**
- 低評価(★2, ★1): **4個**


**評価値の基準**
- (★5): とても満足できた
- (★4): 満足できた
- (★3): 普通だった
- (★2): やや期待外れだった
- (★1): 期待外れだった  

・評価値の変更はサイドバーでも行えます。評価の削除はサイドバーのゴミ箱ボタンか、★マークを再度押すと行えます。作業終了後は「評価送信」ボタンを押して結果を送信してください\n
・「映画タイトルで検索」では入力後、Enterまたは検索ボタンを押すことで検索できます。ジャンルと邦画・洋画の絞り込みは変更後に自動で反映されます。\n
・多く表示しすぎないように検索を活用してください。
""")

main_top_col1, main_top_col2 = st.columns([3, 1])
with main_top_col1:
    st.subheader("映画を探して評価する")
with main_top_col2:
    if st.button("評価送信（確認へ）", type="primary", use_container_width=True, key="main_top_submit"):
        if not st.session_state.get("sidebar_user_id", "").strip():
            st.error("サイドバーでユーザーIDを入力してください。")
        # elif total_count == 0:
            # st.warning("評価（★）を1つ以上選択してください。")
        else:
            confirm_submission_dialog(st.session_state.sidebar_user_id, ratings_dict)

st.divider()

# ---------------------------------------------------------
# 検索・絞り込みエリア
# ---------------------------------------------------------
col_genre, col_style, col_year, col_search_input, col_search_btn = st.columns([2, 2, 1.5, 3, 1])

with col_genre:
    selected_genre = st.selectbox("ジャンルで絞り込み", genres)

with col_style:
    selected_style = st.selectbox("邦画・洋画で絞り込み", ["すべて", "邦画", "洋画"])

with col_year:
    selected_year = st.selectbox("公開年で絞り込み", years)

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
filter_state_key = f"{selected_genre}_{selected_style}_{selected_year}_{search_kw}"
if st.session_state.get("last_filter") != filter_state_key:
    st.session_state.display_limit = DIAPLAY_NUM_MAX
    st.session_state.last_filter = filter_state_key

# ---------------------------------------------------------
# フィルタリング処理（固定されたシャッフル順を使用）
# ---------------------------------------------------------
filtered_movies = []
for title_key in st.session_state.FIXED_SHUFFLED_KEYS:
    details = movie_data[title_key]
    m_id = details.get("movie_id")
    title = details.get("title", "")
    raw_genres = [g.strip() for g in details.get("genre", "").split(",") if g.strip()]
    movie_style = details.get("style", "その他")
    movie_year = details.get("year", "")
    
    genre_match = (selected_genre == "すべて") or (selected_genre in raw_genres)
    style_match = (selected_style == "すべて") or (movie_style in [selected_style, "その他"])
    year_match = (selected_year == "すべて") or (movie_year == selected_year)
    search_match = (search_kw == "") or (search_kw.lower() in title.lower())
    
    if genre_match and style_match and year_match and search_match:
        filtered_movies.append({"movie_id": m_id, "title": title})

display_movies = filtered_movies[:st.session_state.display_limit]

st.subheader(f"映画一覧（該当: {len(filtered_movies)}件 / 表示中: {len(display_movies)}件）")

if not filtered_movies:
    st.warning("該当する映画が見つかりませんでした。")

# 映画リストの表示と評価UI（st.pills を用いた完全同期型のボタン評価）
# 修正後
for movie in display_movies:
    c1, c2 = st.columns([1, 1])
    movie_id = movie.get("movie_id")
    title = movie.get("title")

    with c1:
        st.write(f"・**{title}**")
        
    with c2:
        eval_key = f"eval_{movie_id}"
        
        current_item = st.session_state.current_ratings.get(movie_id)
        st.session_state[eval_key] = current_item["rating"] if current_item else None

        st.pills(
            label=f"{title}の評価",
            options=[5, 4, 3, 2, 1],
            format_func=lambda x: f"★{x}",
            key=eval_key,
            on_change=update_rating_from_main,
            args=(movie_id, title),
            label_visibility="collapsed"
        )

# --- 「もっと見る」ボタン ---
remaining_count = len(filtered_movies) - len(display_movies)
if remaining_count > 0:
    st.markdown("---")
    if st.button(f"➕ さらに表示する（残り {remaining_count} 件）", use_container_width=True, type="secondary"):
        st.session_state.display_limit += DIAPLAY_NUM_MAX
        st.rerun()