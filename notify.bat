@echo off
REM TODOサマリーをDiscordに送信するバッチファイル
REM
REM セットアップ:
REM   1. Discordチャンネルで Webhook URL を取得
REM   2. システム環境変数 DISCORD_WEBHOOK に URL を設定
REM      (コントロールパネル > システム > 環境変数 > システム環境変数に追加)
REM   3. Windowsタスクスケジューラで毎朝9時にこのファイルを実行するよう登録
REM
REM 手動実行:
REM   notify.bat
REM   または Webhook URL を直接指定:
REM   python todo_dashboard.py --root F:\claude --notify --discord-webhook "https://discord.com/api/webhooks/..."

python "%~dp0todo_dashboard.py" --root F:\claude --notify --discord-webhook %DISCORD_WEBHOOK%
