"""クラウド公開用エントリーポイント。秘密情報はStreamlit Secretsで管理する。"""
import base64, hashlib, json, os
from datetime import date, datetime, timedelta, timezone

import pandas as pd
import streamlit as st
from supabase import create_client

st.set_page_config(page_title="からだログ", page_icon="🥗", layout="wide")
st.markdown("""
<style>
.macro-grid { display:grid; grid-template-columns:repeat(2, minmax(0, 1fr)); gap:12px; margin:12px 0 18px; }
.macro-card { border:1px solid; border-radius:18px; padding:15px 14px 13px; min-height:136px; }
.macro-card.below { background:rgba(151, 205, 243, .34); border-color:rgba(186, 224, 248, .72); }
.macro-card.over { background:rgba(245, 166, 180, .34); border-color:rgba(255, 202, 210, .72); }
.macro-name { font-size:.88rem; font-weight:700; opacity:.9; }
.macro-value { font-size:1.65rem; line-height:1.2; font-weight:800; margin:12px 0 8px; letter-spacing:-.03em; }
.macro-target, .macro-diff { font-size:.78rem; opacity:.86; }
.macro-diff { margin-top:4px; font-weight:700; }
@media (max-width: 420px) { .macro-grid { gap:9px; } .macro-card { padding:13px 12px; min-height:128px; } .macro-value { font-size:1.45rem; } }
</style>
""", unsafe_allow_html=True)

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
    raw = OpenAI(api_key=api_key).responses.create(model=secret("OPENAI_MODEL") or "gpt-4.1-mini", input=[{"role":"user","content":content}], max_output_tokens=350).output_text
    return json.loads(raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip())

def health_chat(question, context):
    """診断をせず、記録に基づく生活改善の相談に答える。"""
    from openai import OpenAI
    client = OpenAI(api_key=secret("OPENAI_API_KEY"))
    prompt = f"""あなたは日本語の健康習慣コーチです。診断・薬の服用指示・治療の断定はしません。
記録を踏まえ、食事・水分・休養・運動調整について、今日できる具体的な提案を短く答えてください。
サプリは食事で補えない場合の候補としてのみ示し、服薬・持病・妊娠中の場合は医師または薬剤師への確認を促してください。
胸痛、強い息苦しさ、意識障害、片側の麻痺、突然の激しい頭痛、自傷の危険が示唆される場合は、回答の最初に緊急受診・地域の緊急連絡先への相談を促してください。

今日の記録: {json.dumps(context, ensure_ascii=False, default=str)}
相談: {question}"""
    return client.responses.create(model=secret("OPENAI_MODEL") or "gpt-4.1-mini", input=prompt, max_output_tokens=600).output_text

def nutrition_coach(context, goal, notes):
    from openai import OpenAI
    prompt = f"""あなたは日本語の栄養コーチです。食事記録は写真AIによる概算であり、診断はしません。
目標: {goal}。避けたい食材・補足: {notes or 'なし'}。
目標が「アンチエイジング＋脂肪を落とす」の場合は、筋肉維持のたんぱく質、食物繊維、オメガ3、カルシウム、鉄、マグネシウム、亜鉛、ビタミンA/C/D、葉酸を優先し、極端な低カロリーや過度なサプリ依存を勧めないでください。
食事内容から、食物繊維、鉄、カルシウム、カリウム、マグネシウム、亜鉛、ビタミンA/C/D/葉酸/B12、オメガ3、塩分について「不足・過多の可能性」を慎重に推定してください。
複数日分の記録がある場合は、単日の不足ではなく、繰り返し不足・過多になっている傾向を優先してください。記録から判断できない栄養素は「不明」と明記してください。
次のJSONだけを返してください。配列は最大3件、説明は1文ずつにしてください。
{{"headline":"今日の要点", "deficiencies":[{{"nutrient":"栄養素", "reason":"理由"}}], "next_meal":{{"title":"次の一食", "items":["料理・食材"]}}, "drink_snack":["飲み物・間食"], "supplements":["必要な場合のみの候補"], "avoid":["控えめにしたいもの"], "note":"注意書き"}}
記録: {json.dumps(context, ensure_ascii=False, default=str)}"""
    raw = OpenAI(api_key=secret("OPENAI_API_KEY")).responses.create(
        model=secret("OPENAI_MODEL") or "gpt-4.1-mini", input=prompt, max_output_tokens=650
    ).output_text.strip()
    raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    return json.loads(raw)

