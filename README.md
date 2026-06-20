# からだログ MVP

食事・筋トレ・有酸素運動を、PC上のSQLiteデータベースに記録する小さな健康管理アプリです。食事写真とメモをもとに、AIがカロリーとPFC（たんぱく質・脂質・炭水化物）を概算します。

有酸素運動は、ランニングマシンの画面写真から時間・消費カロリー・距離などを読み取り、ログとして登録することもできます（AI機能を有効にした場合）。

## 起動方法

1. Python 3.10以降をインストールします。
2. このフォルダをターミナルで開き、次を実行します。

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
py -m pip install -r requirements.txt
streamlit run app.py
```

ブラウザで `http://localhost:8501` が開きます。終了はターミナルで `Ctrl+C` です。

PowerShellで仮想環境の実行が拒否された場合は、次のコマンドを一度だけ実行してから、もう一度有効化してください。

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

## AI食事推定を有効にする（任意）

OpenAI APIキーを設定すると、写真とメモを使った推定になります。設定しなくてもアプリは起動し、デモ推定で一連の操作を試せます。

```powershell
$env:OPENAI_API_KEY = "あなたのAPIキー"
streamlit run app.py
```

必要ならモデルも変更できます。

```powershell
$env:OPENAI_MODEL = "gpt-4.1-mini"
```

## 保存場所

- `health.db`: 登録した食事・運動データ
- `uploads/`: アップロードした食事写真

どちらもアプリと同じフォルダに作られます。推定値は目安であり、医療・栄養指導の代わりにはなりません。
