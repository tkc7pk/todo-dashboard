---
project: todo-dashboard
updated: 2026-06-13
goal: プロジェクト横断のTODOを1画面で把握できる状態を保つ
---

# todo-dashboard ロードマップ

このツール自身の TODO。ダッシュボードを `--root F:\claude` で起動すると、
このファイルも `todo-dashboard` プロジェクトとして一覧に出ます（自己ドッグフーディング）。

## 外部公開（Cloudflare Tunnel + Access・2026-08-25 完了）

Discord通知（`--notify`）はP1/P2先頭5件＋P3/P4件数のみで全タスクが見えないため、
既存のローカルWebサーバー（`127.0.0.1:8765`）をこのPCから直接Cloudflare Tunnel経由で
外部公開し、スマホから全タスクを見られるようにした。コードは `--require-cf-access` フラグと
`cf_access_ok()` のヘッダーチェックを追加済み（CLAUDE.md §2/§5/§7 参照）。

**`https://todo.naozi.jp` にスマホからOne-Time PINでログインして動作確認済み。**

- [x] (P1) `todo_dashboard.py` に `cf_access_ok()` と `--require-cf-access` を追加
- [x] (P1) `tests/test_dashboard.py` に `TestCfAccessGuard` を追加
- [x] (P1) `CLAUDE.md` の外部公開方針を更新
- [x] (P1) cloudflared をこのPCに winget でインストール（`C:\Program Files (x86)\cloudflared\cloudflared.exe`、
      version 2026.8.2）
- [x] (P1) Cloudflare Zero Trust で Windows用トンネル作成（名前 `todo-dashboard-win`、
      Tunnel ID `aa4f1d5b-77d4-4250-86f2-21cf77b22a5e`）→ `cloudflared.exe service install <token>` で
      Windowsサービス登録済み（`Get-Service cloudflared` → Status: Running, StartType: Automatic）
- [x] (P1) Public Hostname 追加済み（`todo.naozi.jp` → `http://localhost:8765`）
- [x] (P1) Access アプリケーション作成（`todo.naozi.jp`、Policy `owner-only`: Allow /
      Emails: tkj.kato@gmail.com のみ、Login methods: One-Time PIN）
- [x] (P2) `todo_dashboard.py --root F:\claude --no-browser --require-cf-access` を
      Windowsタスクスケジューラ「TodoDashboard」に登録（トリガー: ログオン時。
      「スタートアップ時・ログオン不要」はパスワード保存が必要になるため、
      セキュリティ上の理由で「ログオン時」に変更した — PCにログインした状態で
      使う分には実質支障なし）
- [x] (P2) スマホ実機で `https://todo.naozi.jp` にログインし、ダッシュボードが表示されることを確認
- [ ] (P3) （任意）電源設定でスリープを無効化し、常時アクセス可能にする

### セットアップ時にハマった2つの罠（今後同じ構成をやる時のために記録）

1. **Access アプリケーションの宛先が `todo.naozi.jp.naozi.jp` と二重登録されていた**。
   アプリ作成フォームの「サブドメイン」欄に誤って `todo.naozi.jp`（フルホスト名）を入力し、
   「ドメイン」欄の `naozi.jp` と結合されて二重になっていた。症状: Cloudflare Access の
   ログインエンドポイント（`https://<team>.cloudflareaccess.com/cdn-cgi/access/login/<host>`）
   が `Unable to find your Access application!` で404になり、`todo.naozi.jp` への
   アクセスがAccessを素通りしてオリジンに直接届いてしまう（`--require-cf-access` が
   ヘッダー無しで403を返すので、一見「Accessが機能している」ように誤解しやすい）。
   直し方: アプリの「宛先」でサブドメイン欄を `todo` だけに修正して保存し直す。
2. **アカウントに「Cloudflare」という種類のIDプロバイダーが自動登録されていて、
   One-Time PINが使えなくなっていた**。ダッシュボードの説明文には「IDプロバイダーを
   追加しなければOne-Time PINがデフォルト」とあるが、実際には「Cloudflare」IDPが
   1件登録されている状態だとOne-Time PINが選択肢に出ない。この「Cloudflare」IDPを
   インテグレーション → IDプロバイダーの画面から削除しても、今度は
   「ログイン方法が1つもありません」になる（自動デフォルトには戻らない）。
   直し方: 同じ画面から明示的に **One-Time PIN を追加**する必要がある
   （Google/Okta等と同列の選択肢として一覧にある）。

## 改善候補

- [x] (P1) スモークテストを `tests/` に整備（parse/format ラウンドトリップ＋update/delete/add＋ガードを stdlib `unittest` で）
- [x] (P2) プロジェクト概要ビュー＋全体TODO対応（カード一覧・ドリルダウン・ゴールのインライン編集・
      `F:\claude\TODO.md` を「全体」プロジェクトとして扱う・サイドバー進捗バー・`buildRaw` の indent/bullet 保持）
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
