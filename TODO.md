---
project: todo-dashboard
updated: 2026-06-13
---

# todo-dashboard ロードマップ

このツール自身の TODO。ダッシュボードを `--root F:\claude` で起動すると、
このファイルも `todo-dashboard` プロジェクトとして一覧に出ます（自己ドッグフーディング）。

## 改善候補

- [x] (P1) スモークテストを `tests/` に整備（parse/format ラウンドトリップ＋update/delete/add＋ガードを stdlib `unittest` で）
- [ ] (P2) 手動並べ替え順の永続化（同一優先度内の順序。フロントマターか専用コメントで order を保持）
- [ ] (P2) Windows 用ランチャ `start.bat`（`python todo_dashboard.py --root F:\claude` を1クリック起動）
- [ ] (P3) 自動更新（ファイル変更監視 or 一定間隔ポーリングで再スキャン）
- [ ] (P3) 設定ファイル対応（起点・ポート・除外フォルダを `.todo_dashboard.toml` で指定）
- [ ] (P3) タグ／担当の任意フィールド対応（`#tag` を本文から抽出してフィルタ）
- [ ] (P4) 完了タスクの「アーカイブ」表示（古い完了を畳む）
- [ ] (P4) キーボードショートカット（j/k 移動、x で完了、1〜4 で優先度）

## 既知の制限（メモ）

- 同一ファイル内に**完全一致する行**が複数あると、最初の1件だけが置換対象になる。
- `due` の書式は `<!-- due:YYYY-MM-DD -->` のみ対応。
