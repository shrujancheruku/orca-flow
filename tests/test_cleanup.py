import os
import subprocess
import tempfile
import unittest

from flowlib import cleanup


def git(args, cwd):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com"] + args, cwd=cwd, check=True,
                   capture_output=True)


class VerdictTest(unittest.TestCase):
    def test_only_a_clean_pushed_worktree_is_removed(self):
        self.assertEqual(cleanup.verdict(True, False, [], ["origin/main"]), (True, "remove (HEAD is on origin/main)"))
        self.assertFalse(cleanup.verdict(True, False, ["a.txt"], ["origin/main"])[0])
        self.assertIn("no remote branch", cleanup.verdict(True, False, [], [])[1])
        self.assertIn("own checkout", cleanup.verdict(True, True, [], ["origin/main"])[1])
        self.assertEqual(cleanup.verdict(False, False, [], []), (False, "already gone"))

    def test_paths_come_from_orcas_workspace_once_each(self):
        workers = [{"workspace": "repo::/w/12-a"}, {"workspace": "repo::/w/12-a"}, {"workspace": "repo::/w/13-b"},
                   {"worktree": "/w/14-c"}, {}]
        self.assertEqual(cleanup.worktree_paths(workers), ["/w/12-a", "/w/13-b", "/w/14-c"])


class RealGitTest(unittest.TestCase):
    """Against a real repo with a bare remote: git is what decides, so it is what is tested."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.remote = os.path.join(self.tmp, "remote.git")
        self.repo = os.path.join(self.tmp, "repo")
        subprocess.run(["git", "init", "-q", "--bare", self.remote], check=True)
        subprocess.run(["git", "init", "-q", "-b", "main", self.repo], check=True)
        open(os.path.join(self.repo, "a.txt"), "w").write("a\n")
        git(["add", "a.txt"], self.repo)
        git(["commit", "-q", "-m", "one"], self.repo)
        git(["remote", "add", "origin", self.remote], self.repo)
        git(["push", "-q", "origin", "main"], self.repo)

    def worktree(self, name):
        path = os.path.join(self.tmp, name)
        git(["worktree", "add", "-q", "-b", name, path, "main"], self.repo)
        return path

    def test_a_clean_pushed_worktree_goes_and_its_branch_stays(self):
        path = self.worktree("t1")
        self.assertTrue(cleanup.inspect(path, self.repo)[0])
        self.assertEqual(cleanup.remove(path, self.repo), (True, "removed"))
        self.assertFalse(os.path.exists(path))
        self.assertEqual(cleanup.run_git(["rev-parse", "--verify", "-q", "t1"], self.repo)[0], 0)
        self.assertEqual(cleanup.inspect(path, self.repo), (False, "already gone"))

    def test_an_unpushed_commit_keeps_the_worktree(self):
        path = self.worktree("t2")
        open(os.path.join(path, "b.txt"), "w").write("b\n")
        git(["add", "b.txt"], path)
        git(["commit", "-q", "-m", "two"], path)
        go, why = cleanup.inspect(path, self.repo)
        self.assertFalse(go)
        self.assertIn("no remote branch", why)

    def test_an_uncommitted_file_keeps_the_worktree(self):
        path = self.worktree("t3")
        open(os.path.join(path, "c.txt"), "w").write("c\n")
        go, why = cleanup.inspect(path, self.repo)
        self.assertFalse(go)
        self.assertIn("c.txt", why)
        self.assertFalse(cleanup.remove(path, self.repo)[0])
        self.assertTrue(os.path.exists(path))

    def test_the_repos_own_checkout_is_never_removed(self):
        self.assertIn("own checkout", cleanup.inspect(self.repo, self.repo)[1])


if __name__ == "__main__":
    unittest.main()
