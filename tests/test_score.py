import json, os, shutil, subprocess, sys, tempfile, unittest

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

    def test_codex_thread_resolves_to_root_task(self):
        tmp = tempfile.mkdtemp(prefix="hub-score-"); self.addCleanup(shutil.rmtree, tmp, True)
        codex = os.path.join(tmp, "codex"); d = os.path.join(codex, "sessions", "2026", "01", "01"); os.makedirs(d)
        root_tid, sub_tid, lost_tid = "aaaa1111-0000-0000-0000-000000000000", "bbbb2222-0000-0000-0000-000000000000", "cccc3333-0000-0000-0000-000000000000"
        for tid, meta in ((root_tid, {"id": root_tid}), (sub_tid, {"id": sub_tid, "session_id": root_tid, "parent_thread_id": "zzzz9999-x"})):
            with open(os.path.join(d, f"rollout-x-{tid}.jsonl"), "w") as f: f.write(json.dumps({"type": "session_meta", "payload": meta}) + "\n")
        def run(extra, *args):
            env = {**os.environ, "AGENTS_HUB_DATA": os.path.join(tmp, "data"), "CODEX_HOME": codex, "PATH": "/usr/bin:/bin"}
            for k in ("CODEX_THREAD_ID", "CLAUDE_CODE_SESSION_ID", "AGENTS_HUB_SESSION", "CLAUDE_CONFIG_DIR"): env.pop(k, None)
            env.update(extra)
            return subprocess.run([sys.executable, os.path.join(REPO, "bin", "score.py"), *args], env=env, capture_output=True, text=True, cwd=tmp)
        add = ("add", "--cycle", "1", "--severity", "majeur", "--title", "t")
        self.assertEqual(run({"CODEX_THREAD_ID": root_tid}, *add).returncode, 0)   # orchestrateur : son propre id
        self.assertEqual(run({"CODEX_THREAD_ID": sub_tid}, *add).returncode, 0)    # sous-agent : tâche racine
        self.assertEqual(run({"CODEX_THREAD_ID": lost_tid}, *add).returncode, 0)   # rollout introuvable : son id
        with open(os.path.join(tmp, "data", "scores.json")) as f: bugs = json.load(f)["bugs"]
        self.assertEqual([b["session"] for b in bugs], ["aaaa1111", "aaaa1111", "cccc3333"])
        self.assertEqual([b["thread"] for b in bugs], [root_tid, sub_tid, lost_tid])
        self.assertEqual([b["id"] for b in bugs], ["C1-B1", "C1-B2", "C1-B1"])  # la numérotation est celle de la tâche racine
        self.assertIn("10 pts", run({"CODEX_THREAD_ID": sub_tid}, "total").stdout)
        self.assertIn("0 pts", run({"CODEX_THREAD_ID": root_tid}, "reset", ).stdout + run({"CODEX_THREAD_ID": root_tid}, "total").stdout)
        self.assertIn("5 pts", run({"CODEX_THREAD_ID": lost_tid}, "total").stdout)
        # CLAUDE_CODE_SESSION_ID et AGENTS_HUB_SESSION passent avant CODEX_THREAD_ID
        run({"CLAUDE_CODE_SESSION_ID": "claude77-x", "CODEX_THREAD_ID": root_tid}, *add)
        with open(os.path.join(tmp, "data", "scores.json")) as f: bugs = json.load(f)["bugs"]
        self.assertEqual(bugs[-1]["session"], "claude77"); self.assertNotIn("thread", bugs[-1])
        r = run({"CLAUDE_CODE_SESSION_ID": "claude77-x", "AGENTS_HUB_SESSION": "hub55555-y"}, *add)
        with open(os.path.join(tmp, "data", "scores.json")) as f: self.assertEqual(json.load(f)["bugs"][-1]["session"], "hub55555")
        self.assertEqual(run({"CODEX_THREAD_ID": "../../x"}, *add).returncode, 0)  # id invalide : jamais de lecture hors sessions


if __name__ == "__main__":
    unittest.main()
