"""クラウド公開用エントリーポイント。秘密情報はStreamlit Secretsで管理する。"""
import base64, json, os, uuid
from datetime import date

import streamlit as st
from supabase import create_client

st.set_page_config(page_title="からだログ", page_icon="🥗", layout="wide")

def secret(name):
    return os.getenv(name) or st.secrets.get(name)

def login_gate():
    password = secret("APP_PASSWORD")
    if not password or st.session_state.get("authenticated"):
        return
    st.title("🥗 からだログ")
    st.caption("このアプリは非公開です。")
    entered = st.text_input("パスワード", type="password")
    if st.button("ログイン"):
        if entered == password:
            st.session_state.authenticated = True
            st.rerun()
        st.error("パスワードが違います。")
    st.stop()

login_gate()
url, key = secret("SUPABASE_URL"), secret("SUPABASE_SECRET_KEY")
if not url or not key:
    st.error("クラウド接続の設定がまだです。管理者がSecretsを設定してください。")
    st.stop()
db = create_client(url, key)

def upload(file):
    if not file: return None
    path = f"{date.today().isoformat()}/{uuid.uuid4().hex}_{file.name}"
    db.storage.from_("health-photos").upload(path, file.getvalue(), {"content-type": file.type, "upsert": "false"})
    return path

def signed(path):
    if not path: return None
    return db.storage.from_("health-photos").create_signed_url(path, 3600)["signedURL"]

def ai(prompt, image=None):
    api_key = secret("OPENAI_API_KEY")
    if not api_key: return None
    from openai import OpenAI
    content = [{"type":"input_text", "text":prompt}]
    if image:
        content.append({"type":"input_image", "image_url":f"data:{image.type};base64,{base64.b64encode(image.getvalue()).decode()}"})
    raw = OpenAI(api_key=api_key).responses.create(model=secret("OPENAI_MODEL") or "gpt-4.1-mini", input=[{"role":"user","content":content}]).output_text
    return json.loads(raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip())

st.title("🥗 からだログ")
selected = st.sidebar.date_input("表示・登録する日", date.today())
tabs = st.tabs(["🍱 食事", "🏋️ 筋トレ", "🏃 有酸素", "📅 1日のまとめ"])

with tabs[0]:
    with st.form("meal", clear_on_submit=True):
        photo = st.file_uploader("食事写真（任意）", type=["jpg","jpeg","png","webp"])
        memo = st.text_area("食事メモ")
        add = st.form_submit_button("AIで推定して登録")
    if add:
        try:
            r = ai('食事写真とメモから栄養を概算。JSONのみ: {"items":"料理", "calories":0,"protein":0,"fat":0,"carbs":0,"advice":"短い助言"}。メモ:'+memo, photo)
            if not r: r={"items":"食事（手入力メモ）","calories":0,"protein":0,"fat":0,"carbs":0,"advice":"AI推定にはAPIキー設定が必要です。"}
            db.table("meals").insert({"logged_date":str(selected),"memo":memo,"image_url":upload(photo),"estimated_items":r["items"],"calories":r["calories"],"protein":r["protein"],"fat":r["fat"],"carbs":r["carbs"],"advice":r["advice"],"ai_source":"AI推定" if secret("OPENAI_API_KEY") else "手入力"}).execute()
            st.success("食事を登録しました。")
        except Exception as e: st.error(f"登録できませんでした: {e}")

with tabs[1]:
    with st.form("strength", clear_on_submit=True):
        exercise=st.text_input("種目"); c1,c2,c3=st.columns(3); weight=c1.number_input("重量 (kg)",0.0); reps=c2.number_input("回数",0); sets=c3.number_input("セット数",0); memo=st.text_input("メモ（任意）")
        add=st.form_submit_button("筋トレを登録")
    if add and exercise:
        db.table("strength_logs").insert({"logged_date":str(selected),"exercise":exercise,"weight":weight,"reps":reps,"sets":sets,"memo":memo}).execute(); st.success("筋トレを登録しました。")

with tabs[2]:
    with st.form("cardio", clear_on_submit=True):
        photo=st.file_uploader("マシン表示の写真（任意）",type=["jpg","jpeg","png","webp"]); activity=st.text_input("種目"); c1,c2=st.columns(2); minutes=c1.number_input("時間（分）",0); burned=c2.number_input("消費カロリー",0.0); memo=st.text_input("メモ（任意）")
        auto=st.form_submit_button("写真から読み取って登録"); add=st.form_submit_button("手入力で登録")
    if auto and photo:
        try:
            r=ai('有酸素マシンの表示写真を読取。JSONのみ: {"activity":"ランニング", "minutes":0,"calories_burned":0,"memo":"距離・速度など"}',photo)
            if not r: raise ValueError("AIキーを設定してください")
            db.table("cardio_logs").insert({"logged_date":str(selected),**r,"image_url":upload(photo),"ai_source":"AI写真読取"}).execute(); st.success("写真から登録しました。")
        except Exception as e: st.error(f"登録できませんでした: {e}")
    if add and activity:
        db.table("cardio_logs").insert({"logged_date":str(selected),"activity":activity,"minutes":minutes,"calories_burned":burned,"memo":memo,"image_url":upload(photo),"ai_source":"手入力"}).execute(); st.success("有酸素を登録しました。")

with tabs[3]:
    meals=db.table("meals").select("*").eq("logged_date",str(selected)).execute().data
    strength=db.table("strength_logs").select("*").eq("logged_date",str(selected)).execute().data
    cardio=db.table("cardio_logs").select("*").eq("logged_date",str(selected)).execute().data
    total=lambda n:sum(float(x.get(n) or 0) for x in meals)
    a,b,c,d=st.columns(4); a.metric("摂取カロリー",f"{total('calories'):.0f} kcal"); b.metric("たんぱく質",f"{total('protein'):.0f} g"); c.metric("脂質",f"{total('fat'):.0f} g"); d.metric("炭水化物",f"{total('carbs'):.0f} g")
    st.markdown("#### 食事"); st.dataframe(meals, use_container_width=True, hide_index=True)
    st.markdown("#### 筋トレ"); st.dataframe(strength, use_container_width=True, hide_index=True)
    st.markdown("#### 有酸素"); st.dataframe(cardio, use_container_width=True, hide_index=True)
