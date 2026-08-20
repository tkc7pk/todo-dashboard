---
project: todo-dashboard
updated: 2026-06-13
---

# todo-dashboard ロードマップ

このツール自身の TODO。ダッシュボードを `--root F:\claude` で起動すると、
このファイルも `todo-dashboard` プロジェクトとして一覧に出ます（自己ドッグフーディング）。

## 外部公開（Cloudflare Tunnel + Access・2026-08-20 実装・セットアップ待ち）

Discord通知（`--notify`）はP1/P2先頭5件＋P3/P4件数のみで全タスクが見えないため、
既存のローカルWebサーバー（`127.0.0.1:8765`）をこのPCから直接Cloudflare Tunnel経由で
外部公開し、スマホから全タスクを見られるようにする。コードは `--require-cf-access` フラグと
`cf_access_ok()` のヘッダーチェックを追加済み（CLAUDE.md §2/§5/§7 参照）。

- [x] (P1) `todo_dashboard.py` に `cf_access_ok()` と `--require-cf-access` を追加
- [x] (P1) `tests/test_dashboard.py` に `TestCfAccessGuard` を追加
- [x] (P1) `CLAUDE.md` の外部公開方針を更新
- [ ] (P1) Cloudflare Zero Trust で Windows用トンネル作成（名前 `todo-dashboard-win`）
      → `cloudflared.exe service install <token>` でサービス登録
- [ ] (P1) Public Hostname 追加（`todo` / `naozi.jp` → `localhost:8765`）
- [ ] (P1) Access アプリケーション作成（`todo.naozi.jp`、メールOTP、tkj.kato@gmail.com のみ許可）
- [ ] (P2) `todo_dashboard.py --root F:\claude --no-browser --require-cf-access` を
      Windowsタスクスケジューラに登録（トリガー: スタートアップ時・ログオン状態を問わない）
- [ ] (P2) PCを再起動しログオンせずに `https://todo.naozi.jp` へアクセスできることを確認
- [ ] (P3) （任意）電源設定でスリープを無効化し、常時アクセス可能にする

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
