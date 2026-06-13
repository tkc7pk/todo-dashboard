#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
todo_dashboard.py  --  Claude Code プロジェクト横断 TODO ダッシュボード

各プロジェクト配下の TODO.md を正本(source of truth)として読み込み、
ブラウザ上で優先度順の一覧表示・チェック・優先度変更・並べ替え・追加・削除を行い、
変更はそのまま TODO.md に書き戻します。追加インストール不要(Python標準ライブラリのみ)。

使い方:
    python todo_dashboard.py                 # カレントディレクトリを起点にスキャン
    python todo_dashboard.py --root F:\\claude # 起点を指定
    python todo_dashboard.py --port 8765 --no-browser

TODO.md の書式(ゆるい規約):
    ---
    project: 表示名(省略時はフォルダ名)
    ---
    - [ ] (P1) タスク内容 <!-- due:2026-06-20 -->
    - [x] (P3) 完了したタスク
    - [ ] 優先度未設定のタスク
  * (P1)〜(P4) で優先度。無くてもよい(「未設定」として表示)。
  * <!-- due:YYYY-MM-DD --> で期限(任意)。
"""

import argparse
import json
import os
import re
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

IGNORE_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__",
               "dist", "build", ".next", "target", ".cache", ".idea", ".tox"}
TODO_NAMES = {"todo.md"}
ANALYSIS_NAMES = {"todo_analysis.md"}

TASK_RE = re.compile(r"^(?P<indent>\s*)(?P<bullet>[-*+])\s+\[(?P<check>[ xX])\]\s*(?P<body>.*)$")
PRI_RE = re.compile(r"^\(\s*[Pp](?P<n>[1-4])\s*\)\s*")
DUE_RE = re.compile(r"\s*<!--\s*due:\s*(?P<due>\d{4}-\d{2}-\d{2})\s*-->\s*")

ROOT = Path(".").resolve()


# ---------- parsing / formatting ----------

def parse_task_line(line):
    """1行をパースしてタスク辞書を返す。タスク行でなければ None。"""
    m = TASK_RE.match(line.rstrip("\n"))
    if not m:
        return None
    indent = m.group("indent")
    bullet = m.group("bullet")
    checked = m.group("check").lower() == "x"
    body = m.group("body")

    pri = None
    pm = PRI_RE.match(body)
    if pm:
        pri = int(pm.group("n"))
        body = body[pm.end():]

    due = None
    dm = DUE_RE.search(body)
    if dm:
        due = dm.group("due")
        body = (body[:dm.start()] + body[dm.end():])

    text = body.strip()
    return {
        "indent": indent,
        "bullet": bullet,
        "checked": checked,
        "priority": pri,
        "text": text,
        "due": due,
    }


def format_task_line(t):
    """タスク辞書を1行の文字列に再構成する。"""
    parts = []
    parts.append(f"{t['indent']}{t['bullet']} [{'x' if t['checked'] else ' '}] ")
    line = "".join(parts)
    if t.get("priority"):
        line += f"(P{int(t['priority'])}) "
    line += (t.get("text") or "")
    if t.get("due"):
        line += f" <!-- due:{t['due']} -->"
    return line


def parse_frontmatter(lines):
    """先頭の YAML フロントマターから project と priority を取り出す。
    戻り値: {"project": str|None, "priority": str|None}
    """
    result = {"project": None, "priority": None}
    if not lines or lines[0].strip() != "---":
        return result
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            break
        m = re.match(r"\s*project\s*:\s*(.+?)\s*$", lines[i])
        if m:
            result["project"] = m.group(1).strip().strip('"').strip("'")
        m2 = re.match(r"\s*priority\s*:\s*(P[1-4])\s*$", lines[i], re.IGNORECASE)
        if m2:
            result["priority"] = m2.group(1).upper()
    return result


# ---------- scanning ----------

def iter_todo_files(root):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS and not d.startswith(".")]
        for fn in filenames:
            if fn.lower() in TODO_NAMES:
                yield Path(dirpath) / fn


def find_analysis(root):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS and not d.startswith(".")]
        for fn in filenames:
            if fn.lower() in ANALYSIS_NAMES:
                p = Path(dirpath) / fn
                try:
                    return {"file": str(p), "content": p.read_text(encoding="utf-8", errors="replace")}
                except Exception:
                    return None
    return None


def scan(root):
    projects = []
    tasks = []
    for f in sorted(iter_todo_files(root)):
        try:
            raw = f.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        lines = raw.splitlines()
        fm = parse_frontmatter(lines)
        project = fm["project"] or f.parent.name
        proj_priority = fm["priority"]
        rel = str(f.relative_to(root)) if str(f).startswith(str(root)) else str(f)
        projects.append({"project": project, "file": str(f), "rel": rel, "priority": proj_priority})
        for idx, line in enumerate(lines):
            t = parse_task_line(line)
            if t is None:
                continue
            tasks.append({
                "id": f"{f}::{idx}",
                "project": project,
                "file": str(f),
                "lineno": idx,
                "checked": t["checked"],
                "priority": t["priority"],
                "text": t["text"],
                "due": t["due"],
                "raw": line,
            })
    # de-dup project list, keep order
    seen = set()
    uniq_projects = []
    for p in projects:
        if p["project"] in seen:
            continue
        seen.add(p["project"])
        uniq_projects.append(p)

    stats = {"open": 0, "done": 0, "p1": 0, "p2": 0, "p3": 0, "p4": 0, "none": 0}
    for t in tasks:
        if t["checked"]:
            stats["done"] += 1
        else:
            stats["open"] += 1
            key = f"p{t['priority']}" if t["priority"] else "none"
            stats[key] += 1
    return {
        "root": str(root),
        "projects": uniq_projects,
        "tasks": tasks,
        "analysis": find_analysis(root),
        "stats": stats,
    }


# ---------- safe file mutations ----------

def _check_target(file_str):
    """書き込み対象が root 配下の todo.md であることを保証する。"""
    p = Path(file_str).resolve()
    if p.name.lower() not in TODO_NAMES:
        raise ValueError("対象は TODO.md のみ書き込み可能です")
    try:
        p.relative_to(ROOT)
    except ValueError:
        raise ValueError("対象が起点ディレクトリの外です")
    return p


def update_line(file_str, old_raw, new_raw):
    p = _check_target(file_str)
    text = p.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines(keepends=True)
    for i, line in enumerate(lines):
        if line.rstrip("\n").rstrip("\r") == old_raw.rstrip("\n").rstrip("\r"):
            nl = "\r\n" if line.endswith("\r\n") else ("\n" if line.endswith("\n") else "")
            lines[i] = new_raw + nl
            p.write_text("".join(lines), encoding="utf-8")
            return True
    raise ValueError("元の行が見つかりませんでした(外部で編集された可能性)。更新して再試行してください")


def delete_line(file_str, old_raw):
    p = _check_target(file_str)
    text = p.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines(keepends=True)
    for i, line in enumerate(lines):
        if line.rstrip("\n").rstrip("\r") == old_raw.rstrip("\n").rstrip("\r"):
            del lines[i]
            p.write_text("".join(lines), encoding="utf-8")
            return True
    raise ValueError("元の行が見つかりませんでした")


def add_task(file_str, text, priority):
    p = _check_target(file_str)
    content = p.read_text(encoding="utf-8", errors="replace")
    t = {"indent": "", "bullet": "-", "checked": False,
         "priority": int(priority) if priority else None, "text": text.strip(), "due": None}
    new_line = format_task_line(t)
    sep = "" if content.endswith("\n") or content == "" else "\n"
    p.write_text(content + sep + new_line + "\n", encoding="utf-8")
    return new_line


def update_project_priority(file_str, priority):
    """TODO.md のフロントマターに priority: Pn を書き込む。
    priority が空文字または None のときは priority 行を削除（未設定）。
    """
    if priority and not re.match(r"^P[1-4]$", priority, re.IGNORECASE):
        raise ValueError(f"priority は P1〜P4 で指定してください: {priority!r}")
    priority = priority.upper() if priority else ""

    p = _check_target(file_str)
    content = p.read_text(encoding="utf-8", errors="replace")
    lines = content.splitlines(keepends=True)

    # フロントマターの範囲を探す
    if lines and lines[0].strip() == "---":
        close = None
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                close = i
                break
        if close is not None:
            # フロントマターあり → priority 行を更新/挿入/削除
            pri_idx = None
            for i in range(1, close):
                if re.match(r"\s*priority\s*:", lines[i]):
                    pri_idx = i
                    break
            if priority:
                new_pri_line = f"priority: {priority}\n"
                if pri_idx is not None:
                    lines[pri_idx] = new_pri_line
                else:
                    lines.insert(close, new_pri_line)
            else:
                if pri_idx is not None:
                    del lines[pri_idx]
            p.write_text("".join(lines), encoding="utf-8")
            return

    # フロントマターなし → 先頭に新規ブロックを挿入
    if priority:
        header = f"---\npriority: {priority}\n---\n"
        p.write_text(header + content, encoding="utf-8")


# ---------- HTTP handler ----------

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # quiet

    def _send_json(self, obj, code=200):
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_html(self, html):
        data = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _body(self):
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length).decode("utf-8")) if length else {}

    def do_GET(self):
        if self.path == "/" or self.path.startswith("/?"):
            self._send_html(PAGE)
        elif self.path == "/api/scan":
            try:
                self._send_json(scan(ROOT))
            except Exception as e:
                self._send_json({"error": str(e)}, 500)
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        try:
            body = self._body()
            if self.path == "/api/update":
                update_line(body["file"], body["old_raw"], body["new_raw"])
                self._send_json({"ok": True})
            elif self.path == "/api/delete":
                delete_line(body["file"], body["old_raw"])
                self._send_json({"ok": True})
            elif self.path == "/api/add":
                new_line = add_task(body["file"], body["text"], body.get("priority"))
                self._send_json({"ok": True, "new_raw": new_line})
            elif self.path == "/api/update-project":
                update_project_priority(body["file"], body.get("priority", ""))
                self._send_json({"ok": True})
            else:
                self.send_response(404)
                self.end_headers()
        except Exception as e:
            self._send_json({"error": str(e)}, 400)


# ---------- embedded UI ----------

PAGE = r"""<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>TODO ダッシュボード</title>
<style>
  :root{
    --bg:#0f1419; --surface:#161b22; --surface-2:#1b212b; --raised:#202836;
    --border:#283041; --border-soft:#222a36;
    --text:#dfe5ee; --muted:#828d9c; --faint:#5b6573;
    --accent:#d97757; --accent-soft:#3a2820;
    --p1:#f2555a; --p2:#f0934e; --p3:#5db0a8; --p4:#5a86c4; --none:#7d8795;
    --done:#4b5563;
    --mono:'Cascadia Code','Cascadia Mono',Consolas,'SF Mono',ui-monospace,Menlo,monospace;
    --sans:system-ui,'Segoe UI','Hiragino Kaku Gothic ProN','Yu Gothic UI',sans-serif;
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--text);font-family:var(--sans);
       font-size:14px;line-height:1.5;-webkit-font-smoothing:antialiased}
  a{color:var(--accent)}
  .wrap{max-width:1080px;margin:0 auto;padding:28px 22px 80px}

  header{display:flex;align-items:baseline;gap:14px;flex-wrap:wrap;margin-bottom:4px}
  h1{font-size:19px;font-weight:650;letter-spacing:.2px;margin:0}
  h1 .dot{display:inline-block;width:9px;height:9px;border-radius:2px;
          background:linear-gradient(135deg,var(--p1),var(--p4));margin-right:9px;vertical-align:middle}
  .root{font-family:var(--mono);font-size:12px;color:var(--muted);
        background:var(--surface);border:1px solid var(--border-soft);
        padding:3px 8px;border-radius:6px}
  .spacer{flex:1}
  button{font-family:var(--sans);cursor:pointer}
  .btn{background:var(--surface-2);color:var(--text);border:1px solid var(--border);
       padding:7px 13px;border-radius:7px;font-size:13px;transition:background .12s,border-color .12s}
  .btn:hover{background:var(--raised);border-color:#36404f}
  .btn.primary{background:var(--accent);border-color:var(--accent);color:#1a1411;font-weight:600}
  .btn.primary:hover{background:#e08763}

  .stats{display:flex;gap:8px;flex-wrap:wrap;margin:18px 0 10px}
  .stat{font-family:var(--mono);font-size:12px;color:var(--muted);
        background:var(--surface);border:1px solid var(--border-soft);
        border-radius:6px;padding:5px 9px;display:flex;gap:7px;align-items:center}
  .stat b{color:var(--text);font-weight:600}
  .pill{width:8px;height:8px;border-radius:50%}

  .controls{display:flex;gap:10px;flex-wrap:wrap;align-items:center;
            margin:14px 0 22px;padding-bottom:16px;border-bottom:1px solid var(--border-soft)}
  .controls input[type=text], .controls select{
    font-family:var(--sans);font-size:13px;color:var(--text);
    background:var(--surface);border:1px solid var(--border);border-radius:7px;padding:7px 10px}
  .controls input[type=text]{min-width:200px;flex:1}
  .controls input::placeholder{color:var(--faint)}
  .seg{display:inline-flex;border:1px solid var(--border);border-radius:7px;overflow:hidden}
  .seg button{background:var(--surface);color:var(--muted);border:0;padding:7px 12px;font-size:13px}
  .seg button.on{background:var(--raised);color:var(--text)}

  .group{margin-bottom:18px}
  .group-head{display:flex;align-items:center;gap:10px;margin:0 0 8px 2px}
  .group-head .gdot{width:10px;height:10px;border-radius:3px}
  .group-head h2{font-size:12px;font-weight:600;letter-spacing:.08em;text-transform:uppercase;
                 color:var(--muted);margin:0}
  .group-head .count{font-family:var(--mono);font-size:11px;color:var(--faint)}
  .group.dragover .list{outline:1.5px dashed var(--accent);outline-offset:3px;border-radius:8px}

  .list{display:flex;flex-direction:column;gap:5px}
  .row{display:flex;align-items:flex-start;gap:0;background:var(--surface);
       border:1px solid var(--border-soft);border-radius:8px;overflow:hidden;
       transition:border-color .12s,background .12s}
  .row:hover{border-color:#323c4b;background:var(--surface-2)}
  .row.saved{animation:flash .7s ease}
  @keyframes flash{0%{background:var(--accent-soft)}100%{background:var(--surface)}}
  .row.done .txt{color:var(--done);text-decoration:line-through}
  .spine{width:4px;align-self:stretch;flex:0 0 auto}
  .grip{flex:0 0 auto;padding:11px 6px 0 8px;color:var(--faint);cursor:grab;
        font-size:13px;user-select:none;line-height:1}
  .grip:active{cursor:grabbing}
  .check{flex:0 0 auto;margin:11px 4px 0 2px;width:16px;height:16px;cursor:pointer;accent-color:var(--accent)}
  .main{flex:1;min-width:0;padding:9px 10px 9px 4px}
  .txt{font-family:var(--mono);font-size:13.5px;color:var(--text);word-break:break-word;
       cursor:text;border-radius:4px;padding:1px 3px;margin:-1px -3px}
  .txt:hover{background:var(--raised)}
  .txt-input{font-family:var(--mono);font-size:13.5px;color:var(--text);width:100%;
             background:var(--bg);border:1px solid var(--accent);border-radius:5px;padding:4px 6px}
  .meta{display:flex;gap:10px;align-items:center;margin-top:5px;flex-wrap:wrap}
  .badge{font-family:var(--mono);font-size:11px;color:var(--muted);
         background:var(--surface-2);border:1px solid var(--border-soft);
         border-radius:5px;padding:2px 7px}
  .due{font-family:var(--mono);font-size:11px;color:var(--p2)}
  .due.over{color:var(--p1);font-weight:600}
  .src{font-family:var(--mono);font-size:10.5px;color:var(--faint)}
  .prisel{flex:0 0 auto;margin:9px 8px 0 0}
  .prisel select{font-family:var(--mono);font-size:11px;background:var(--surface-2);
                 color:var(--text);border:1px solid var(--border);border-radius:6px;padding:3px 5px}
  .del{flex:0 0 auto;margin:9px 8px 0 0;background:transparent;border:0;color:var(--faint);
       font-size:14px;padding:2px 6px;border-radius:5px}
  .del:hover{color:var(--p1);background:var(--surface-2)}

  .addbar{display:flex;gap:8px;align-items:center;margin-top:10px;flex-wrap:wrap}
  .addbar select,.addbar input{font-family:var(--sans);font-size:13px;color:var(--text);
        background:var(--surface);border:1px solid var(--border);border-radius:7px;padding:7px 10px}
  .addbar input[type=text]{flex:1;min-width:200px;font-family:var(--mono)}

  .empty{color:var(--muted);font-size:13px;padding:30px 4px;text-align:center;
         border:1px dashed var(--border);border-radius:10px}
  .toast{position:fixed;bottom:20px;left:50%;transform:translateX(-50%);
         background:var(--raised);color:var(--text);border:1px solid var(--border);
         padding:10px 16px;border-radius:9px;font-size:13px;opacity:0;pointer-events:none;
         transition:opacity .2s;z-index:50}
  .toast.show{opacity:1}
  .toast.err{border-color:var(--p1);color:#ffd2d2}

  details.analysis{margin-top:26px;border:1px solid var(--border-soft);border-radius:10px;
                   background:var(--surface);overflow:hidden}
  details.analysis summary{padding:11px 14px;cursor:pointer;font-size:13px;color:var(--muted);
                           list-style:none;font-family:var(--mono)}
  details.analysis summary::-webkit-details-marker{display:none}
  details.analysis pre{margin:0;padding:0 16px 16px;font-family:var(--mono);font-size:12.5px;
                       color:var(--text);white-space:pre-wrap;line-height:1.6}

  body{display:flex;align-items:flex-start}

  #sidebar{
    width:220px;flex:0 0 220px;min-height:100vh;
    background:var(--surface);border-right:1px solid var(--border);
    display:flex;flex-direction:column;position:sticky;top:0;overflow-y:auto;
  }
  .sb-head{
    padding:18px 14px 10px;font-size:11px;font-weight:700;letter-spacing:.1em;
    text-transform:uppercase;color:var(--muted);border-bottom:1px solid var(--border-soft);
  }
  .sb-all{
    padding:10px 12px 6px;display:flex;align-items:center;gap:8px;
    cursor:pointer;border-radius:7px;margin:6px 8px 2px;
    font-size:13px;color:var(--muted);transition:background .1s;
  }
  .sb-all:hover,.sb-all.on{background:var(--raised);color:var(--text)}
  .sb-item{
    padding:7px 12px;margin:2px 8px;border-radius:7px;cursor:pointer;
    display:flex;flex-direction:column;gap:4px;transition:background .1s;
  }
  .sb-item:hover{background:var(--surface-2)}
  .sb-item.on{background:var(--raised)}
  .sb-name{font-size:13px;color:var(--text);word-break:break-all;line-height:1.3}
  .sb-pri{display:flex;align-items:center;gap:6px;margin-top:2px}
  .sb-dot{width:7px;height:7px;border-radius:50%;flex-shrink:0}
  .sb-sel{
    font-family:var(--mono);font-size:11px;background:var(--surface-2);
    color:var(--muted);border:1px solid var(--border);border-radius:5px;
    padding:2px 4px;cursor:pointer;
  }
  .sb-sel:hover{border-color:#36404f}
  .wrap{flex:1;min-width:0}

  @media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
  @media (max-width:700px){#sidebar{display:none}}
  @media (max-width:600px){.src{display:none}}
</style>
</head>
<body>
<aside id="sidebar">
  <div class="sb-head">プロジェクト</div>
  <div id="sb-list"></div>
</aside>
<div class="wrap">
  <header>
    <h1><span class="dot"></span>TODO ダッシュボード</h1>
    <span class="root" id="root">…</span>
    <span class="spacer"></span>
    <button class="btn" id="copyPrompt" title="全タスクを並べた優先度提案プロンプトをコピーします">Claude用プロンプトをコピー</button>
    <button class="btn primary" id="refresh">更新</button>
  </header>

  <div class="stats" id="stats"></div>

  <div class="controls">
    <input type="text" id="search" placeholder="タスクを検索…">
    <select id="project" style="display:none"><option value="">すべてのプロジェクト</option></select>
    <div class="seg" id="statusSeg">
      <button data-s="open" class="on">未完了</button>
      <button data-s="all">すべて</button>
      <button data-s="done">完了</button>
    </div>
  </div>

  <div id="board"></div>

  <div class="addbar">
    <select id="addProject"></select>
    <select id="addPri">
      <option value="">優先度なし</option>
      <option value="1">P1</option><option value="2">P2</option>
      <option value="3">P3</option><option value="4">P4</option>
    </select>
    <input type="text" id="addText" placeholder="新しいタスクを追加…(Enter)">
    <button class="btn" id="addBtn">追加</button>
  </div>

  <div id="analysisHost"></div>
</div>
<div class="toast" id="toast"></div>

<script>
const PRIOS = [
  {key:1, label:'P1', name:'最優先', color:'var(--p1)'},
  {key:2, label:'P2', name:'高',     color:'var(--p2)'},
  {key:3, label:'P3', name:'中',     color:'var(--p3)'},
  {key:4, label:'P4', name:'低',     color:'var(--p4)'},
  {key:0, label:'—',  name:'未設定', color:'var(--none)'},
];
let DATA = {tasks:[], projects:[], stats:{}, root:''};
let FILTER = {q:'', project:'', status:'open'};

const $ = s => document.querySelector(s);
const esc = s => (s||'').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));

function toast(msg, isErr){
  const t = $('#toast'); t.textContent = msg;
  t.className = 'toast show' + (isErr?' err':'');
  clearTimeout(t._t); t._t = setTimeout(()=>t.className='toast', 2200);
}

async function api(path, body){
  const opt = body ? {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)} : {};
  const r = await fetch(path, opt);
  const j = await r.json();
  if(j.error) throw new Error(j.error);
  return j;
}

async function load(){
  try{
    DATA = await api('/api/scan');
    $('#root').textContent = DATA.root;
    fillProjects();
    renderStats();
    render();
    renderAnalysis();
    renderSidebar();
  }catch(e){ toast('読み込み失敗: '+e.message, true); }
}

function fillProjects(){
  const names = DATA.projects.map(p=>p.project);
  const sel = $('#project'), add = $('#addProject');
  sel.innerHTML = '<option value="">すべてのプロジェクト</option>' +
    names.map(n=>`<option value="${esc(n)}">${esc(n)}</option>`).join('');
  sel.value = FILTER.project;
  add.innerHTML = DATA.projects.map(p=>`<option value="${esc(p.file)}">${esc(p.project)}</option>`).join('');
}

function renderStats(){
  const s = DATA.stats;
  const cell = (color,label,val)=>`<span class="stat"><span class="pill" style="background:${color}"></span>${label} <b>${val}</b></span>`;
  $('#stats').innerHTML =
    cell('var(--p1)','P1', s.p1) + cell('var(--p2)','P2', s.p2) +
    cell('var(--p3)','P3', s.p3) + cell('var(--p4)','P4', s.p4) +
    cell('var(--none)','未設定', s.none) +
    `<span class="stat">未完了 <b>${s.open}</b></span>` +
    `<span class="stat">完了 <b>${s.done}</b></span>`;
}

function visible(t){
  if(FILTER.status==='open' && t.checked) return false;
  if(FILTER.status==='done' && !t.checked) return false;
  if(FILTER.project && t.project!==FILTER.project) return false;
  if(FILTER.q && !(t.text.toLowerCase().includes(FILTER.q) || t.project.toLowerCase().includes(FILTER.q))) return false;
  return true;
}

function today(){ const d=new Date(); return d.toISOString().slice(0,10); }

function rowHTML(t){
  const pri = t.priority || 0;
  const color = (PRIOS.find(p=>p.key===pri)||PRIOS[4]).color;
  const overdue = t.due && !t.checked && t.due < today();
  const due = t.due ? `<span class="due ${overdue?'over':''}">📅 ${t.due}</span>` : '';
  const src = `<span class="src">${esc(t.file.split(/[\\/]/).pop())}</span>`;
  const opts = [['','—'],['1','P1'],['2','P2'],['3','P3'],['4','P4']]
    .map(([v,l])=>`<option value="${v}" ${String(t.priority||'')===v?'selected':''}>${l}</option>`).join('');
  return `<div class="row ${t.checked?'done':''}" draggable="true" data-id="${esc(t.id)}">
    <div class="spine" style="background:${color}"></div>
    <div class="grip" title="ドラッグで優先度を変更">⋮⋮</div>
    <input type="checkbox" class="check" ${t.checked?'checked':''}>
    <div class="main">
      <div class="txt" tabindex="0">${esc(t.text)||'<span style="color:var(--faint)">(空)</span>'}</div>
      <div class="meta"><span class="badge">${esc(t.project)}</span>${due}${src}</div>
    </div>
    <div class="prisel"><select title="優先度">${opts}</select></div>
    <button class="del" title="削除">✕</button>
  </div>`;
}

function render(){
  const board = $('#board');
  const shown = DATA.tasks.filter(visible);
  if(shown.length===0){ board.innerHTML = '<div class="empty">該当するタスクはありません。</div>'; return; }
  board.innerHTML = PRIOS.map(p=>{
    const items = shown.filter(t=>(t.priority||0)===p.key);
    return `<div class="group" data-pri="${p.key}">
      <div class="group-head">
        <span class="gdot" style="background:${p.color}"></span>
        <h2>${p.label} · ${p.name}</h2>
        <span class="count">${items.length}</span>
      </div>
      <div class="list">${items.map(rowHTML).join('')}</div>
    </div>`;
  }).join('');
  wire();
}

function taskById(id){ return DATA.tasks.find(t=>t.id===id); }

// 行データから raw 文字列を再構成(サーバの format と同じ規則)
function buildRaw(t){
  let raw = `- [${t.checked?'x':' '}] `;
  if(t.priority) raw += `(P${t.priority}) `;
  raw += (t.text||'');
  if(t.due) raw += ` <!-- due:${t.due} -->`;
  return raw;
}

async function mutate(t, changes){
  const old_raw = t.raw;
  Object.assign(t, changes);
  const new_raw = buildRaw(t);
  try{
    await api('/api/update', {file:t.file, old_raw, new_raw});
    t.raw = new_raw;
    return true;
  }catch(e){
    Object.assign(t, {raw:old_raw});  // 楽観更新を巻き戻し
    toast('保存失敗: '+e.message, true);
    await load();
    return false;
  }
}

function wire(){
  document.querySelectorAll('.row').forEach(row=>{
    const id = row.dataset.id;
    const t = taskById(id);
    if(!t) return;

    row.querySelector('.check').addEventListener('change', async e=>{
      const ok = await mutate(t, {checked:e.target.checked});
      if(ok){ renderStats(); render(); }
    });

    row.querySelector('.prisel select').addEventListener('change', async e=>{
      const v = e.target.value ? parseInt(e.target.value,10) : null;
      const ok = await mutate(t, {priority:v});
      if(ok){ renderStats(); render(); }
    });

    row.querySelector('.del').addEventListener('click', async ()=>{
      if(!confirm('このタスクを TODO.md から削除します。よろしいですか？')) return;
      try{
        await api('/api/delete', {file:t.file, old_raw:t.raw});
        DATA.tasks = DATA.tasks.filter(x=>x.id!==id);
        renderStats(); render(); toast('削除しました');
      }catch(e){ toast('削除失敗: '+e.message, true); await load(); }
    });

    const txt = row.querySelector('.txt');
    txt.addEventListener('click', ()=>startEdit(txt, t, row));
    txt.addEventListener('keydown', e=>{ if(e.key==='Enter'){e.preventDefault();startEdit(txt,t,row);} });

    // drag & drop for priority
    row.addEventListener('dragstart', e=>{ e.dataTransfer.setData('text/plain', id); row.style.opacity=.4; });
    row.addEventListener('dragend', ()=>{ row.style.opacity=1; });
  });

  document.querySelectorAll('.group').forEach(g=>{
    g.addEventListener('dragover', e=>{ e.preventDefault(); g.classList.add('dragover'); });
    g.addEventListener('dragleave', ()=> g.classList.remove('dragover'));
    g.addEventListener('drop', async e=>{
      e.preventDefault(); g.classList.remove('dragover');
      const id = e.dataTransfer.getData('text/plain');
      const t = taskById(id); if(!t) return;
      const newPri = parseInt(g.dataset.pri,10) || null;
      if((t.priority||0)===(newPri||0)) return;
      const ok = await mutate(t, {priority:newPri});
      if(ok){ renderStats(); render();
        const moved = document.querySelector(`.row[data-id="${CSS.escape(id)}"]`);
        if(moved) moved.classList.add('saved');
      }
    });
  });
}

function startEdit(txt, t, row){
  if(row.querySelector('.txt-input')) return;
  const input = document.createElement('input');
  input.className='txt-input'; input.value=t.text; input.type='text';
  txt.replaceWith(input); input.focus(); input.select();
  const finish = async (save)=>{
    if(save && input.value.trim()!==t.text){
      const ok = await mutate(t, {text:input.value.trim()});
      if(!ok){ render(); return; }
    }
    render();
  };
  input.addEventListener('keydown', e=>{
    if(e.key==='Enter'){ e.preventDefault(); finish(true); }
    if(e.key==='Escape'){ finish(false); }
  });
  input.addEventListener('blur', ()=>finish(true));
}

function renderAnalysis(){
  const host = $('#analysisHost');
  if(DATA.analysis){
    host.innerHTML = `<details class="analysis"><summary>📋 ${esc(DATA.analysis.file.split(/[\\/]/).pop())} (Claudeの優先度提案)</summary><pre>${esc(DATA.analysis.content)}</pre></details>`;
  }else host.innerHTML='';
}

// ---- controls ----
$('#refresh').addEventListener('click', load);
$('#search').addEventListener('input', e=>{ FILTER.q=e.target.value.toLowerCase().trim(); render(); });
$('#project').addEventListener('change', e=>{ FILTER.project=e.target.value; render(); });
document.querySelectorAll('#statusSeg button').forEach(b=>{
  b.addEventListener('click', ()=>{
    document.querySelectorAll('#statusSeg button').forEach(x=>x.classList.remove('on'));
    b.classList.add('on'); FILTER.status=b.dataset.s; render();
  });
});

async function doAdd(){
  const file = $('#addProject').value;
  const text = $('#addText').value.trim();
  const pri = $('#addPri').value;
  if(!file || !text){ toast('プロジェクトとタスク内容を入力してください', true); return; }
  try{
    await api('/api/add', {file, text, priority: pri||null});
    $('#addText').value='';
    await load();
    toast('追加しました');
  }catch(e){ toast('追加失敗: '+e.message, true); }
}
$('#addBtn').addEventListener('click', doAdd);
$('#addText').addEventListener('keydown', e=>{ if(e.key==='Enter') doAdd(); });

$('#copyPrompt').addEventListener('click', ()=>{
  const open = DATA.tasks.filter(t=>!t.checked);
  const byProj = {};
  open.forEach(t=>{ (byProj[t.project]=byProj[t.project]||[]).push(t); });
  let p = `以下は複数プロジェクトの未完了TODOです。各タスクに優先度(P1=最優先〜P4=低)を割り当て、\n`;
  p += `各 TODO.md の該当行のチェックボックス直後に "(Pn) " を追記・修正してください。\n`;
  p += `判断根拠は各プロジェクト直下の TODO_ANALYSIS.md にまとめてください。\n\n`;
  for(const proj in byProj){
    p += `## ${proj}\n`;
    byProj[proj].forEach(t=>{ p += `- [${t.priority?'P'+t.priority:'未'}] ${t.text} (${t.file})\n`; });
    p += `\n`;
  }
  navigator.clipboard.writeText(p).then(
    ()=>toast('プロンプトをコピーしました。Claude Codeに貼り付けてください'),
    ()=>toast('コピーに失敗しました', true)
  );
});

// ---- sidebar ----
const PRI_META = {
  P1:{color:'var(--p1)',label:'P1'},
  P2:{color:'var(--p2)',label:'P2'},
  P3:{color:'var(--p3)',label:'P3'},
  P4:{color:'var(--p4)',label:'P4'},
};

function selectProject(name){
  FILTER.project = name;
  $('#project').value = name;
  renderSidebar();
  render();
}

function renderSidebar(){
  const list = $('#sb-list');
  const allActive = !FILTER.project;
  let html = `<div class="sb-all${allActive?' on':''}" id="sb-all">すべて</div>`;
  for(const p of DATA.projects){
    const active = FILTER.project === p.project;
    const pri = p.priority ? PRI_META[p.priority] : null;
    const dot = pri
      ? `<span class="sb-dot" style="background:${pri.color}"></span>`
      : `<span class="sb-dot" style="background:var(--none)"></span>`;
    const opts = ['','P1','P2','P3','P4'].map(v=>
      `<option value="${v}" ${p.priority===v?'selected':''}>${v||'—'}</option>`
    ).join('');
    html += `<div class="sb-item${active?' on':''}" data-proj="${esc(p.project)}">
      <div class="sb-name">${esc(p.project)}</div>
      <div class="sb-pri">${dot}
        <select class="sb-sel" data-file="${esc(p.file)}" data-proj="${esc(p.project)}"
                title="プロジェクト優先度">${opts}</select>
      </div>
    </div>`;
  }
  list.innerHTML = html;

  $('#sb-all').addEventListener('click', ()=>selectProject(''));
  list.querySelectorAll('.sb-item').forEach(el=>{
    el.addEventListener('click', e=>{
      if(e.target.classList.contains('sb-sel')) return;
      selectProject(el.dataset.proj);
    });
  });
  list.querySelectorAll('.sb-sel').forEach(sel=>{
    sel.addEventListener('change', async e=>{
      e.stopPropagation();
      const file = sel.dataset.file;
      const priority = sel.value;
      try{
        await api('/api/update-project', {file, priority});
        const proj = DATA.projects.find(p=>p.file===file);
        if(proj) proj.priority = priority || null;
        renderSidebar();
        toast('プロジェクト優先度を更新しました');
      }catch(err){ toast('更新失敗: '+err.message, true); }
    });
  });
}

load();
</script>
</body>
</html>
"""


def main():
    global ROOT
    ap = argparse.ArgumentParser(description="Claude Code プロジェクト横断 TODO ダッシュボード")
    ap.add_argument("--root", default=".", help="スキャン起点(デフォルト: カレントディレクトリ)")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--no-browser", action="store_true", help="ブラウザを自動で開かない")
    args = ap.parse_args()

    ROOT = Path(args.root).resolve()
    if not ROOT.exists():
        raise SystemExit(f"起点ディレクトリが存在しません: {ROOT}")

    url = f"http://{args.host}:{args.port}/"
    print(f"  TODO ダッシュボード")
    print(f"  起点 : {ROOT}")
    print(f"  URL  : {url}")
    print(f"  停止 : Ctrl+C")
    print()

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    if not args.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n停止しました。")
        server.shutdown()


if __name__ == "__main__":
    main()