def cached_analysis(kind, analysis_date, context, make_analysis):
    """同じ食事内容には再課金せず、保存済みのAI分析を再利用する。"""
    digest = hashlib.sha256(json.dumps(context, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()
    cached = db.table("analysis_cache").select("input_hash,content,created_at").eq("kind", kind).eq("analysis_date", str(analysis_date)).limit(1).execute().data
    if cached:
        created = pd.to_datetime(cached[0]["created_at"], utc=True).to_pydatetime()
        still_fresh = datetime.now(timezone.utc) - created < timedelta(hours=12)
        if cached[0]["input_hash"] == digest or still_fresh:
            return json.loads(cached[0]["content"]), False
    content = make_analysis()
    db.table("analysis_cache").upsert({"kind":kind, "analysis_date":str(analysis_date), "input_hash":digest, "content":json.dumps(content, ensure_ascii=False)}, on_conflict="kind,analysis_date").execute()
    return content, True

def render_coach_card(title, advice):
    st.markdown(f"##### {title}")
    st.caption(advice.get("headline", "食事記録をもとにした目安です。"))
    left, right = st.columns(2)
    with left:
        with st.container(border=True):
            st.markdown("**不足しやすい栄養**")
            for item in advice.get("deficiencies", []):
                st.markdown(f"**{item.get('nutrient', '')}**  ")
                st.caption(item.get("reason", ""))
    with right:
        with st.container(border=True):
            meal = advice.get("next_meal", {})
            st.markdown(f"**🍽 {meal.get('title', '次の一食')}**")
            for item in meal.get("items", []):
                st.write(f"• {item}")
    c1, c2 = st.columns(2)
    with c1:
        with st.container(border=True):
            st.markdown("**🥤 飲み物・間食**")
            for item in advice.get("drink_snack", []): st.write(f"• {item}")
    with c2:
        with st.container(border=True):
            st.markdown("**🌿 サプリは必要な場合だけ**")
            for item in advice.get("supplements", []): st.write(f"• {item}")
    if advice.get("avoid"):
        st.caption("控えめに：" + " / ".join(advice["avoid"]))
    if advice.get("note"):
        st.caption(advice["note"])

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
        column_config={"id": None, "logged_date": "日付"},
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
goal = st.sidebar.selectbox("目標", ["アンチエイジング＋脂肪を落とす", "脂肪を落とす", "体調・体重を維持", "筋肉を増やす", "運動パフォーマンスを上げる"])
diet_notes = st.sidebar.text_input("避けたい食材・補足（任意）", placeholder="例：乳製品が苦手")
st.sidebar.caption("写真はAI推定にのみ使い、保存しません。")
tabs = st.tabs(["🍱 食事", "🏋️ 筋トレ", "🏃 有酸素", "🧍 体組成", "💬 体の相談", "📅 1日のまとめ", "📈 1か月の推移"])

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
    st.subheader("体の相談")
    st.caption("今日の食事・運動・体組成を参考に、生活習慣の提案を受けられます。診断や緊急対応の代わりにはなりません。")
    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []
    for item in st.session_state.chat_history:
        with st.chat_message(item["role"]):
            st.write(item["content"])
    question = st.chat_input("例：今日はだるい。次に何を食べればいい？")
    if question:
        st.session_state.chat_history.append({"role":"user", "content":question})
        with st.chat_message("user"):
            st.write(question)
        urgent_words = ["胸痛", "息苦しい", "意識がない", "ろれつ", "片麻痺", "死にたい", "自殺"]
        if any(word in question for word in urgent_words):
            answer = "緊急性のある症状の可能性があります。AI相談を続けず、地域の救急窓口・医療機関へすぐ相談してください。"
        else:
            context = {
                "date": str(selected),
                "meals": db.table("meals").select("estimated_items,calories,protein,fat,carbs,memo").eq("logged_date",str(selected)).execute().data,
                "strength": db.table("strength_logs").select("exercise,weight,reps,sets,memo").eq("logged_date",str(selected)).execute().data,
                "cardio": db.table("cardio_logs").select("activity,minutes,calories_burned,memo").eq("logged_date",str(selected)).execute().data,
                "body": db.table("body_metrics").select("weight,body_fat_percentage,skeletal_muscle_mass,basal_metabolic_rate").eq("logged_date",str(selected)).execute().data,
            }
            try:
                answer = health_chat(question, context)
            except Exception as exc:
                answer = f"相談機能を使えませんでした: {exc}"
        st.session_state.chat_history.append({"role":"assistant", "content":answer})
        with st.chat_message("assistant"):
            st.write(answer)
    if st.session_state.chat_history and st.button("この画面の相談履歴を消す"):
        st.session_state.chat_history = []
        st.rerun()

with tabs[5]:
    meals=db.table("meals").select("*").eq("logged_date",str(selected)).execute().data
    strength=db.table("strength_logs").select("*").eq("logged_date",str(selected)).execute().data
    cardio=db.table("cardio_logs").select("*").eq("logged_date",str(selected)).execute().data
    total=lambda n:sum(float(x.get(n) or 0) for x in meals)
    latest_body = db.table("body_metrics").select("*").lte("logged_date", str(selected)).order("logged_date", desc=True).limit(1).execute().data
    body = latest_body[0] if latest_body else {}
    bmr = float(body.get("basal_metabolic_rate") or weight_kg * 22)
    week_start = selected - timedelta(days=6)
    week_meals = db.table("meals").select("logged_date,estimated_items,calories,protein,fat,carbs,memo").gte("logged_date", str(week_start)).lte("logged_date", str(selected)).execute().data
    week_dates = {row["logged_date"] for row in week_meals}
    week_days = len(week_dates)
    month_start = selected - timedelta(days=29)
    month_meals_for_advice = db.table("meals").select("logged_date,estimated_items,calories,protein,fat,carbs,memo").gte("logged_date", str(month_start)).lte("logged_date", str(selected)).execute().data
    month_days_for_advice = len({row["logged_date"] for row in month_meals_for_advice})
    cardio_burned = sum(float(x.get("calories_burned") or 0) for x in cardio)
    strength_bonus = len(strength) * 150
    if goal in ["アンチエイジング＋脂肪を落とす", "脂肪を落とす"]:
        # まず休養日の目安を出し、登録済みの運動分だけ追加する。
        rest_day_target = max(bmr * 1.05, bmr * 1.20 - 300)
        # 直近の記録が3日以上あるときだけ、平均の過不足を穏やかに帳尻合わせする。
        week_avg_calories = sum(float(row.get("calories") or 0) for row in week_meals) / week_days if week_days else 0
        weekly_adjustment = max(-150, min(150, -(week_avg_calories - rest_day_target) * 0.35)) if week_days >= 3 else 0
        calorie_target = rest_day_target + cardio_burned + strength_bonus + weekly_adjustment
        protein_target, fat_target = weight_kg * 1.6, weight_kg * 0.8
    elif goal == "筋肉を増やす":
        calorie_target = bmr * 1.4 + cardio_burned + strength_bonus + 200
        protein_target, fat_target = weight_kg * 1.8, weight_kg * 0.9
    else:
        calorie_target = bmr * 1.4 + cardio_burned + strength_bonus
        protein_target, fat_target = weight_kg * 1.6, weight_kg * 0.8
    carb_target = max(0, (calorie_target - protein_target * 4 - fat_target * 9) / 4)
    macros = [
        ("摂取カロリー", total("calories"), calorie_target, "kcal"),
        ("たんぱく質", total("protein"), protein_target, "g"),
        ("脂質", total("fat"), fat_target, "g"),
        ("炭水化物", total("carbs"), carb_target, "g"),
    ]
    cards = "".join(
        f'''<div class="macro-card {'over' if current > target else 'below'}">
        <div class="macro-name">{name}</div><div class="macro-value">{current:.0f} {unit}</div>
        <div class="macro-target">目安 {target:.0f} {unit}</div>
        <div class="macro-diff">差分 {current-target:+.0f} {unit}</div></div>'''
        for name, current, target, unit in macros
    )
    st.markdown(f'<div class="macro-grid">{cards}</div>', unsafe_allow_html=True)
    activity_note = "休養日" if not cardio and not strength else f"有酸素 +{cardio_burned:.0f} kcal / 筋トレ +{strength_bonus:.0f} kcal"
    weekly_note = f"直近{week_days}記録日の帳尻調整 {weekly_adjustment:+.0f} kcal" if goal in ["アンチエイジング＋脂肪を落とす", "脂肪を落とす"] and week_days >= 3 else "直近の記録が3日未満のため、帳尻調整なし"
    st.caption(f"目標：{goal}　/　{activity_note}　/　{weekly_note}　/　差分は「現在 − 目安」（マイナス＝不足、プラス＝目安超え）")
    st.markdown("#### アンチエイジングゾーン")
    st.caption(f"直近7日：食事ログ {week_days} 日。直近30日：食事ログ {month_days_for_advice} 日。分析は食事内容が変わった場合でも最大12時間に1回だけ更新されます。")
    if week_meals or month_meals_for_advice:
        try:
            week_scope = selected - timedelta(days=selected.weekday())
            week_context = {"window":"直近7日", "meals":week_meals, "log_days":week_days, "body":body, "goal":goal}
            month_scope = selected.replace(day=1)
            month_context = {"window":"直近30日", "meals":month_meals_for_advice, "log_days":month_days_for_advice, "body":body, "goal":goal}
            with st.spinner("栄養傾向を確認中..."):
                week_advice, _ = cached_analysis("antiaging_week_v2", week_scope, week_context, lambda: nutrition_coach(week_context, goal, diet_notes)) if week_meals else (None, False)
                month_advice, _ = cached_analysis("antiaging_month_v2", month_scope, month_context, lambda: nutrition_coach(month_context, goal, diet_notes)) if month_meals_for_advice else (None, False)
            if week_advice:
                render_coach_card("直近7日の傾向", week_advice)
            if month_advice:
                render_coach_card("直近30日の傾向", month_advice)
        except Exception as exc:
            st.warning(f"栄養傾向をまだ表示できません: {exc}")
    targets = pd.DataFrame([
        {"栄養素":"カロリー", "目安":f"{calorie_target:.0f} kcal", "現在":f"{total('calories'):.0f} kcal", "差分（現在−目安）":f"{total('calories')-calorie_target:+.0f} kcal"},
        {"栄養素":"たんぱく質", "目安":f"{protein_target:.0f} g", "現在":f"{total('protein'):.0f} g", "差分（現在−目安）":f"{total('protein')-protein_target:+.0f} g"},
        {"栄養素":"脂質", "目安":f"{fat_target:.0f} g", "現在":f"{total('fat'):.0f} g", "差分（現在−目安）":f"{total('fat')-fat_target:+.0f} g"},
        {"栄養素":"炭水化物", "目安":f"{carb_target:.0f} g", "現在":f"{total('carbs'):.0f} g", "差分（現在−目安）":f"{total('carbs')-carb_target:+.0f} g"},
    ])
    st.markdown("#### 今日の目安と差分")
    st.dataframe(targets, use_container_width=True, hide_index=True)
    st.caption("休養日は休養日の目安だけを表示し、運動ログを登録した日だけ有酸素の消費分と筋トレの回復分を上乗せします。")
    st.markdown("#### 食事")
    if meals:
        st.dataframe(pd.DataFrame(meals)[["estimated_items", "calories", "protein", "fat", "carbs", "memo"]].rename(columns={"estimated_items":"内容","calories":"kcal","protein":"P(g)","fat":"F(g)","carbs":"C(g)","memo":"メモ"}), use_container_width=True, hide_index=True)
    st.markdown("#### 筋トレ")
    if strength:
        st.dataframe(pd.DataFrame(strength)[["exercise", "weight", "reps", "sets", "memo"]].rename(columns={"exercise":"種目","weight":"重量(kg)","reps":"回数","sets":"セット","memo":"メモ"}), use_container_width=True, hide_index=True)
    st.markdown("#### 有酸素")
    if cardio:
        st.dataframe(pd.DataFrame(cardio)[["activity", "minutes", "calories_burned", "memo"]].rename(columns={"activity":"種目","minutes":"時間(分)","calories_burned":"消費(kcal)","memo":"メモ"}), use_container_width=True, hide_index=True)

    st.markdown("#### 栄養バランスの目安")
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

with tabs[6]:
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
