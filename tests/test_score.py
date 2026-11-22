import os, shutil, subprocess, sys, tempfile, unittest

REPO = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))


class ScoreTest(unittest.TestCase):
    def run_add(self, sev):
        tmp = tempfile.mkdtemp(prefix="hub-score-"); self.addCleanup(shutil.rmtree, tmp, True)
        env = {**os.environ, "AGENTS_HUB_DATA": tmp}
        return subprocess.run([sys.executable, os.path.join(REPO, "bin", "score.py"), "add", "--cycle", "1",
                               "--severity", sev, "--title", "t"], env=env, capture_output=True, text=True, cwd=tmp)

    def test_known_severity(self): self.assertEqual(self.run_add("majeur").returncode, 0)

    def test_unknown_severity_refused(self):
        r = self.run_add('x"><script>'); self.assertNotEqual(r.returncode, 0)
        self.assertIn("Sévérité invalide", r.stderr)

    def run_raw(self, *args):
        tmp = tempfile.mkdtemp(prefix="hub-score-"); self.addCleanup(shutil.rmtree, tmp, True)
        env = {**os.environ, "AGENTS_HUB_DATA": tmp}
        return subprocess.run([sys.executable, os.path.join(REPO, "bin", "score.py"), "add", "--severity", "majeur", *args],
                              env=env, capture_output=True, text=True, cwd=tmp)

    def test_cycle_required_and_validated(self):
        for args in ((), ("--cycle", "deux"), ("--cycle", "7")):
            r = self.run_raw(*args)
            self.assertEqual(r.returncode, 2, args)
            self.assertNotIn("Traceback", r.stderr)
        self.assertEqual(self.run_raw("--cycle", "2").returncode, 0)

    def test_bugs_belong_to_their_task(self):
        # deux tâches du même projet : chacune ne voit, ne compte et ne remet à zéro que ses bugs
        tmp = tempfile.mkdtemp(prefix="hub-score-"); self.addCleanup(shutil.rmtree, tmp, True)
        def run(sid, *args):
            env = {**os.environ, "AGENTS_HUB_DATA": tmp, "CLAUDE_CODE_SESSION_ID": sid}
            env.pop("AGENTS_HUB_SESSION", None)
            return subprocess.run([sys.executable, os.path.join(REPO, "bin", "score.py"), *args],
                                  env=env, capture_output=True, text=True, cwd=tmp).stdout
        run("aaaa1111-x", "add", "--cycle", "1", "--severity", "majeur", "--title", "ui")
        run("bbbb2222-y", "add", "--cycle", "1", "--severity", "critique", "--title", "archi")
        self.assertIn("5 pts", run("aaaa1111-x", "total"))
        self.assertIn("10 pts", run("bbbb2222-y", "total"))
        self.assertIn("C1-B1", run("bbbb2222-y", "list"))  # numérotation propre à chaque tâche
        run("aaaa1111-x", "reset")
        self.assertIn("0 pts", run("aaaa1111-x", "total"))
        self.assertIn("10 pts", run("bbbb2222-y", "total"))


if __name__ == "__main__":
    unittest.main()
