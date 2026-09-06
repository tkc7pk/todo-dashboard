# CLAUDE.md — todo-dashboard

このリポジトリは「Claude Code プロジェクト横断 TODO ダッシュボード」(`todo_dashboard.py`) の
ソース管理・改善用です。Claude Code はこのファイルを最初に読み、以下のルールに従って作業してください。

---

## 1. このツールは何か

`F:\claude` 配下の各プロジェクトにある `TODO.md` を**正本(source of truth)**として横断スキャンし、
ブラウザ上で優先度順の一覧・チェック・優先度変更・並べ替え・追加・削除を行い、
変更をそのまま各 `TODO.md` に書き戻すローカルツール。

- 単一ファイル `todo_dashboard.py`。HTML/CSS/JS はその中に文字列として埋め込み。
- **Python標準ライブラリのみ**（`http.server` / `argparse` / `pathlib` / `re` / `json` / `threading` / `webbrowser`）。
- DB なし。状態はすべて `TODO.md` 側にある。
- トップは**プロジェクト概要ビュー**（カード一覧：進捗率・未完了件数・P1件数・期限切れ件数・ゴール）。
  カードをクリックするとそのプロジェクトのタスク詳細（従来の優先度別ボード）へドリルダウンする。
  ヘッダーの `[概要] [タスク]` セグメントと `location.hash`（`#/overview` / `#/p/<project>`）で状態を保持する。
- `--root` 直下（サブディレクトリでない）にある `TODO.md` は「全体 TODO」として扱い、`is_root: true` が付き、
  概要ビューの先頭に全幅で固定表示される。どのプロジェクトにも属さない横断タスクをここに書く。

## 2. 起動方法

```
python todo_dashboard.py --root F:\claude        # F:\claude を起点にスキャン
python todo_dashboard.py --port 8765 --no-browser
```

| 引数 | 既定値 | 意味 |
|------|--------|------|
| `--root` | `.` | スキャン起点 |
| `--port` | `8765` | 待受ポート |
| `--host` | `127.0.0.1` | 待受アドレス（ローカル限定） |
| `--no-browser` | off | ブラウザ自動起動を抑止 |
| `--notify` | off | TODOサマリーをDiscordに送信して終了（サーバーは起動しない） |
| `--discord-webhook` | — | Discord Webhook URL（省略時は `DISCORD_WEBHOOK` 環境変数） |
| `--require-cf-access` | off | `Cf-Access-Jwt-Assertion` ヘッダーが無いリクエストを403で拒否する（Cloudflare Tunnel経由で外部公開する場合に指定。ローカル利用時は付けない） |

`http://127.0.0.1:8765/` で UI が開く。`Ctrl+C` で停止。

### Discord通知モード

```
# 環境変数で指定（推奨）
$env:DISCORD_WEBHOOK = "https://discord.com/api/webhooks/..."
python todo_dashboard.py --root F:\claude --notify

# またはバッチファイルで実行（Windowsタスクスケジューラ登録用）
F:\claude\todo-dashboard\notify.bat
```

`--notify` を指定すると HTTPサーバーを起動せずにDiscordに送信して終了する。
通知内容: P1/P2タスク詳細（最大5件ずつ）＋P3/P4/未設定の件数＋統計。

**Discord通知フォーマット**:
```
📋 **TODO Dashboard** — 2026-06-14
────────────────────────────────
🔴 **P1** (2件)
  • ideaposting: Supabaseスキーマを本番DBに適用
  • crypto_trading_bot: bitFlyer API接続テスト ⏰2026-06-20
🟠 **P2** (3件)
  • ...
🟡 **P3** (5件)
🔵 **P4** (2件)

📊 合計: 15件 | 完了: 8件 | 未完了: 7件
```

**セキュリティ**: Webhook URL はシステム環境変数 `DISCORD_WEBHOOK` に格納し、
コマンド引数や `notify.bat` に直書きしないこと。

## 3. TODO.md の書式（パーサが解釈する規約）

```markdown
---
project: 表示名            # 省略時はフォルダ名
priority: P1               # 省略可。P1〜P4。UI から変更可能
goal: プロジェクトのゴール   # 省略可。改行不可・200文字以内。概要カードでインライン編集可能
---
- [ ] (P1) タスク内容 <!-- due:2026-06-20 -->
- [x] (P3) 完了タスク
- [ ] 優先度なしタスク
```

- タスク行: 行頭の `- ` / `* ` / `+ ` ＋ `[ ]` または `[x]`。インデント（ネスト）は保持される。
- 優先度: チェックボックス直後の `(P1)`〜`(P4)`。無い場合は「未設定」グループ。
- 期限: `<!-- due:YYYY-MM-DD -->`。期限超過は UI で赤表示。
- フロントマターの `project:` が無ければ、その `TODO.md` の**親フォルダ名**を表示名にする。
- フロントマターの `goal:` はプロジェクト概要カードに表示される一行ゴール。無くてもよい。
- `is_root`（`scan` の内部計算値。フロントマターには書かない）: その `TODO.md` が `--root` 直下にあるかどうか。
  `true` のプロジェクトは「全体 TODO」として概要ビューの先頭に全幅で固定表示される。
- `TODO_ANALYSIS.md` があれば UI 下部にClaudeの優先度提案として折りたたみ表示する。

パースとフォーマットは `parse_task_line` / `format_task_line` が対。
**この2つは常にラウンドトリップ可逆**であること（既存の書式を壊さない）が最重要の不変条件。

## 4. アーキテクチャ / 主要関数

