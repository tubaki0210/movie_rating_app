import json
import datetime
import streamlit as st
import pandas as pd
from streamlit_gsheets import GSheetsConnection

# ---------------------------------------------------------
# 0. ページ設定
# ---------------------------------------------------------
st.set_page_config(
    page_title="映画評価アンケート",
    page_icon="🎬",
    layout="wide"
)

# 1. JSONデータの読み込み
with open('movie.json', 'r', encoding='utf-8') as f:
    movie_data = json.load(f)

# ジャンルの抽出
all_genres = set()
for m_key, details in movie_data.items():
    if "genre" in details:
        for genre in details["genre"].split(","):
            all_genres.add(genre.strip())

genres = ["すべて"] + sorted(list(all_genres))

# ---------------------------------------------------------
# セッション状態の初期化
# ---------------------------------------------------------
if "current_ratings" not in st.session_state:
    st.session_state.current_ratings = {}

# 全体・映画ごとのリセット用グローバルカウンター
if "global_reset_count" not in st.session_state:
    st.session_state.global_reset_count = 0

if "movie_reset_counters" not in st.session_state:
    st.session_state.movie_reset_counters = {}

def get_movie_counter(movie_title):
    return st.session_state.movie_reset_counters.get(movie_title, 0) + st.session_state.global_reset_count

def increment_movie_counter(movie_title):
    st.session_state.movie_reset_counters[movie_title] = st.session_state.movie_reset_counters.get(movie_title, 0) + 1

# --- 全体リセット関数（確定版） ---
def reset_all_ratings():
    # 1. 評価データ本体を完全に空にする
    st.session_state.current_ratings = {}
    
    # 2. グローバルカウンターを増やし、すべての画面内キーIDを一新する
    st.session_state.global_reset_count += 1

    # 3. 既存の星・セレクトボックス関連のsession_stateキーをすべて完全削除
    keys_to_delete = [
        k for k in list(st.session_state.keys()) 
        if k.startswith("star_") or k.startswith("sb_select_")
    ]
    for k in keys_to_delete:
        del st.session_state[k]

# --- 個別削除関数 ---
def remove_single_rating(movie_title):
    st.session_state.current_ratings.pop(movie_title, None)
    increment_movie_counter(movie_title)
    
    # 個別削除対象のキーも削除
    keys_to_delete = [
        k for k in list(st.session_state.keys()) 
        if k.startswith(f"star_{movie_title}_") or k.startswith(f"sb_select_{movie_title}_")
    ]
    for k in keys_to_delete:
        del st.session_state[k]

# --- コールバック関数：メイン画面の星変更時 ---
def update_rating_from_main(movie_title, star_key):
    val = st.session_state.get(star_key)
    if val is not None:
        st.session_state.current_ratings[movie_title] = val + 1
    else:
        st.session_state.current_ratings.pop(movie_title, None)

# --- コールバック関数：サイドバーのセレクトボックス変更時 ---
def update_rating_from_sidebar(movie_title, sb_key):
    new_val = st.session_state.get(sb_key)
    if new_val is not None:
        st.session_state.current_ratings[movie_title] = new_val
        increment_movie_counter(movie_title)

# ---------------------------------------------------------
# データ送信処理用関数
# ---------------------------------------------------------
def submit_data(user_id, ratings):
# ローディング表示を出す
    with st.spinner("データをスプレッドシートへ送信中... しばらくお待ちください ⏳"):
        conn = st.connection("gsheets", type=GSheetsConnection)
        
        # secrets.toml からスプレッドシートのURLを取得
        sheet_url = st.secrets["connections"]["gsheets"]["spreadsheet"]
        
        # read() と update() に明示的に spreadsheet パラメータを渡す
        existing_data = conn.read(spreadsheet=sheet_url, ttl=0)
        
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        new_rows = []
        for movie, rating_val in ratings.items():
            new_rows.append({
                "user_id": user_id,
                "movie_title": movie,
                "rating": rating_val,
                "timestamp": now
            })
        
        new_df = pd.DataFrame(new_rows)
        updated_df = pd.concat([existing_data, new_df], ignore_index=True)
        
        # update() 時にも spreadsheet パラメータを指定
        conn.update(spreadsheet=sheet_url, data=updated_df)

