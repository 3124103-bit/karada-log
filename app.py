import base64
import json
import os
import sqlite3
import uuid
from datetime import date, datetime
from pathlib import Path

import streamlit as st


APP_DIR = Path(__file__).parent
DB_PATH = APP_DIR / "health.db"
UPLOAD_DIR = APP_DIR / "uploads"


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    UPLOAD_DIR.mkdir(exist_ok=True)
    with get_connection() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS meals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            logged_date TEXT NOT NULL,
            created_at TEXT NOT NULL,
            memo TEXT,
            image_path TEXT,
            estimated_items TEXT,
            calories REAL NOT NULL DEFAULT 0,
            protein REAL NOT NULL DEFAULT 0,
            fat REAL NOT NULL DEFAULT 0,
            carbs REAL NOT NULL DEFAULT 0,
            advice TEXT,
            ai_source TEXT
        );
        CREATE TABLE IF NOT EXISTS strength_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            logged_date TEXT NOT NULL,
            exercise TEXT NOT NULL,
            weight REAL,
            reps INTEGER,
            sets INTEGER,
            memo TEXT
        );
        CREATE TABLE IF NOT EXISTS cardio_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            logged_date TEXT NOT NULL,
            activity TEXT NOT NULL,
            minutes INTEGER,
            calories_burned REAL,
            memo TEXT,
            image_path TEXT,
            ai_source TEXT
        );
        """)
        cardio_columns = {row["name"] for row in conn.execute("PRAGMA table_info(cardio_logs)")}
        if "image_path" not in cardio_columns:
            conn.execute("ALTER TABLE cardio_logs ADD COLUMN image_path TEXT")
        if "ai_source" not in cardio_columns:
            conn.execute("ALTER TABLE cardio_logs ADD COLUMN ai_source TEXT")


def safe_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def fallback_estimate(memo: str) -> dict:
    """APIキーがないときも画面を試せる、控えめなデモ推定。"""
    text = (memo or "").lower()
    if any(word in text for word in ["サラダ", "野菜", "salad"]):
        return {"items": "野菜のサラダ（デモ推定）", "calories": 180, "protein": 8, "fat": 10, "carbs": 15,
                "advice": "たんぱく質源（鶏肉、卵、豆腐など）を足すと食事のバランスが整います。"}
    if any(word in text for word in ["鶏", "チキン", "chicken"]):
        return {"items": "鶏肉を含む食事（デモ推定）", "calories": 520, "protein": 35, "fat": 16, "carbs": 55,
                "advice": "良いたんぱく質源です。野菜や海藻も添えると微量栄養素を補えます。"}
    return {"items": "食事（デモ推定）", "calories": 500, "protein": 20, "fat": 18, "carbs": 65,
            "advice": "これはデモ推定です。APIキーを設定すると写真とメモからより具体的に推定します。"}


def estimate_meal(memo: str, image_bytes: bytes | None, mime_type: str | None) -> tuple[dict, str]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return fallback_estimate(memo), "デモ推定（APIキー未設定）"

    try:
        from openai import OpenAI
        contents = [{"type": "input_text", "text": f"""あなたは栄養管理アシスタントです。食事写真とメモから、食べた内容と栄養を概算してください。
メモ: {memo or 'なし'}
次のJSONだけを返してください。数値は1食分の推定値です。
{{\"items\": \"料理名・量の簡潔な説明\", \"calories\": 0, \"protein\": 0, \"fat\": 0, \"carbs\": 0, \"advice\": \"健康・筋トレ向けの短い改善提案\"}}"""}]
        if image_bytes:
            image_url = f"data:{mime_type or 'image/jpeg'};base64,{base64.b64encode(image_bytes).decode()}"
            contents.append({"type": "input_image", "image_url": image_url})
        response = OpenAI(api_key=api_key).responses.create(
            model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
            input=[{"role": "user", "content": contents}],
        )
        raw = response.output_text.strip()
        raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        result = json.loads(raw)
        required = ["items", "calories", "protein", "fat", "carbs", "advice"]
        if not all(key in result for key in required):
            raise ValueError("AI response lacked required keys")
        return result, "AI推定"
    except Exception as exc:
        st.warning(f"AI推定に失敗したため、デモ推定を表示しています: {exc}")
        return fallback_estimate(memo), "デモ推定（AI接続失敗）"


def save_upload(uploaded_file) -> str | None:
    if uploaded_file is None:
        return None
    suffix = Path(uploaded_file.name).suffix.lower() or ".jpg"
    filename = f"{uuid.uuid4().hex}{suffix}"
    path = UPLOAD_DIR / filename
    path.write_bytes(uploaded_file.getvalue())
    return str(path)