- スキャン: `iter_todo_files` → `scan`。`IGNORE_DIRS`（`node_modules` `.git` `.venv` 等）と
  ドット始まりフォルダは除外。再帰探索。
  - `projects[]` の各要素は `{project, file, rel, priority, goal, is_root, stats}`。
    `stats` は `{total, open, done, p1, p2, p3, p4, none, overdue}`（`_empty_stats()` / `_tally()` で計算）。
    同名プロジェクトが複数ファイルにまたがる場合は名前で合算する。
  - `projects` の順序は `_project_sort_key`（`is_root` 優先 → `priority`（未設定は最後） → 名前）でソートされる。
  - `tasks[]` の各要素には `indent` / `bullet` も含まれる（JS の `buildRaw` がラウンドトリップを保つために使用）。
  - 全体 `stats`（トップレベル）も同じ `_empty_stats()` 形式（`total` / `overdue` を含む）。
- HTTP: `Handler`（`ThreadingHTTPServer`）。
  - `GET /` … 埋め込み HTML (`PAGE`) を返す
  - `GET /api/scan` … `{root, projects, tasks, analysis, stats}` を返す
  - `POST /api/update` … `{file, old_raw, new_raw}` で1行を置換
  - `POST /api/delete` … `{file, old_raw}` で1行を削除
  - `POST /api/add` … `{file, text, priority}` で末尾に1行追加
  - `POST /api/update-project` … `{file, priority}` でフロントマターの `priority:` を更新
  - `POST /api/update-project-goal` … `{file, goal}` でフロントマターの `goal:` を更新（空文字で削除）
- フロントマター書き込みの共通処理: `_update_frontmatter_field(file_str, key, value)`。
  `update_project_priority` と `update_project_goal` はいずれもこの薄いラッパー。
- 書き戻しの同定方式: **行番号ではなく `old_raw` の完全一致**で対象行を探す（インデックスずれに強い）。
  元の行が見つからなければ保存せずエラーを返し、UI 側は再読込を促す。
- 改行コード（CRLF/LF）は元の行のものを維持する。

## 5. セキュリティ上の不変条件（緩めないこと）

- `--host` の既定は `127.0.0.1`。**アプリ自体はローカル限定のまま**で、`0.0.0.0` 等への
  バインドをコードで行わない。外部公開が必要な場合はアプリを変更するのではなく、
  実行環境側で **Cloudflare Tunnel**（PC上で常駐する `cloudflared`）を `127.0.0.1:8765` に
  向けて立て、**Cloudflare Access**（メールOTP・本人のみ許可）でエッジ側の認証をかける運用とする
  （2026-08-20〜 `todo.naozi.jp` で運用）。
- `--require-cf-access` を指定したときだけ、`Cf-Access-Jwt-Assertion` ヘッダーの**存在チェック**
  （`cf_access_ok`）で 403 を返す。これは署名検証を伴う本物の認証ではなく、Tunnel を経由しない
  誤アクセスを弾く保険にすぎない。実際の認証は Cloudflare Access 側で完結している前提。
- 書き込みは `_check_target` を必ず通す: 対象は `--root` 配下、かつファイル名が `todo.md`（大小無視）に限る。
  この2条件をどんな改修でも外さない。
- ユーザ入力（タスク本文・パス）を `eval` 等に渡さない。HTML 出力は `esc()` でエスケープ済み。

## 6. Claude Code への作業ルール

- **依存追加は原則禁止**。「インストール不要の単一ファイル」が本ツールの価値。外部ライブラリを足したくなったら、
  まず理由と代替（標準ライブラリで可能か）を提示して合意を取る。
  （Discord通知は `urllib.request` で実装済み。stdlib のみで外部通信を実現している）
- 変更は `feature/<topic>` ブランチで行い、小さい単位でコミットする。コミットメッセージは命令形・1行サマリ＋必要なら本文。
- **コミット前チェック**（最低限のスモークテスト）:
  ```
  # 構文チェック
  python -c "import ast,sys; ast.parse(open('todo_dashboard.py',encoding='utf-8').read()); print('syntax OK')"
  # ユニットテスト（parse/format ラウンドトリップ・update/delete/add・_check_target ガード）
  python -m unittest discover -s tests -v
  ```
  `tests/test_dashboard.py` が §3 の3パターン（優先度＋期限あり / ネスト＋完了 / 優先度なし）や
  `goal:` の読み書き・`scan` のプロジェクト集計を含む53ケースをカバーしている（2026-09時点）。
  パーサや書き込み関数を触ったら必ずテストを通すこと。
- 仕様（§2〜§5）を変えたら、**この CLAUDE.md を同じコミットで更新**する。ドキュメントと実装を乖離させない。
- 大きめの変更後は `/security-review` を実行して書き込みガード・入力エスケープの退行がないか確認する。
- このプロジェクトの TODO は `TODO.md`（プロジェクトルート直下）に記録する。タスクの追加・更新・完了チェックはすべて `TODO.md` に書き込む（`todo-dashboard` 自身で一元管理）。着手前にユーザへ優先度の確認を取る。

## 7. やらないこと

- 認証・アカウント作成・権限変更・課金は実装しない（ローカル個人ツールの範囲を超える。
  Cloudflare Access 等エッジ層の認証と組み合わせる運用は可。`cf_access_ok` のヘッダー
  存在チェックは認証の代替ではなく、Tunnel 経由以外からの誤アクセスを防ぐ保険）。
- `--notify` の自動実行トリガーをスクリプト内に組み込まない（スケジューリングはOS側＝タスクスケジューラが担う）。
- `TODO.md` 以外のファイルへの書き込み機能を追加しない。
