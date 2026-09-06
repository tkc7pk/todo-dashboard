"""
tests/test_dashboard.py — unittest スモークテスト

カバー範囲:
  - parse_task_line / format_task_line ラウンドトリップ (§3 の3パターン＋α)
  - update_line / delete_line / add_task のファイル操作
  - _check_target のセキュリティガード（範囲外・todo.md 以外を弾く）
"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

import todo_dashboard as td


# ---------------------------------------------------------------------------
# parse_task_line / format_task_line ラウンドトリップ
# ---------------------------------------------------------------------------

class TestParseFormatRoundtrip(unittest.TestCase):

    def _check(self, line):
        t = td.parse_task_line(line)
        self.assertIsNotNone(t, f"parse_task_line returned None for: {line!r}")
        self.assertEqual(td.format_task_line(t), line)

    def test_priority_and_due(self):
        """§3 パターン1: 優先度 + 期限あり"""
        self._check("- [ ] (P1) タスク内容 <!-- due:2026-06-20 -->")

    def test_nested_and_checked(self):
        """§3 パターン2: ネスト + 完了"""
        self._check("  * [x] (P3) 完了タスク")

    def test_no_priority(self):
        """§3 パターン3: 優先度なし"""
        self._check("- [ ] 優先度なしタスク")

    def test_plus_bullet(self):
        """+ 記法のタスク行"""
        self._check("+ [ ] (P2) plus bullet task")

    def test_uppercase_X_normalised(self):
        """[X] は checked=True と解釈し、format で小文字 x に正規化される"""
        t = td.parse_task_line("- [X] done task")
        self.assertIsNotNone(t)
        self.assertTrue(t["checked"])
        self.assertIn("[x]", td.format_task_line(t))

    def test_non_task_lines_return_none(self):
        """タスク行でない行は None を返す"""
        for line in ("# heading", "", "通常テキスト", "---"):
            self.assertIsNone(td.parse_task_line(line), f"should be None: {line!r}")

    def test_trailing_newline_stripped(self):
        """末尾改行は parse で除去され、round-trip は改行なし文字列で成立する"""
        t = td.parse_task_line("- [ ] (P2) foo\n")
        self.assertIsNotNone(t)
        self.assertEqual(td.format_task_line(t), "- [ ] (P2) foo")

    def test_all_priorities(self):
        """P1〜P4 すべてがラウンドトリップ可逆"""
        for n in range(1, 5):
            self._check(f"- [ ] (P{n}) task")

    def test_deep_nested_with_due(self):
        """深いネスト + 期限あり（JS の buildRaw 修正の回帰確認: indent/bullet が失われないこと）"""
        self._check("    - [ ] (P2) deeply nested with due <!-- due:2026-12-01 -->")

    def test_checked_state_preserved(self):
        """完了 / 未完了の両方が正しく往復する"""
        self._check("- [x] done item")
        self._check("- [ ] open item")


# ---------------------------------------------------------------------------
# _check_target セキュリティガード
# ---------------------------------------------------------------------------

class TestCheckTarget(unittest.TestCase):

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self._tmpdir.name).resolve()
        self._patch = patch.object(td, "ROOT", self.root)
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        self._tmpdir.cleanup()

    def test_accepts_todo_md_inside_root(self):
        """ROOT 配下の todo.md (大文字混在も可) は通過する"""
        p = self.root / "proj" / "TODO.md"
        p.parent.mkdir(parents=True)
        p.touch()
        result = td._check_target(str(p))
        self.assertEqual(result, p.resolve())

    def test_rejects_notes_md(self):
        """notes.md は todo.md でないので拒否される"""
        p = self.root / "notes.md"
        with self.assertRaises(ValueError):
            td._check_target(str(p))

    def test_rejects_readme_md(self):
        """README.md も拒否される"""
        p = self.root / "README.md"
        with self.assertRaises(ValueError):
            td._check_target(str(p))

    def test_rejects_outside_root(self):
        """ROOT の外にある todo.md は拒否される"""
        with tempfile.TemporaryDirectory() as other:
            outside = Path(other).resolve() / "todo.md"
            with self.assertRaises(ValueError):
                td._check_target(str(outside))


# ---------------------------------------------------------------------------
# cf_access_ok — Cloudflare Access ガード
# ---------------------------------------------------------------------------

class TestCfAccessGuard(unittest.TestCase):

    def test_not_required_always_allows(self):
        """required=False（ローカル利用の既定）なら常に許可される"""
        self.assertTrue(td.cf_access_ok({}, False))

    def test_required_without_header_is_denied(self):
        """required=True かつヘッダー無しは拒否される"""
        self.assertFalse(td.cf_access_ok({}, True))

    def test_required_with_header_is_allowed(self):
        """required=True でも Cf-Access-Jwt-Assertion ヘッダーがあれば許可される"""
        headers = {"Cf-Access-Jwt-Assertion": "dummy-token"}
        self.assertTrue(td.cf_access_ok(headers, True))


# ---------------------------------------------------------------------------
# update_line / delete_line / add_task ファイル操作
# ---------------------------------------------------------------------------

class TestFileMutations(unittest.TestCase):

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self._tmpdir.name).resolve()
        self._patch = patch.object(td, "ROOT", self.root)
        self._patch.start()
        self.todo = self.root / "proj" / "TODO.md"
        self.todo.parent.mkdir(parents=True)

    def tearDown(self):
        self._patch.stop()
        self._tmpdir.cleanup()

    def _write(self, content):
        self.todo.write_text(content, encoding="utf-8")

    def _read(self):
        return self.todo.read_text(encoding="utf-8")

    # --- update_line ---

    def test_update_replaces_matching_line(self):
        self._write("- [ ] (P1) task one\n- [ ] task two\n")
        td.update_line(str(self.todo), "- [ ] (P1) task one", "- [x] (P1) task one")
        self.assertEqual(self._read(), "- [x] (P1) task one\n- [ ] task two\n")

    def test_update_preserves_other_lines(self):
        self._write("# header\n- [ ] keep me\n- [ ] change me\n")
        td.update_line(str(self.todo), "- [ ] change me", "- [x] change me")
        result = self._read()
        self.assertIn("# header\n", result)
        self.assertIn("- [ ] keep me\n", result)
        self.assertIn("- [x] change me\n", result)

    def test_update_not_found_raises(self):
        self._write("- [ ] only line\n")
        with self.assertRaises(ValueError):
            td.update_line(str(self.todo), "nonexistent line", "replacement")

    # --- delete_line ---

    def test_delete_removes_matching_line(self):
        self._write("- [ ] (P1) keep\n- [ ] delete me\n")
        td.delete_line(str(self.todo), "- [ ] delete me")
        self.assertEqual(self._read(), "- [ ] (P1) keep\n")

    def test_delete_not_found_raises(self):
        self._write("- [ ] only line\n")
        with self.assertRaises(ValueError):
            td.delete_line(str(self.todo), "does not exist")

    # --- add_task ---

    def test_add_with_priority(self):
        self._write("- [ ] existing\n")
        new_line = td.add_task(str(self.todo), "new task", 2)
        self.assertIn("- [ ] (P2) new task\n", self._read())
        self.assertEqual(new_line, "- [ ] (P2) new task")

    def test_add_without_priority(self):
        self._write("- [ ] existing\n")
        new_line = td.add_task(str(self.todo), "no prio", None)
        self.assertIn("- [ ] no prio\n", self._read())
        self.assertEqual(new_line, "- [ ] no prio")

    def test_add_to_empty_file(self):
        self._write("")
        td.add_task(str(self.todo), "first task", 1)
        self.assertEqual(self._read(), "- [ ] (P1) first task\n")

    def test_add_strips_whitespace(self):
        self._write("- [ ] existing\n")
        td.add_task(str(self.todo), "  padded  ", None)
        self.assertIn("- [ ] padded\n", self._read())


# ---------------------------------------------------------------------------
# parse_frontmatter — project + priority 抽出
# ---------------------------------------------------------------------------

class TestParseFrontmatter(unittest.TestCase):

    def _fm(self, text):
        return td.parse_frontmatter(text.splitlines())

    def test_returns_project_and_priority(self):
        fm = self._fm("---\nproject: MyApp\npriority: P2\n---\n")
        self.assertEqual(fm["project"], "MyApp")
        self.assertEqual(fm["priority"], "P2")

    def test_priority_normalised_to_uppercase(self):
        fm = self._fm("---\npriority: p3\n---\n")
        self.assertEqual(fm["priority"], "P3")

    def test_no_frontmatter_returns_none_values(self):
        fm = self._fm("- [ ] task without frontmatter\n")
        self.assertIsNone(fm["project"])
        self.assertIsNone(fm["priority"])

    def test_priority_missing_returns_none(self):
        fm = self._fm("---\nproject: Foo\n---\n")
        self.assertEqual(fm["project"], "Foo")
        self.assertIsNone(fm["priority"])

    def test_extracts_goal(self):
        fm = self._fm("---\nproject: X\ngoal: これはゴールです\n---\n")
        self.assertEqual(fm["goal"], "これはゴールです")

    def test_goal_missing_returns_none(self):
        fm = self._fm("---\nproject: X\npriority: P2\n---\n")
        self.assertIsNone(fm["goal"])

    def test_goal_quotes_stripped(self):
        fm = self._fm('---\ngoal: "quoted goal"\n---\n')
        self.assertEqual(fm["goal"], "quoted goal")


# ---------------------------------------------------------------------------
# update_project_priority — フロントマター書き込み
# ---------------------------------------------------------------------------

class TestProjectPriority(unittest.TestCase):

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self._tmpdir.name).resolve()
        self._patch = patch.object(td, "ROOT", self.root)
        self._patch.start()
        self.todo = self.root / "proj" / "TODO.md"
        self.todo.parent.mkdir(parents=True)

    def tearDown(self):
        self._patch.stop()
        self._tmpdir.cleanup()

    def _write(self, content):
        self.todo.write_text(content, encoding="utf-8")

    def _read(self):
        return self.todo.read_text(encoding="utf-8")

    def test_creates_frontmatter_when_absent(self):
        """フロントマターなしのファイルに priority を書くと先頭に挿入される"""
        self._write("- [ ] task\n")
        td.update_project_priority(str(self.todo), "P1")
        content = self._read()
        self.assertIn("priority: P1", content)
        self.assertTrue(content.startswith("---"))

    def test_modifies_existing_priority(self):
        """既存の priority: を別の値に更新できる"""
        self._write("---\nproject: X\npriority: P3\n---\n- [ ] task\n")
        td.update_project_priority(str(self.todo), "P1")
        content = self._read()
        self.assertIn("priority: P1", content)
        self.assertNotIn("priority: P3", content)

    def test_removes_priority_when_empty(self):
        """空文字を渡すと priority 行が削除される"""
        self._write("---\nproject: X\npriority: P2\n---\n- [ ] task\n")
        td.update_project_priority(str(self.todo), "")
        self.assertNotIn("priority:", self._read())

    def test_rejects_invalid_priority(self):
        """P1〜P4 以外は ValueError"""
        self._write("---\nproject: X\n---\n")
        with self.assertRaises(ValueError):
            td.update_project_priority(str(self.todo), "P5")
        with self.assertRaises(ValueError):
            td.update_project_priority(str(self.todo), "high")


# ---------------------------------------------------------------------------
# update_project_goal — フロントマター書き込み(ゴール)
# ---------------------------------------------------------------------------

class TestProjectGoal(unittest.TestCase):

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self._tmpdir.name).resolve()
        self._patch = patch.object(td, "ROOT", self.root)
        self._patch.start()
        self.todo = self.root / "proj" / "TODO.md"
        self.todo.parent.mkdir(parents=True)

    def tearDown(self):
        self._patch.stop()
        self._tmpdir.cleanup()

    def _write(self, content):
        self.todo.write_text(content, encoding="utf-8")

    def _read(self):
        return self.todo.read_text(encoding="utf-8")

    def test_inserts_goal_into_existing_frontmatter(self):
        """既存フロントマターに goal: が無ければ新規挿入される"""
        self._write("---\nproject: X\n---\n- [ ] task\n")
        td.update_project_goal(str(self.todo), "新しいゴール")
        self.assertIn("goal: 新しいゴール", self._read())

    def test_updates_existing_goal(self):
        """既存の goal: を別の値に更新できる"""
        self._write("---\nproject: X\ngoal: old goal\n---\n- [ ] task\n")
        td.update_project_goal(str(self.todo), "new goal")
        content = self._read()
        self.assertIn("goal: new goal", content)
        self.assertNotIn("old goal", content)

    def test_removes_goal_when_empty(self):
        """空文字を渡すと goal: 行が削除される"""
        self._write("---\nproject: X\ngoal: to be removed\n---\n- [ ] task\n")
        td.update_project_goal(str(self.todo), "")
        self.assertNotIn("goal:", self._read())

    def test_creates_frontmatter_when_absent(self):
        """フロントマターなしのファイルに goal を書くと先頭に挿入される"""
        self._write("- [ ] task\n")
        td.update_project_goal(str(self.todo), "fresh goal")
        content = self._read()
        self.assertTrue(content.startswith("---"))
        self.assertIn("goal: fresh goal", content)

    def test_newline_raises(self):
        """改行を含む goal は ValueError"""
        self._write("---\nproject: X\n---\n")
        with self.assertRaises(ValueError):
            td.update_project_goal(str(self.todo), "line1\nline2")

    def test_over_200_chars_raises(self):
        """201文字以上の goal は ValueError"""
        self._write("---\nproject: X\n---\n")
        with self.assertRaises(ValueError):
            td.update_project_goal(str(self.todo), "a" * 201)


# ---------------------------------------------------------------------------
# scan — projects[].stats / is_root / ソート順
# ---------------------------------------------------------------------------

class TestScanProjectStats(unittest.TestCase):

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self._tmpdir.name).resolve()
        self._patch = patch.object(td, "ROOT", self.root)
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        self._tmpdir.cleanup()

    def test_project_stats_is_root_and_sort_order(self):
        # root 直下の「全体」TODO（is_root のはず）
        (self.root / "TODO.md").write_text(
            "---\nproject: 全体\npriority: P2\n---\n"
            "- [ ] (P1) root task overdue <!-- due:2020-01-01 -->\n"
            "- [x] (P3) root done\n",
            encoding="utf-8",
        )
        # サブプロジェクト A（優先度 P1）
        a_dir = self.root / "proj-a"
        a_dir.mkdir()
        (a_dir / "TODO.md").write_text(
            "---\nproject: ProjA\npriority: P1\n---\n"
            "- [ ] (P1) a task1\n"
            "- [ ] (P2) a task2\n"
            "- [x] a task3 done\n",
            encoding="utf-8",
        )
        # サブプロジェクト B（優先度未設定・フロントマターなし）
        b_dir = self.root / "proj-b"
        b_dir.mkdir()
        (b_dir / "TODO.md").write_text("- [ ] b task open\n", encoding="utf-8")

        data = td.scan(self.root)
        projects = {p["project"]: p for p in data["projects"]}

        # is_root
        self.assertTrue(projects["全体"]["is_root"])
        self.assertFalse(projects["ProjA"]["is_root"])
        self.assertFalse(projects["proj-b"]["is_root"])

        # stats: 全体（total/open/done/p1/overdue）
        root_stats = projects["全体"]["stats"]
        self.assertEqual(root_stats["total"], 2)
        self.assertEqual(root_stats["open"], 1)
        self.assertEqual(root_stats["done"], 1)
        self.assertEqual(root_stats["p1"], 1)
        self.assertEqual(root_stats["overdue"], 1)

        # stats: ProjA
        a_stats = projects["ProjA"]["stats"]
        self.assertEqual(a_stats["total"], 3)
        self.assertEqual(a_stats["open"], 2)
        self.assertEqual(a_stats["done"], 1)
        self.assertEqual(a_stats["p1"], 1)
        self.assertEqual(a_stats["overdue"], 0)

        # stats: proj-b（優先度未設定タスク1件、期限なし）
        b_stats = projects["proj-b"]["stats"]
        self.assertEqual(b_stats["total"], 1)
        self.assertEqual(b_stats["open"], 1)
        self.assertEqual(b_stats["none"], 1)

        # ソート順: is_root -> priority(未設定は最後) -> 名前
        order = [p["project"] for p in data["projects"]]
        self.assertEqual(order[0], "全体")
        self.assertLess(order.index("ProjA"), order.index("proj-b"))


# ---------------------------------------------------------------------------
# build_discord_summary
# ---------------------------------------------------------------------------

class TestBuildDiscordSummary(unittest.TestCase):

    def _make_data(self, tasks, stats=None):
        if stats is None:
            open_count = sum(1 for t in tasks if not t["checked"])
            done_count = sum(1 for t in tasks if t["checked"])
            stats = {
                "open": open_count, "done": done_count,
                "p1": 0, "p2": 0, "p3": 0, "p4": 0, "none": 0,
            }
            for t in tasks:
                if not t["checked"]:
                    key = f"p{t['priority']}" if t["priority"] else "none"
                    stats[key] += 1
        return {"root": ".", "projects": [], "tasks": tasks, "analysis": None, "stats": stats}

    def _task(self, priority, text, project="proj", checked=False, due=None):
        return {
            "id": f"fake::{text}",
            "project": project,
            "file": "fake/TODO.md",
            "lineno": 0,
            "checked": checked,
            "priority": priority,
            "text": text,
            "due": due,
            "raw": "",
        }

    def test_contains_header(self):
        data = self._make_data([])
        result = td.build_discord_summary(data)
        self.assertIn("TODO Dashboard", result)

    def test_p1_task_shown_with_detail(self):
        data = self._make_data([self._task(1, "緊急タスク")])
        result = td.build_discord_summary(data)
        self.assertIn("🔴", result)
        self.assertIn("緊急タスク", result)
        self.assertIn("proj", result)

    def test_p2_task_shown_with_detail(self):
        data = self._make_data([self._task(2, "重要タスク")])
        result = td.build_discord_summary(data)
        self.assertIn("🟠", result)
        self.assertIn("重要タスク", result)

    def test_p3_p4_count_only(self):
        tasks = [self._task(3, "中程度"), self._task(4, "低優先")]
        data = self._make_data(tasks)
        result = td.build_discord_summary(data)
        self.assertIn("🟡", result)
        self.assertIn("🔵", result)
        self.assertNotIn("中程度", result)
        self.assertNotIn("低優先", result)

    def test_due_date_shown(self):
        data = self._make_data([self._task(1, "期限あり", due="2026-07-01")])
        result = td.build_discord_summary(data)
        self.assertIn("2026-07-01", result)

    def test_checked_tasks_excluded(self):
        data = self._make_data([self._task(1, "完了タスク", checked=True)])
        result = td.build_discord_summary(data)
        self.assertNotIn("完了タスク", result)

    def test_stats_line(self):
        tasks = [self._task(1, "open1"), self._task(2, "done1", checked=True)]
        data = self._make_data(tasks)
        result = td.build_discord_summary(data)
        self.assertIn("合計: 2件", result)
        self.assertIn("完了: 1件", result)
        self.assertIn("未完了: 1件", result)

    def test_p1_capped_at_5(self):
        tasks = [self._task(1, f"task{i}") for i in range(7)]
        data = self._make_data(tasks)
        result = td.build_discord_summary(data)
        self.assertIn("他 2件", result)

    def test_no_tasks(self):
        data = self._make_data([])
        result = td.build_discord_summary(data)
        self.assertIn("合計: 0件", result)


if __name__ == "__main__":
    unittest.main()
