"""クラウド公開用エントリーポイント。秘密情報はStreamlit Secretsで管理する。"""
import base64, json, os
from datetime import date

import pandas as pd
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
    # 写真はAI推定にだけ使い、クラウドには保存しない。
    return None

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

def manage_records(table, rows, fields, label):
    """その日のログをアプリ内で安全に編集・削除する。"""
    st.markdown(f"#### 登録済みの{label}")
    if not rows:
        st.caption("まだ記録はありません。")
        return
    frame = pd.DataFrame(rows)
    visible = ["id", "logged_date", *fields]
    edited = st.data_editor(
        frame[visible], hide_index=True, use_container_width=True,
        column_config={"id": None, "logged_date": st.column_config.DateColumn("日付")},
        key=f"editor_{table}",
    )
    c1, c2 = st.columns(2)
    if c1.button(f"{label}の編集を保存", key=f"save_{table}"):
        for row in edited.to_dict("records"):
            payload = {}
            for field in fields:
                value = row.get(field)
                payload[field] = None if pd.isna(value) else value
            db.table(table).update(payload).eq("id", row["id"]).execute()
        st.success("編集を保存しました。")
    delete_ids = c2.multiselect(
        "削除する記録", [r["id"] for r in rows],
        format_func=lambda ident: next((f"{r.get('logged_date')} · {r.get(fields[0], '')}" for r in rows if r["id"] == ident), ident),
        key=f"delete_{table}",
    )
    if delete_ids and st.button("選んだ記録を削除", type="secondary", key=f"confirm_delete_{table}"):
        for ident in delete_ids:
            db.table(table).delete().eq("id", ident).execute()
        st.success("選んだ記録を削除しました。")
        st.rerun()

st.title("🥗 からだログ")
selected = st.sidebar.date_input("表示・登録する日", date.today())
weight_kg = st.sidebar.number_input("体重（kg・栄養目安用）", min_value=30.0, max_value=200.0, value=75.75, step=0.5)
st.sidebar.caption("写真はAI推定にのみ使い、保存しません。")
tabs = st.tabs(["🍱 食事", "🏋️ 筋トレ", "🏃 有酸素", "🧍 体組成", "📅 1日のまとめ", "📈 1か月の推移"])

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
    manage_records("meals", db.table("meals").select("*").eq("logged_date", str(selected)).execute().data,
                   ["memo", "estimated_items", "calories", "protein", "fat", "carbs", "advice"], "食事ログ")

with tabs[1]:
    with st.form("strength", clear_on_submit=True):
        exercise=st.text_input("種目"); c1,c2,c3=st.columns(3); weight=c1.number_input("重量 (kg)",0.0); reps=c2.number_input("回数",0); sets=c3.number_input("セット数",0); memo=st.text_input("メモ（任意）")
        add=st.form_submit_button("筋トレを登録")
    if add and exercise:
        db.table("strength_logs").insert({"logged_date":str(selected),"exercise":exercise,"weight":weight,"reps":reps,"sets":sets,"memo":memo}).execute(); st.success("筋トレを登録しました。")
    manage_records("strength_logs", db.table("strength_logs").select("*").eq("logged_date", str(selected)).execute().data,
                   ["exercise", "weight", "reps", "sets", "memo"], "筋トレログ")

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
    manage_records("cardio_logs", db.table("cardio_logs").select("*").eq("logged_date", str(selected)).execute().data,
                   ["activity", "minutes", "calories_burned", "memo"], "有酸素ログ")

with tabs[3]:
    st.subheader("体組成を登録")
    st.caption("体組成計の表示を見ながら記録します。数値は医療診断ではなく、日々の変化を見るための目安です。")
    with st.form("body_metrics", clear_on_submit=True):
        a,b,c = st.columns(3)
        weight = a.number_input("体重 (kg)", min_value=0.0, step=0.05, value=float(weight_kg))
        bmi = b.number_input("BMI", min_value=0.0, step=0.1)
        body_fat = c.number_input("体脂肪率 (%)", min_value=0.0, step=0.1)
        a,b,c = st.columns(3)
        fat_mass = a.number_input("体脂肪量 (kg)", min_value=0.0, step=0.05)
        visceral = b.number_input("内臓脂肪指数", min_value=0.0, step=1.0)
        muscle = c.number_input("骨格筋量 (kg)", min_value=0.0, step=0.05)
        a,b,c = st.columns(3)
        bone = a.number_input("推定骨量 (kg)", min_value=0.0, step=0.05)
        water = b.number_input("水分量 (kg)", min_value=0.0, step=0.05)
        bmr = c.number_input("基礎代謝量 (kcal)", min_value=0.0, step=10.0)
        a,b = st.columns(2)
        lean = a.number_input("四肢の除脂肪量 (kg)", min_value=0.0, step=0.05)
        smi = b.number_input("SMI (kg/m²)", min_value=0.0, step=0.1)
        memo = st.text_input("メモ（任意）")
        add = st.form_submit_button("体組成を登録")
    if add:
        row = {"logged_date":str(selected),"weight":weight,"bmi":bmi,"body_fat_percentage":body_fat,"body_fat_mass":fat_mass,"visceral_fat_index":visceral,"skeletal_muscle_mass":muscle,"estimated_bone_mass":bone,"body_water_mass":water,"basal_metabolic_rate":bmr,"appendicular_lean_mass":lean,"smi":smi,"memo":memo}
        db.table("body_metrics").upsert(row, on_conflict="logged_date").execute()
        st.success("体組成を登録しました。")
    manage_records("body_metrics", db.table("body_metrics").select("*").eq("logged_date", str(selected)).execute().data,
                   ["weight", "bmi", "body_fat_percentage", "body_fat_mass", "visceral_fat_index", "skeletal_muscle_mass", "estimated_bone_mass", "body_water_mass", "basal_metabolic_rate", "appendicular_lean_mass", "smi", "memo"], "体組成ログ")

