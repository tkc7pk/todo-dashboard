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

`http://127.0.0.1:8765/` で UI が開く。`Ctrl+C` で停止。

## 3. TODO.md の書式（パーサが解釈する規約）

```markdown
---
project: 表示名            # 省略時はフォルダ名
priority: P1               # 省略可。P1〜P4。UI から変更可能
---
- [ ] (P1) タスク内容 <!-- due:2026-06-20 -->
- [x] (P3) 完了タスク
- [ ] 優先度なしタスク
```

- タスク行: 行頭の `- ` / `* ` / `+ ` ＋ `[ ]` または `[x]`。インデント（ネスト）は保持される。
- 優先度: チェックボックス直後の `(P1)`〜`(P4)`。無い場合は「未設定」グループ。
- 期限: `<!-- due:YYYY-MM-DD -->`。期限超過は UI で赤表示。
- フロントマターの `project:` が無ければ、その `TODO.md` の**親フォルダ名**を表示名にする。
- `TODO_ANALYSIS.md` があれば UI 下部にClaudeの優先度提案として折りたたみ表示する。

パースとフォーマットは `parse_task_line` / `format_task_line` が対。
**この2つは常にラウンドトリップ可逆**であること（既存の書式を壊さない）が最重要の不変条件。

## 4. アーキテクチャ / 主要関数

- スキャン: `iter_todo_files` → `scan`。`IGNORE_DIRS`（`node_modules` `.git` `.venv` 等）と
  ドット始まりフォルダは除外。再帰探索。
- HTTP: `Handler`（`ThreadingHTTPServer`）。
  - `GET /` … 埋め込み HTML (`PAGE`) を返す
  - `GET /api/scan` … `{root, projects, tasks, analysis, stats}` を返す
  - `POST /api/update` … `{file, old_raw, new_raw}` で1行を置換
  - `POST /api/delete` … `{file, old_raw}` で1行を削除
  - `POST /api/add` … `{file, text, priority}` で末尾に1行追加
  - `POST /api/update-project` … `{file, priority}` でフロントマターの `priority:` を更新
- 書き戻しの同定方式: **行番号ではなく `old_raw` の完全一致**で対象行を探す（インデックスずれに強い）。
  元の行が見つからなければ保存せずエラーを返し、UI 側は再読込を促す。
- 改行コード（CRLF/LF）は元の行のものを維持する。

## 5. セキュリティ上の不変条件（緩めないこと）

- `--host` の既定は `127.0.0.1`。**外部公開しない**。
- 書き込みは `_check_target` を必ず通す: 対象は `--root` 配下、かつファイル名が `todo.md`（大小無視）に限る。
  この2条件をどんな改修でも外さない。
- ユーザ入力（タスク本文・パス）を `eval` 等に渡さない。HTML 出力は `esc()` でエスケープ済み。

## 6. Claude Code への作業ルール

- **依存追加は原則禁止**。「インストール不要の単一ファイル」が本ツールの価値。外部ライブラリを足したくなったら、
  まず理由と代替（標準ライブラリで可能か）を提示して合意を取る。
- 変更は `feature/<topic>` ブランチで行い、小さい単位でコミットする。コミットメッセージは命令形・1行サマリ＋必要なら本文。
- **コミット前チェック**（最低限のスモークテスト）:
  ```
  # 構文チェック
  python -c "import ast,sys; ast.parse(open('todo_dashboard.py',encoding='utf-8').read()); print('syntax OK')"
  # ユニットテスト（parse/format ラウンドトリップ・update/delete/add・_check_target ガード）
  python -m unittest discover -s tests -v
  ```
  `tests/test_dashboard.py` が §3 の3パターン（優先度＋期限あり / ネスト＋完了 / 優先度なし）を
  含む30ケースをカバーしている。パーサや書き込み関数を触ったら必ずテストを通すこと。
- 仕様（§2〜§5）を変えたら、**この CLAUDE.md を同じコミットで更新**する。ドキュメントと実装を乖離させない。
- 大きめの変更後は `/security-review` を実行して書き込みガード・入力エスケープの退行がないか確認する。
- ロードマップは `TODO.md`（このリポジトリ直下）にある。着手前にユーザへ優先度の確認を取る。

## 7. やらないこと

- 認証・アカウント作成・権限変更・課金・送信系の自動実行は実装しない（ローカル個人ツールの範囲を超える）。
- `TODO.md` 以外のファイルへの書き込み機能を追加しない。
