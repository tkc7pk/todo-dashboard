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


if __name__ == "__main__":
    unittest.main()