# ---------------------------------------------------------
# 1. 送信完了表示モーダルダイアログ（画面中央）
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

# ---------------------------------------------------------
# 2. 送信確認モーダルダイアログ（画面中央）
# ---------------------------------------------------------
@st.dialog("送信内容の最終確認")
def confirm_submission_dialog(user_id, ratings):
    st.write(f"**ユーザーID:** `{user_id}`")
    st.write(f"**合計評価件数:** {len(ratings)} 件")
    
    st.caption("評価内訳:")
    preview_df = pd.DataFrame([
        {"映画タイトル": m, "評価": f"★{r}"} for m, r in ratings.items()
    ])
    st.dataframe(preview_df, use_container_width=True, height=180)
    
    st.warning("この内容でスプレッドシートへ送信します。よろしいですか？")
    
    col_yes, col_no = st.columns(2)
    with col_yes:
        if st.button("はい、送信します", type="primary", use_container_width=True):
            # 送信実行
            submit_data(user_id, ratings)
            # 送信確認ダイアログを閉じ、完了ダイアログのフラグを立てて再描画
            st.session_state.show_completion_dialog = True
            st.rerun()
            
    with col_no:
        if st.button("キャンセル", use_container_width=True):
            st.rerun()


# ---------------------------------------------------------
# 送信完了モーダルチェック（アプリ描画時に判定）
# ---------------------------------------------------------
if st.session_state.get("show_completion_dialog", False):
    completion_dialog()


# ---------------------------------------------------------
# サイドバー：評価状況 & 送信エリア
# ---------------------------------------------------------
with st.sidebar:
    st.header("📊 あなたの評価状況")
    
    # 完了メッセージの表示（送信直後）
    if st.session_state.get("submitted", False):
        st.success("評価を送信しました！ご協力ありがとうございました。")
        st.session_state.submitted = False
        reset_all_ratings()
        st.rerun()

    ratings_dict = st.session_state.current_ratings
    total_count = len(ratings_dict)
    
    # 内訳カウント
    high_count = sum(1 for r in ratings_dict.values() if r in [4, 5])
    mid_count = sum(1 for r in ratings_dict.values() if r == 3)
    low_count = sum(1 for r in ratings_dict.values() if r in [1, 2])

    # 集計メトリクス表示
    st.metric("現在の合計評価数", f"{total_count} 件")
    
    col_h, col_m, col_l = st.columns(3)
    col_h.metric("高(★4-5)", f"{high_count}件")
    col_m.metric("中(★3)", f"{mid_count}件")
    col_l.metric("低(★1-2)", f"{low_count}件")

    st.divider()

    # --- 送信ボタンエリア（サイドバー上部） ---
    user_id = st.text_input("ユーザーID", placeholder="例: user123", key="sidebar_user_id")
    
    # if st.button("🚀 評価を送信する", type="primary", use_container_width=True):
    #     if not user_id.strip():
    #         st.error("ユーザーIDを入力してください。")
    #     elif total_count == 0:
    #         st.warning("評価（★）を1つ以上選択してください。")
    #     else:
    #         confirm_submission_dialog(user_id, ratings_dict)

    st.divider()

    # 評価した映画の一覧・編集表示
    if total_count > 0:
        st.subheader("📝 評価済みの作品一覧・変更")
        
        for movie_name, score in reversed(list(ratings_dict.items())):
            st.markdown(f"**{movie_name}**")
            
            sb_col1, sb_col2 = st.columns([3, 1])
            counter = get_movie_counter(movie_name)
            sb_key = f"sb_select_{movie_name}_{counter}"
            
            with sb_col1:
                st.selectbox(
                    label=f"{movie_name}の評価変更",
                    options=[5, 4, 3, 2, 1],
                    index=[5, 4, 3, 2, 1].index(score),
                    format_func=lambda x: f"★{x} ({'高' if x>=4 else '中' if x==3 else '低'})",
                    key=sb_key,
                    on_change=update_rating_from_sidebar,
                    args=(movie_name, sb_key),
                    label_visibility="collapsed"
                )

            with sb_col2:
                if st.button("🗑️", key=f"del_{movie_name}_{counter}", help="この評価を削除"):
                    remove_single_rating(movie_name)
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
st.title("映画の視聴履歴収集アプリ")

