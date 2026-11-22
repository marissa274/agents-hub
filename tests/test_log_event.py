import json, os, runpy, shutil, subprocess, sys, tempfile, unittest
from unittest import mock

REPO = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
SID = "019fcab7-7be9-73c1-a013-165682ee3abb"


class LogEventTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hub-logev-"); self.addCleanup(shutil.rmtree, self.tmp, True)
        self.data = os.path.join(self.tmp, "data")
        self.env = {**os.environ, "HOME": self.tmp, "AGENTS_HUB_DATA": self.data, "AGENTS_HUB_PORT": "1",
                    "PATH": "/usr/bin:/bin", "AGENTS_HUB_NO_WINDOW": "1"}
        for k in ("CODEX_HOME", "CODEX_THREAD_ID", "CLAUDE_CODE_SESSION_ID", "AGENTS_HUB_SESSION", "CLAUDE_CONFIG_DIR"):
            self.env.pop(k, None)

    def run_hook(self, payload, *args, raw=None):
        r = subprocess.run([sys.executable, os.path.join(REPO, "bin", "log_event.py"), *args], env=self.env, capture_output=True, text=True,
                           input=raw if raw is not None else json.dumps(payload))
        return r

    def events(self):
        p = os.path.join(self.data, "events.jsonl")
        if not os.path.exists(p): return []
        with open(p) as f: return [json.loads(l) for l in f]

    def codex(self, payload):
        r = self.run_hook({"session_id": SID, "cwd": "/w", "transcript_path": "/t/r.jsonl", **payload}, "--source", "codex")
        self.assertEqual(r.returncode, 0, r.stderr); self.assertEqual(r.stdout, "")
        evs = self.events()
        return evs[-1] if evs else None

    def test_bash(self):
        e = self.codex({"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": "ls -la"}})
        self.assertEqual((e["event"], e["tool"], e["detail"], e["agent"], e["agent_id"]), ("PreToolUse", "Bash", "ls -la", "codex", ""))
        self.assertEqual((e["session"], e["source"], e["via"], e["cwd"], e["transcript"]), (SID[-8:].replace("-", ""), "codex", "hook", "/w", "/t/r.jsonl"))

    def test_apply_patch_multi_files(self):
        patch = "*** Begin Patch\n*** Add File: a/new.py\n+x\n*** Update File: b.py\n@@\n-x\n+y\n*** Delete File: c.txt\n*** End Patch\n"
        for key in ("command", "input", "patch"):
            e = self.codex({"hook_event_name": "PreToolUse", "tool_name": "apply_patch", "tool_input": {key: patch}})
            self.assertEqual(e["detail"], "a/new.py, b.py, c.txt", key)

    def test_spawn_agent_task_name_only(self):
        # vrais rollouts Codex : {message, task_name} sans agent_type (la carte du sous-agent porte task_name)
        e = self.codex({"hook_event_name": "PreToolUse", "tool_name": "spawn_agent", "tool_input": {"message": "Revois X", "task_name": "race_logic"}})
        self.assertEqual(e["detail"], "race_logic: Revois X")
        e = self.codex({"hook_event_name": "PreToolUse", "tool_name": "spawn_agent", "tool_input": {"message": "Revois X"}})
        self.assertEqual(e["detail"], "Revois X")  # sans nom : pas de préfixe « : », donc pas de carte fantôme

    def test_spawn_agent_and_subagent_events(self):
        e = self.codex({"hook_event_name": "PreToolUse", "tool_name": "spawn_agent", "tool_input": {"agent_type": "reviewer", "message": "relis"}})
        self.assertEqual((e["tool"], e["detail"]), ("spawn_agent", "reviewer: relis"))
        e = self.codex({"hook_event_name": "PreToolUse", "tool_name": "spawn_agent", "tool_input": {"role": "dev", "items": [{"type": "text"}]}})
        self.assertTrue(e["detail"].startswith("dev: "))
        e = self.codex({"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": "pwd"}, "agent_id": "sub-1", "agent_type": "reviewer"})
        self.assertEqual((e["agent"], e["agent_id"], e["transcript"]), ("codex · reviewer", "sub-1", ""))
        e = self.codex({"hook_event_name": "SubagentStart", "agent_id": "sub-1", "agent_type": "reviewer"})
        self.assertEqual((e["event"], e["agent"]), ("SubagentStart", "codex · reviewer"))
        e = self.codex({"hook_event_name": "SubagentStop", "agent_id": "sub-1", "agent_type": "reviewer",
                        "agent_transcript_path": "/t/sub.jsonl", "last_assistant_message": "fini"})
        self.assertEqual((e["event"], e["detail"], e["transcript"]), ("SubagentStop", "fini", "/t/sub.jsonl"))

    def test_user_prompt_of_subagent_ignored(self):
        n = len(self.events())
        self.assertIsNone(self.codex({"hook_event_name": "UserPromptSubmit", "prompt": "x", "agent_id": "sub-1"}))
        self.assertEqual(len(self.events()), n)
        e = self.codex({"hook_event_name": "UserPromptSubmit", "prompt": "bonjour"})
        self.assertEqual((e["event"], e["detail"]), ("UserPromptSubmit", "bonjour"))

    def test_permission_request_becomes_notification(self):
        e = self.codex({"hook_event_name": "PermissionRequest", "tool_name": "Bash", "tool_input": {"command": "rm -rf x"}})
        self.assertEqual((e["event"], e["kind"], e["detail"], e["tool"]), ("Notification", "permission_prompt", "rm -rf x", "Bash"))
        e = self.codex({"hook_event_name": "PermissionRequest", "tool_name": "mcp__x__y", "tool_input": {}})
        self.assertEqual(e["detail"], "mcp__x__y")

    def test_stop_update_plan_mcp_and_null_transcript(self):
        e = self.codex({"hook_event_name": "Stop", "last_assistant_message": "Terminé ?", "transcript_path": None})
        self.assertEqual((e["event"], e["detail"], e["transcript"]), ("Stop", "Terminé ?", ""))
        e = self.codex({"hook_event_name": "PreToolUse", "tool_name": "update_plan", "tool_input": {"plan": [{}, {}, {}]}})
        self.assertEqual(e["detail"], "3 étapes")
        e = self.codex({"hook_event_name": "PreToolUse", "tool_name": "update_plan", "tool_input": {"explanation": "ok", "plan": []}})
        self.assertEqual(e["detail"], "ok")
        e = self.codex({"hook_event_name": "PreToolUse", "tool_name": "mcp__x__y", "tool_input": {"a": 1}})
        self.assertEqual(e["detail"], '{"a": 1}')

    def test_never_fails_never_prints(self):
        for raw in ("", "pas du json", "[1,2]", "null", '{"hook_event_name": 3, "session_id": 4}', '{"hook_event_name":"PreToolUse","session_id":"abc","tool_input":5,"tool_name":[]}'):
            r = self.run_hook(None, "--source", "codex", raw=raw)
            self.assertEqual((r.returncode, r.stdout), (0, ""), raw)
        os.remove(os.path.join(self.data, "events.jsonl"))
        os.makedirs(os.path.join(self.data, "events.jsonl"))  # écriture impossible : toujours code 0
        r = self.run_hook({"session_id": SID, "hook_event_name": "Stop"}, "--source", "codex")
        self.assertEqual((r.returncode, r.stdout), (0, ""))

    def test_claude_payload_unchanged(self):
        r = self.run_hook({"hook_event_name": "PreToolUse", "session_id": "abcdef123456", "tool_name": "Bash", "cwd": "/p",
                           "transcript_path": "/c/x.jsonl", "tool_input": {"command": "ls", "description": "liste"}})
        self.assertEqual((r.returncode, r.stdout), (0, ""))
        e = self.events()[-1]
        self.assertEqual(set(e), {"ts", "event", "session", "agent_id", "agent", "tool", "detail", "kind", "cwd", "transcript"})
        self.assertEqual((e["session"], e["agent"], e["detail"], e["transcript"]), ("abcdef12", "", "liste", "/c/x.jsonl"))
        # un payload Codex sans --source reste traité comme du Claude
        self.run_hook({"hook_event_name": "Notification", "session_id": "abcdef123456", "message": "m", "notification_type": "idle_prompt"})
        e = self.events()[-1]
        self.assertEqual((e["event"], e["detail"], e["kind"]), ("Notification", "m", "idle_prompt"))
        self.assertNotIn("source", e)
        n = len(self.events())
        self.run_hook({"hook_event_name": "SubagentStart", "session_id": "abcdef123456"})  # sous-agent interne : ignoré
        self.assertEqual(len(self.events()), n)

    def test_spawn_agent_with_no_window_does_not_launch(self):
        # AGENTS_HUB_NO_WINDOW=1 (posé par setUp) : ni fenêtre ni serveur ; le lancement réel est à vérifier avec un vrai Codex
        e = self.codex({"hook_event_name": "PreToolUse", "tool_name": "spawn_agent", "tool_input": {"agent_type": "a", "message": "m"}})
        self.assertEqual(e["tool"], "spawn_agent")
        self.assertFalse(os.path.exists(os.path.join(self.data, ".open.lock")))

    def test_spawn_agent_never_opens_a_window_even_without_no_window(self):
        # sans AGENTS_HUB_NO_WINDOW : le hook n'appelle ni Popen ni open_window (exécuté en processus, subprocess mocké)
        env = {k: v for k, v in self.env.items() if k != "AGENTS_HUB_NO_WINDOW"}
        payload = {"hook_event_name": "PreToolUse", "session_id": SID, "tool_name": "spawn_agent",
                   "tool_input": {"agent_type": "a", "message": "m"}}
        popen = mock.Mock(side_effect=AssertionError("Popen interdit"))
        with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(sys, "argv", ["log_event.py", "--source", "codex"]), \
             mock.patch.object(sys, "stdin", __import__("io").StringIO(json.dumps(payload))), \
             mock.patch("subprocess.Popen", popen), mock.patch("subprocess.run", popen), \
             mock.patch("common.EV", os.path.join(self.data, "events.jsonl")):
            os.makedirs(self.data, exist_ok=True)
            with self.assertRaises(SystemExit) as cm: runpy.run_path(os.path.join(REPO, "bin", "log_event.py"), run_name="__main__")
        self.assertEqual(cm.exception.code, 0)
        popen.assert_not_called()
        self.assertEqual(self.events()[-1]["tool"], "spawn_agent")  # l'activité est bien enregistrée
        with open(os.path.join(REPO, "bin", "log_event.py")) as f: self.assertNotIn("open_window", f.read())


if __name__ == "__main__":
    unittest.main()