def estimate_cardio_from_photo(image_bytes: bytes, mime_type: str | None) -> tuple[dict | None, str]:
    """ランニングマシン等の画面を読取り、有酸素ログに変換する。"""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None, "AIキー未設定"
    try:
        from openai import OpenAI
        image_url = f"data:{mime_type or 'image/jpeg'};base64,{base64.b64encode(image_bytes).decode()}"
        prompt = """これは有酸素運動マシンの表示画面、または運動記録の写真です。表示から運動内容を読み取ってください。
次のJSONだけを返してください。読めない値は 0、種目が不明なら「有酸素運動」にしてください。
{\"activity\": \"ランニングなどの種目\", \"minutes\": 0, \"calories_burned\": 0, \"memo\": \"距離・速度・傾斜など、読めた補足\"}"""
        response = OpenAI(api_key=api_key).responses.create(
            model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
            input=[{"role": "user", "content": [
                {"type": "input_text", "text": prompt},
                {"type": "input_image", "image_url": image_url},
            ]}],
        )
        raw = response.output_text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        result = json.loads(raw)
        if "activity" not in result:
            raise ValueError("AI response lacked activity")
        return result, "AI写真読取"
    except Exception as exc:
        st.warning(f"写真の読取りに失敗しました: {exc}")
        return None, "AI読取失敗"


def number(value):
    return f"{safe_float(value):,.0f}"


init_db()
st.set_page_config(page_title="からだログ MVP", page_icon="🥗", layout="wide")
st.markdown("""
<style>
/* Streamlit標準の英語メニューはアプリ利用に不要なため非表示にする。 */
#MainMenu, footer, [data-testid="stToolbar"] { visibility: hidden; }

/* 写真アップロード欄の案内を日本語化する。 */
[data-testid="stFileUploaderDropzoneInstructions"] div { font-size: 0; }
[data-testid="stFileUploaderDropzoneInstructions"] div::before {
    content: "写真をここにドラッグ＆ドロップ";
    font-size: 0.95rem;
}
[data-testid="stFileUploaderDropzoneInstructions"] small { font-size: 0; }
[data-testid="stFileUploaderDropzoneInstructions"] small::before {
    content: "JPG、PNG、WebP に対応";
    font-size: 0.8rem;
}
[data-testid="stFileUploader"] button { font-size: 0; }
[data-testid="stFileUploader"] button::after {
    content: "写真を選択";
    font-size: 0.9rem;
}
</style>
""", unsafe_allow_html=True)
st.title("🥗 からだログ")
st.caption("食事と運動を記録して、1日の流れを見える化するローカルMVP")

selected_date = st.sidebar.date_input("表示・登録する日", value=date.today())
st.sidebar.divider()
st.sidebar.caption("AI推定を使うには環境変数 OPENAI_API_KEY を設定してください。未設定でもデモ推定で試せます。")

tab_meal, tab_strength, tab_cardio, tab_day = st.tabs(["🍱 食事", "🏋️ 筋トレ", "🏃 有酸素", "📅 1日のまとめ"])