st.info("""
**【ご協力のおねがい】**  
検索やジャンル絞り込みを使い、見たことある映画に評価（★1〜5）をつけてください。
評価値の基準
- (★5): とても満足できた
- (★4): 満足できた
- (★3): 普通だった
- (★2): やや期待外れだった
- (★1): 期待外れだった   
評価値の変更はサイドバーで行えます。作業終了後は「評価送信」ボタンを押して結果を送信してください
""")

# 上部送信ショートカット
main_top_col1, main_top_col2 = st.columns([3, 1])
with main_top_col1:
    st.subheader("🔍 映画を探して評価する")
with main_top_col2:
    if st.button("🚀 評価送信（確認へ）", type="primary", use_container_width=True, key="main_top_submit"):
        if not st.session_state.get("sidebar_user_id", "").strip():
            st.error("サイドバーでユーザーIDを入力してください。")
        elif total_count == 0:
            st.warning("評価（★）を1つ以上選択してください。")
        else:
            confirm_submission_dialog(st.session_state.sidebar_user_id, ratings_dict)

st.divider()

# 検索・絞り込みエリア
col_genre, col_search = st.columns([1, 2])

with col_genre:
    selected_genre = st.selectbox("ジャンルで絞り込み", genres)

with col_search:
    search_kw = st.text_input("映画タイトルで検索", placeholder="例: 千尋、ハリー")

# フィルタ条件が変わったら表示件数を最初の40件にリセットする判定
filter_state_key = f"{selected_genre}_{search_kw}"
if st.session_state.get("last_filter") != filter_state_key:
    st.session_state.display_limit = 40
    st.session_state.last_filter = filter_state_key


# フィルタリング処理
filtered_movies = []
for m_key, details in movie_data.items():
    title = details.get("title", m_key)
    raw_genres = [g.strip() for g in details.get("genre", "").split(",") if g.strip()]
    
    genre_match = (selected_genre == "すべて") or (selected_genre in raw_genres)
    search_match = (search_kw == "") or (search_kw.lower() in title.lower())
    
    if genre_match and search_match:
        filtered_movies.append(title)

display_movies = filtered_movies[:st.session_state.display_limit]

st.subheader(f"📋 映画一覧（該当: {len(filtered_movies)}件 / 表示中: {len(display_movies)}件）")

if not filtered_movies:
    st.warning("該当する映画が見つかりませんでした。")

# 映画リストの表示と評価UI
for movie in display_movies:  # 表示対象の映画タイトルを1つずつ取り出してループ処理
    c1, c2 = st.columns([3, 1])  # 画面を横方向に「3 : 1」の比率で2つの列（カラム）に分割
    
    with c1:  # 左側の広いエリア（比率3）
        st.write(f"・**{movie}**")  # 映画タイトルを太字で表示
        
    with c2:  # 右側の狭いエリア（比率1）
        # リセットや変更時にウィジェット（星）を強制再描画するための識別番号（カウンター）を取得
        counter = get_movie_counter(movie)
        
        # Streamlitがウィジェットを識別するためのユニークなキー名（例: star_千と千尋の神隠し_0）を作成
        star_key = f"star_{movie}_{counter}"
        
        # すでにユーザーがこの映画を評価しているか、現在の評価スコア（1〜5）を取得
        current_score = st.session_state.current_ratings.get(movie)
        
        # 【同期処理】サイドバー等で評価が変更されていて、かつ星のキーが未初期化の場合、
        # st.feedback は 0〜4 のインデックスを扱うため「評価値 - 1」を初期値としてセット
        if current_score is not None and star_key not in st.session_state:
            st.session_state[star_key] = current_score - 1

        # 星マーク（★1〜5）の入力ウィジェットを表示
        st.feedback(
            "stars",                            # 星形式を指定
            key=star_key,                       # ユニークキーを設定
            on_change=update_rating_from_main,  # 星がクリックされた時に呼び出す関数
            args=(movie, star_key)              # 関数の引数として映画名とキー名を渡す
        )

# --- 「もっと見る」ボタンの配置 ---
remaining_count = len(filtered_movies) - len(display_movies)
if remaining_count > 0:
    st.markdown("---")
    if st.button(f"➕ さらに表示する（残り {remaining_count} 件）", use_container_width=True, type="secondary"):
        st.session_state.display_limit += 40
        st.rerun()