with tabs[4]:
    meals=db.table("meals").select("*").eq("logged_date",str(selected)).execute().data
    strength=db.table("strength_logs").select("*").eq("logged_date",str(selected)).execute().data
    cardio=db.table("cardio_logs").select("*").eq("logged_date",str(selected)).execute().data
    total=lambda n:sum(float(x.get(n) or 0) for x in meals)
    a,b,c,d=st.columns(4); a.metric("摂取カロリー",f"{total('calories'):.0f} kcal"); b.metric("たんぱく質",f"{total('protein'):.0f} g"); c.metric("脂質",f"{total('fat'):.0f} g"); d.metric("炭水化物",f"{total('carbs'):.0f} g")
    st.markdown("#### 食事"); st.dataframe(meals, use_container_width=True, hide_index=True)
    st.markdown("#### 筋トレ"); st.dataframe(strength, use_container_width=True, hide_index=True)
    st.markdown("#### 有酸素"); st.dataframe(cardio, use_container_width=True, hide_index=True)

    st.markdown("#### 栄養バランスの目安")
    protein_target = weight_kg * 1.6
    protein = total("protein")
    fat, carbs = total("fat"), total("carbs")
    if not meals:
        st.info("食事を登録すると、その日の栄養バランスを確認できます。")
    else:
        if protein < protein_target * 0.7:
            st.warning(f"たんぱく質が少なめです。目安は約 {protein_target:.0f}g、今日は {protein:.0f}g。鶏肉・魚・卵・豆腐・ヨーグルトなどを1品足してみましょう。")
        else:
            st.success(f"たんぱく質は {protein:.0f}g。目安の約 {protein_target:.0f}g に近づいています。")
        if fat > 70:
            st.info("脂質が多めの傾向です。揚げ物や菓子を続けず、次の食事は魚・野菜中心にすると整えやすいです。")
        if carbs < 100 and total("calories") < 1200:
            st.info("総摂取量が少なめです。トレーニング日なら主食や果物も適量足すと、回復しやすくなります。")
        st.caption("これは食事写真からの概算PFCに基づく目安です。ビタミン・ミネラルを正確に判定するには、食材量の詳細な記録が必要です。")

with tabs[5]:
    month_start = selected.replace(day=1)
    if month_start.month == 12:
        next_month = month_start.replace(year=month_start.year + 1, month=1)
    else:
        next_month = month_start.replace(month=month_start.month + 1)
    month_meals = db.table("meals").select("logged_date,calories,protein,fat,carbs").gte("logged_date", str(month_start)).lt("logged_date", str(next_month)).execute().data
    month_body = db.table("body_metrics").select("logged_date,weight,body_fat_percentage,skeletal_muscle_mass").gte("logged_date", str(month_start)).lt("logged_date", str(next_month)).execute().data
    st.subheader(f"{selected.strftime('%Y年%m月')}の推移")
    if not month_meals:
        st.info("この月の食事ログはまだありません。")
    else:
        trend = pd.DataFrame(month_meals)
        trend["logged_date"] = pd.to_datetime(trend["logged_date"])
        for col in ["calories", "protein", "fat", "carbs"]:
            trend[col] = pd.to_numeric(trend[col], errors="coerce").fillna(0)
        daily = trend.groupby("logged_date")[["calories", "protein", "fat", "carbs"]].sum().sort_index()
        st.line_chart(daily[["calories"]], y_label="kcal")
        st.line_chart(daily[["protein", "fat", "carbs"]], y_label="g")
        c1,c2,c3,c4 = st.columns(4)
        c1.metric("月間カロリー", f"{daily['calories'].sum():.0f} kcal")
        c2.metric("平均たんぱく質", f"{daily['protein'].mean():.0f} g/記録日")
        c3.metric("記録日数", f"{len(daily)} 日")
        c4.metric("平均カロリー", f"{daily['calories'].mean():.0f} kcal/記録日")
    if month_body:
        st.markdown("#### 体組成の推移")
        body = pd.DataFrame(month_body)
        body["logged_date"] = pd.to_datetime(body["logged_date"])
        body = body.set_index("logged_date").sort_index()
        st.line_chart(body[["weight", "body_fat_percentage", "skeletal_muscle_mass"]], y_label="kg / %")
