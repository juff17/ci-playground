import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools import scenario


def load(code):
    ns = {}
    exec(compile(code, "<scenario>", "exec"), ns)
    return ns


class FilesTest(unittest.TestCase):
    def test_every_kind_writes_valid_python_into_sandbox(self):
        for kind in scenario.KINDS:
            files = scenario.scenario_files(kind, f"{kind}-abc", f"scn/{kind}-abc")
            for path, text in files.items():
                self.assertTrue(path.startswith(("sandbox/", ".ci/scenarios/")), path)
                if path.endswith(".py"):
                    compile(text, path, "exec")

    def test_switches_file_is_named_for_the_branch(self):
        files = scenario.scenario_files("slow", "slow-abc", "scn/slow-abc", minutes=3)
        self.assertIn("\nslow 3\n", files[".ci/scenarios/scn/slow-abc"])
        self.assertNotIn(".ci/scenarios/scn/happy-abc", scenario.scenario_files("happy", "happy-abc", "scn/happy-abc"))

    def test_passing_code_passes_and_buggy_code_fails(self):
        self.assertEqual(load(scenario.MODULE_OK)["clamp"](5, 0, 3), 3)
        self.assertNotEqual(load(scenario.MODULE_BUG)["last_n"]([1, 2, 3, 4], 2), [3, 4])
        self.assertEqual(load(scenario.MODULE_REVIEW)["spread"]([3, 9, 4]), 6)
        self.assertIn("occured", scenario.MODULE_REVIEW)

    def test_module_name_is_an_identifier(self):
        self.assertTrue(scenario.module_name("conflict-s07-k3x9ab").isidentifier())


class SlotsTest(unittest.TestCase):
    def test_set_slot_rewrites_one_line(self):
        text = scenario.set_slot(scenario.fresh_hotspot(), 7, "claimed by scn/x")
        self.assertEqual(scenario.slots(text)[7], "claimed by scn/x")
        self.assertEqual(sum(v == "free" for v in scenario.slots(text).values()), scenario.SLOTS - 1)

    def test_fresh_hotspot_matches_the_file(self):
        self.assertEqual((scenario.ROOT / scenario.HOTSPOT).read_text(), scenario.fresh_hotspot())

    def test_slot_of_branch(self):
        self.assertEqual(scenario.slot_of("scn/conflict-s07-k3x9ab"), 7)
        self.assertIsNone(scenario.slot_of("scn/happy-k3x9ab"))

    def test_pick_slot_skips_taken_and_claimed(self):
        text = scenario.fresh_hotspot()
        for n in range(2, scenario.SLOTS + 1):
            text = scenario.set_slot(text, n, "taken on main")
        self.assertEqual(scenario.pick_slot(text, []), 1)
        with self.assertRaises(scenario.Fail):
            scenario.pick_slot(text, ["scn/conflict-s01-abc"])


class CommitTest(unittest.TestCase):
    def test_commit_leaves_the_working_tree_alone(self):
        with tempfile.TemporaryDirectory() as d:
            env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
            run = lambda *a: subprocess.run(["git", *a], cwd=d, env=env, check=True, capture_output=True, text=True).stdout.strip()
            run("init", "-q", "-b", "main")
            Path(d, "keep.txt").write_text("keep\n")
            Path(d, "gone.txt").write_text("gone\n")
            run("add", ".")
            run("commit", "-q", "-m", "init")
            head = run("rev-parse", "HEAD")
            with mock.patch.object(scenario, "ROOT", Path(d)), mock.patch.dict(os.environ, env):
                sha = scenario.commit(head, {"sandbox/new.py": "x = 1\n", "gone.txt": None}, "scenario")
            self.assertEqual(run("rev-parse", "HEAD"), head)
            self.assertEqual(run("status", "--porcelain"), "")
            self.assertEqual(run("ls-tree", "-r", "--name-only", sha).split(), ["keep.txt", "sandbox/new.py"])
            self.assertEqual(run("rev-parse", f"{sha}^"), head)


class ParserTest(unittest.TestCase):
    def test_every_command_parses(self):
        p = scenario.parser()
        for argv in (["new", "conflict", "--now"], ["fleet", "--add", "slow", "stuck"], ["advance", "--quiet"],
                     ["collide", "12"], ["review", "12", "nit"], ["merge", "12"], ["pipeline", "late-fail"],
                     ["list"], ["cleanup", "--prune", "-y"], ["setup"]):
            p.parse_args(argv)


if __name__ == "__main__":
    unittest.main()
