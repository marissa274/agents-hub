import json, os, shutil, subprocess, sys, tempfile, unittest
from unittest import mock

REPO = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, os.path.join(REPO, "bin"))
import common  # noqa: E402

CLAUDE = "5f3e2a1b-1111-4222-8333-444455556666"
THREAD = "019fcab7-7be9-73c1-a013-165682ee3abb"


class EnvTaskTest(unittest.TestCase):
    def env(self, **kw):
        base = {k: v for k, v in os.environ.items() if k not in ("AGENTS_HUB_SESSION", "CLAUDE_CODE_SESSION_ID", "CODEX_THREAD_ID")}
        return mock.patch.dict(os.environ, {**base, **kw}, clear=True)

    def test_codex_launched_from_a_claude_terminal_uses_codex(self):
        # Codex lancé depuis un terminal de Claude hérite de CLAUDE_CODE_SESSION_ID : c'est Codex qui exécute
        with self.env(CLAUDE_CODE_SESSION_ID=CLAUDE, CODEX_THREAD_ID=THREAD), \
             mock.patch.object(common, "runtime", return_value="codex"), mock.patch.object(common, "codex_root", side_effect=lambda t: t):
            self.assertEqual(common.env_task(), (common.task_key(THREAD, "codex"), "codex", THREAD))

    def test_claude_wins_inside_claude(self):
        with self.env(CLAUDE_CODE_SESSION_ID=CLAUDE, CODEX_THREAD_ID=THREAD), mock.patch.object(common, "runtime", return_value="claude"):
            self.assertEqual(common.env_task(), ("5f3e2a1b", "claude", ""))

    def test_unknown_runtime_keeps_old_order(self):
        with self.env(CLAUDE_CODE_SESSION_ID=CLAUDE, CODEX_THREAD_ID=THREAD), mock.patch.object(common, "runtime", return_value=""):
            self.assertEqual(common.env_task()[0], "5f3e2a1b")

    def test_single_variable_and_override(self):
        with self.env(CODEX_THREAD_ID=THREAD), mock.patch.object(common, "codex_root", side_effect=lambda t: t):
            self.assertEqual(common.env_task()[1], "codex")
        with self.env(AGENTS_HUB_SESSION="hub55555-y", CLAUDE_CODE_SESSION_ID=CLAUDE, CODEX_THREAD_ID=THREAD):
            self.assertEqual(common.env_task()[0], "hub55555")
        with self.env():
            self.assertEqual(common.env_task()[0], "")

    def test_runtime_walks_parents(self):
        tree = {100: (90, "/bin/zsh"), 90: (80, "/usr/local/bin/codex"), 80: (70, "/bin/zsh"), 70: (1, "/x/MacOS/claude")}
        def fake_run(cmd, **kw):
            ppid, comm = tree.get(int(cmd[-1]), (0, ""))
            return subprocess.CompletedProcess(cmd, 0, stdout=f"{ppid} {comm}\n" if comm else "", stderr="")
        with mock.patch("subprocess.run", side_effect=fake_run):
            self.assertEqual(common.runtime(pid=100), "codex")   # le plus proche gagne
            self.assertEqual(common.runtime(pid=80), "claude")
            self.assertEqual(common.runtime(pid=5), "")


class InternalCodexTaskTest(unittest.TestCase):
    def run_hook(self, payload):
        tmp = tempfile.mkdtemp(prefix="hub-rt-"); self.addCleanup(shutil.rmtree, tmp, True)
        env = {k: v for k, v in os.environ.items() if k not in ("CODEX_HOME", "CODEX_THREAD_ID", "CLAUDE_CODE_SESSION_ID", "AGENTS_HUB_SESSION")}
        env.update({"HOME": tmp, "AGENTS_HUB_DATA": tmp, "AGENTS_HUB_NO_WINDOW": "1", "PATH": "/usr/bin:/bin"})
        r = subprocess.run([sys.executable, os.path.join(REPO, "bin", "log_event.py"), "--source", "codex"],
                           input=json.dumps(payload), text=True, capture_output=True, env=env)
        self.assertEqual((r.returncode, r.stdout), (0, ""))
        p = os.path.join(tmp, "events.jsonl")
        return open(p).read().splitlines() if os.path.exists(p) else []

    def test_background_suggestions_are_ignored(self):
        base = {"session_id": THREAD, "hook_event_name": "UserPromptSubmit", "prompt": "# Overview\n\nGenerate 0 to 3 suggestions"}
        self.assertEqual(self.run_hook({**base, "cwd": "/", "transcript_path": None}), [])

    def test_real_tasks_are_kept(self):
        base = {"session_id": THREAD, "hook_event_name": "UserPromptSubmit", "prompt": "corrige"}
        self.assertEqual(len(self.run_hook({**base, "cwd": "/Users/x/projet", "transcript_path": None})), 1)
        self.assertEqual(len(self.run_hook({**base, "cwd": "/", "transcript_path": "/t/r.jsonl"})), 1)


if __name__ == "__main__":
    unittest.main()