with tab_meal:
    st.subheader("食事を登録")
    with st.form("meal_form", clear_on_submit=True):
        photo = st.file_uploader("食事写真（任意）", type=["jpg", "jpeg", "png", "webp"])
        memo = st.text_area("食事メモ", placeholder="例：鶏むね肉の定食。ご飯は小盛り。")
        submitted = st.form_submit_button("AIで推定して登録", type="primary")
    if submitted:
        image_bytes = photo.getvalue() if photo else None
        estimate, source = estimate_meal(memo, image_bytes, photo.type if photo else None)
        image_path = save_upload(photo)
        with get_connection() as conn:
            conn.execute("""INSERT INTO meals
                (logged_date, created_at, memo, image_path, estimated_items, calories, protein, fat, carbs, advice, ai_source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (selected_date.isoformat(), datetime.now().isoformat(timespec="seconds"), memo, image_path,
                 estimate["items"], safe_float(estimate["calories"]), safe_float(estimate["protein"]),
                 safe_float(estimate["fat"]), safe_float(estimate["carbs"]), estimate["advice"], source))
        st.success("食事を登録しました。")

    with get_connection() as conn:
        meals = conn.execute("SELECT * FROM meals WHERE logged_date = ? ORDER BY id DESC", (selected_date.isoformat(),)).fetchall()
    st.subheader("この日の食事")
    if not meals:
        st.info("まだ食事ログはありません。")
    for meal in meals:
        with st.container(border=True):
            left, right = st.columns([1, 3])
            with left:
                if meal["image_path"] and Path(meal["image_path"]).exists():
                    st.image(meal["image_path"], use_container_width=True)
            with right:
                st.markdown(f"**{meal['estimated_items']}**  ")
                st.caption(f"{meal['ai_source']} · {meal['memo'] or 'メモなし'}")
                st.write(f"{number(meal['calories'])} kcal　P {number(meal['protein'])}g / F {number(meal['fat'])}g / C {number(meal['carbs'])}g")
                st.write(f"💡 {meal['advice']}")

with tab_strength:
    st.subheader("筋トレを登録")
    with st.form("strength_form", clear_on_submit=True):
        exercise = st.text_input("種目", placeholder="例：ベンチプレス")
        c1, c2, c3 = st.columns(3)
        weight = c1.number_input("重量 (kg)", min_value=0.0, step=0.5)
        reps = c2.number_input("回数", min_value=0, step=1)
        sets = c3.number_input("セット数", min_value=0, step=1)
        strength_memo = st.text_input("メモ（任意）", placeholder="例：フォームを意識")
        add_strength = st.form_submit_button("筋トレを登録", type="primary")
    if add_strength:
        if not exercise.strip():
            st.error("種目を入力してください。")
        else:
            with get_connection() as conn:
                conn.execute("INSERT INTO strength_logs (logged_date, exercise, weight, reps, sets, memo) VALUES (?, ?, ?, ?, ?, ?)",
                             (selected_date.isoformat(), exercise.strip(), weight, reps, sets, strength_memo))
            st.success("筋トレを登録しました。")

with tab_cardio:
    st.subheader("有酸素運動を登録")
    st.caption("ランニングマシンの表示写真なら、時間・消費カロリーなどを自動で読んで登録できます。")
    with st.form("cardio_form", clear_on_submit=True):
        cardio_photo = st.file_uploader("マシン表示の写真（任意）", type=["jpg", "jpeg", "png", "webp"], key="cardio_photo")
        activity = st.text_input("種目", placeholder="例：ウォーキング")
        c1, c2 = st.columns(2)
        minutes = c1.number_input("時間（分）", min_value=0, step=5)
        burned = c2.number_input("消費カロリー（kcal・任意）", min_value=0.0, step=10.0)
        cardio_memo = st.text_input("メモ（任意）")
        auto_cardio = st.form_submit_button("写真から読み取って登録", type="primary")
        add_cardio = st.form_submit_button("手入力で登録")
    if auto_cardio:
        if cardio_photo is None:
            st.error("ランニングマシンなどの表示写真を選んでください。")
        else:
            estimate, source = estimate_cardio_from_photo(cardio_photo.getvalue(), cardio_photo.type)
            if estimate is None:
                st.info("AI写真読取には OPENAI_API_KEY の設定が必要です。手入力でも登録できます。")
            else:
                with get_connection() as conn:
                    conn.execute("INSERT INTO cardio_logs (logged_date, activity, minutes, calories_burned, memo, image_path, ai_source) VALUES (?, ?, ?, ?, ?, ?, ?)",
                                 (selected_date.isoformat(), str(estimate["activity"]), int(safe_float(estimate.get("minutes"))),
                                  safe_float(estimate.get("calories_burned")), str(estimate.get("memo", "")),
                                  save_upload(cardio_photo), source))
                st.success(f"写真から「{estimate['activity']}」として登録しました。")
    if add_cardio:
        if not activity.strip():
            st.error("種目を入力してください。")
        else:
            with get_connection() as conn:
                conn.execute("INSERT INTO cardio_logs (logged_date, activity, minutes, calories_burned, memo, image_path, ai_source) VALUES (?, ?, ?, ?, ?, ?, ?)",
                             (selected_date.isoformat(), activity.strip(), minutes, burned, cardio_memo,
                              save_upload(cardio_photo), "手入力"))
            st.success("有酸素運動を登録しました。")

with tab_day:
    st.subheader(f"{selected_date.strftime('%Y年%m月%d日')} のまとめ")
    with get_connection() as conn:
        totals = conn.execute("SELECT COALESCE(SUM(calories),0) calories, COALESCE(SUM(protein),0) protein, COALESCE(SUM(fat),0) fat, COALESCE(SUM(carbs),0) carbs FROM meals WHERE logged_date = ?", (selected_date.isoformat(),)).fetchone()
        strength = conn.execute("SELECT * FROM strength_logs WHERE logged_date = ? ORDER BY id DESC", (selected_date.isoformat(),)).fetchall()
        cardio = conn.execute("SELECT * FROM cardio_logs WHERE logged_date = ? ORDER BY id DESC", (selected_date.isoformat(),)).fetchall()
    a, b, c, d = st.columns(4)
    a.metric("摂取カロリー", f"{number(totals['calories'])} kcal")
    b.metric("たんぱく質", f"{number(totals['protein'])} g")
    c.metric("脂質", f"{number(totals['fat'])} g")
    d.metric("炭水化物", f"{number(totals['carbs'])} g")
    left, right = st.columns(2)
    with left:
        st.markdown("#### 筋トレ")
        if strength:
            st.dataframe([{"種目": r["exercise"], "重量(kg)": r["weight"], "回数": r["reps"], "セット": r["sets"], "メモ": r["memo"]} for r in strength], use_container_width=True, hide_index=True)
        else:
            st.caption("記録なし")
    with right:
        st.markdown("#### 有酸素")
        if cardio:
            st.dataframe([{"種目": r["activity"], "時間(分)": r["minutes"], "消費(kcal)": r["calories_burned"], "メモ": r["memo"], "登録方法": r["ai_source"] or "手入力"} for r in cardio], use_container_width=True, hide_index=True)
        else:
            st.caption("記録なし")
