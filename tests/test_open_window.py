import contextlib, io, json, os, sys, tempfile, unittest
from unittest import mock

# avant l'import : les chemins du Hub pointent vers un dossier temporaire
_tmp = tempfile.mkdtemp(prefix="hub-ow-")
os.environ["AGENTS_HUB_DATA"] = os.path.join(_tmp, "data")
os.environ["AGENTS_HUB_PORT"] = "7799"
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "bin"))
import open_window as ow


class ShouldOpen(unittest.TestCase):
    def test_no_window_opens(self): self.assertTrue(ow.should_open(0, 60, 0, 1000))
    def test_window_present(self): self.assertFalse(ow.should_open(1, 60, 0, 1000))
    def test_burst_guard(self):
        self.assertFalse(ow.should_open(0, 60, 990, 1000))
        self.assertTrue(ow.should_open(0, 60, 970, 1000))
    def test_server_just_started(self): self.assertFalse(ow.should_open(0, 2, 0, 1000))

    def test_session_already_shown(self):
        self.assertFalse(ow.should_open(1, 60, 0, 1000, "abc", {"abc": 1}))
        self.assertFalse(ow.should_open(2, 60, 0, 1000, "abc", {"abc": 2, "def": 1}))

    def test_other_session_shown_opens(self):
        self.assertTrue(ow.should_open(1, 60, 0, 1000, "abc", {"def": 1}))

    def test_session_grace_is_per_task(self):
        self.assertFalse(ow.should_open(1, 60, 990, 1000, "abc", {"def": 1}))   # abc vient d'être ouverte
        self.assertTrue(ow.should_open(1, 60, 970, 1000, "abc", {"def": 1}))    # grâce écoulée
        # une autre tâche ouverte il y a 10 s (last_any) ne bloque pas au-delà de la garde globale
        self.assertTrue(ow.should_open(1, 60, 0, 1000, "abc", {"def": 1}, 990))

    def test_global_guard(self):
        self.assertFalse(ow.should_open(1, 60, 0, 1000, "abc", {"def": 1}, 998))
        self.assertTrue(ow.should_open(1, 60, 0, 1000, "abc", {"def": 1}, 996))
        self.assertFalse(ow.should_open(0, 60, 0, 1000, "", None, 998))

    def test_session_server_just_started(self):
        self.assertFalse(ow.should_open(0, 2, 0, 1000, "abc", {}))

    def test_clean_sid(self):
        self.assertEqual(ow.clean_sid("ab-cd/ef12gh34ij"), "abcdef12")
        self.assertEqual(ow.clean_sid(None), "")


class Launch(unittest.TestCase):
    URL = "http://127.0.0.1:7799/"

    def run_launch(self, system, env, which=None, chrome_rc=0):
        run = mock.Mock(return_value=mock.Mock(returncode=chrome_rc))
        popen = mock.Mock()
        wb = mock.Mock()
        with mock.patch.object(ow.platform, "system", return_value=system), \
             mock.patch.object(ow.subprocess, "run", run), mock.patch.object(ow.subprocess, "Popen", popen), \
             mock.patch.object(ow.shutil, "which", side_effect=lambda n: (which or {}).get(n)), \
             mock.patch.dict(os.environ, env, clear=True), mock.patch("webbrowser.open", wb), \
             contextlib.redirect_stderr(io.StringIO()):
            res = ow.launch(self.URL)
        return res, run, popen, wb

    def test_mac_chrome(self):
        res, run, popen, wb = self.run_launch("Darwin", {})
        self.assertEqual(res, "chrome")
        self.assertEqual(run.call_args_list[0].args[0], ["open", "-Ra", "Google Chrome"])
        self.assertEqual(run.call_args_list[1].args[0],
                         ["open", "-na", "Google Chrome", "--args", f"--app={self.URL}", "--window-size=1440,920"])
        wb.assert_not_called()

    def test_mac_without_chrome(self):
        res, run, popen, wb = self.run_launch("Darwin", {}, chrome_rc=1)
        self.assertEqual(res, "webbrowser"); wb.assert_called_once_with(self.URL); self.assertEqual(run.call_count, 1)

    def test_linux_headless(self):
        res, run, popen, wb = self.run_launch("Linux", {}, which={"chromium": "/usr/bin/chromium"})
        self.assertEqual(res, "none")
        popen.assert_not_called(); wb.assert_not_called()

    def test_linux_first_browser_in_order(self):
        res, run, popen, wb = self.run_launch("Linux", {"DISPLAY": ":0"},
                                              which={"chromium": "/usr/bin/chromium", "brave-browser": "/usr/bin/brave"})
        self.assertEqual(res, "chromium")
        self.assertEqual(popen.call_args.args[0][:2], ["/usr/bin/chromium", f"--app={self.URL}"])

    def test_linux_wayland_no_chrome(self):
        res, run, popen, wb = self.run_launch("Linux", {"WAYLAND_DISPLAY": "wayland-0"})
        self.assertEqual(res, "webbrowser"); wb.assert_called_once_with(self.URL)


class Hook(unittest.TestCase):
    def test_hook_is_a_silent_noop(self):
        out = io.StringIO()
        with mock.patch.object(ow.subprocess, "Popen", side_effect=AssertionError("rien à lancer")), \
             mock.patch.object(ow, "launch", side_effect=AssertionError("pas de fenêtre")), \
             mock.patch.object(ow, "port_open", side_effect=AssertionError("pas de travail dans le hook")), \
             mock.patch.object(ow.sys, "stdin", io.StringIO('{"session_id": "abc"}')), contextlib.redirect_stdout(out):
            self.assertEqual(ow.main(["--hook"]), 0)
        self.assertEqual(out.getvalue(), "")


class MainSession(unittest.TestCase):
    def setUp(self): self.out = io.StringIO()

    def run_main(self, argv, win, last=None):
        launched = []
        with mock.patch.object(ow, "port_open", return_value=True), mock.patch.object(ow, "windows", return_value=win), \
             mock.patch.object(ow, "launch", side_effect=launched.append), mock.patch.object(ow.time, "sleep"), \
             mock.patch.object(ow, "LAST", os.path.join(_tmp, "last-%d.json" % id(launched))), \
             contextlib.redirect_stdout(self.out):
            if last is not None:
                with open(ow.LAST, "w") as f: f.write(last)
            rc = ow.main(argv)
        return rc, launched

    def test_session_opens_pinned_url(self):
        rc, l = self.run_main(["session", "abc12345"], (1, 60, {"zzz": 1}, 1))
        self.assertEqual((rc, l), (0, [ow.URL + "#s-abc12345"]))

    def test_session_already_shown_does_not_open(self):
        self.assertEqual(self.run_main(["session", "abc12345"], (1, 60, {"abc12345": 1}, 1))[1], [])

    def test_no_arg_picks_session_from_claude_then_codex_root_then_auto(self):
        win = (0, 60, {}, 0)
        codex = os.path.join(_tmp, "codex"); d = os.path.join(codex, "sessions", "2026", "01", "02"); os.makedirs(d, exist_ok=True)
        tid = "0000aaaa-1111-2222-3333-444455556666"
        with open(os.path.join(d, f"rollout-x-{tid}.jsonl"), "w") as f:
            f.write(json.dumps({"payload": {"id": tid, "session_id": "01234567-89ab-7cde-8f01-2345aaaa9999", "parent_thread_id": "p"}}) + "\n")
        def run(env):
            with mock.patch.dict(os.environ, env), mock.patch.object(ow, "codex_root", wraps=ow.codex_root), \
                 mock.patch("common.CODEX", codex):
                return self.run_main([], win)[1]
        for k in ("CLAUDE_CODE_SESSION_ID", "CODEX_THREAD_ID"): os.environ.pop(k, None)
        self.assertEqual(run({"CLAUDE_CODE_SESSION_ID": "ab-cd12-34ef-9"}), [ow.URL + "#s-abcd1234"])
        self.assertEqual(run({"CLAUDE_CODE_SESSION_ID": "ab-cd12-34ef-9", "CODEX_THREAD_ID": tid}), [ow.URL + "#s-abcd1234"])
        self.assertEqual(run({"CODEX_THREAD_ID": tid}), [ow.URL + "#s-aaaa9999"])  # tâche racine, pas le fil
        self.assertEqual(run({"CODEX_THREAD_ID": "ffeeddcc-0000-7000-8000-123456789abc"}), [ow.URL + "#s-56789abc"])  # rollout introuvable : le fil lui-même
        self.assertEqual(run({}), [ow.URL])
        with mock.patch.dict(os.environ, {"CLAUDE_CODE_SESSION_ID": "abcd1234"}):
            self.assertEqual(self.run_main(["--auto"], win)[1], [ow.URL])  # --auto force le mode auto

    def test_already_open_for_this_task_says_so(self):
        with mock.patch.dict(os.environ, {"CLAUDE_CODE_SESSION_ID": "abcd1234"}):
            rc, l = self.run_main([], (1, 60, {"abcd1234": 1}, 1))
        self.assertEqual((rc, l), (0, []))
        self.assertEqual(self.out.getvalue(), "Agents Hub est déjà ouvert pour cette tâche.\n")

    def test_grace_explicit_call_says_it_is_opening(self):
        import json, time
        last = json.dumps({"abc12345": time.time() - 5})
        rc, l = self.run_main(["session", "abc12345"], (0, 60, {}, 0), last)
        self.assertEqual((rc, l), (0, []))  # anti-doublon conservé
        self.assertEqual(self.out.getvalue(), "Agents Hub est en train de s'ouvrir… si rien n'apparaît, réessaie dans quelques secondes.\n")

    def test_auto_url_without_pin(self):
        self.assertEqual(self.run_main(["auto"], (0, 60, {}, 0))[1], [ow.URL])
        self.assertEqual(self.run_main(["auto"], (1, 60, {"x": 1}, 1))[1], [])

    def test_server_restart_waits_then_rereads(self):
        wins = mock.Mock(side_effect=[(0, 1, {}, 0), (1, 6, {"abc12345": 1}, 1)])
        with mock.patch.object(ow, "windows", wins), mock.patch.object(ow, "port_open", return_value=True), \
             mock.patch.object(ow, "launch") as launch, mock.patch.object(ow.time, "sleep") as sl, \
             mock.patch.object(ow, "LAST", os.path.join(_tmp, "last-r.json")):
            ow.main(["session", "abc12345"])
        sl.assert_called_once(); self.assertEqual(wins.call_count, 2); launch.assert_not_called()

    def test_recent_open_blocks_same_task_only(self):
        import json, time
        last = json.dumps({"abc12345": time.time() - 5})
        self.assertEqual(self.run_main(["session", "abc12345"], (1, 60, {"z": 1}, 1), last)[1], [])
        self.assertEqual(len(self.run_main(["session", "def67890"], (1, 60, {"z": 1}, 1), last)[1]), 1)

    def test_auto_ignores_pinned_windows(self):
        # C3-B3 : une fenêtre épinglée (n=1, unpinned=0) ne bloque pas « hub --auto »
        self.assertEqual(self.run_main(["auto"], (1, 60, {"x": 1}, 0))[1], [ow.URL])
        self.assertEqual(self.run_main(["auto"], (2, 60, {"x": 1}, 1))[1], [])

    def test_should_open_auto_counts_given_unpinned(self):
        self.assertTrue(ow.should_open(0, 60, 0, 1000))


class FakeClock:
    def __init__(self, t): self.t = t; self.sleeps = []
    def time(self): return self.t
    def sleep(self, d): self.sleeps.append(d); self.t += d


class Simulated(unittest.TestCase):
    """Temps simulé : aucune attente réelle."""
    def setUp(self):
        self.clock = FakeClock(10000.0)
        self.last = os.path.join(_tmp, "last-sim-%d.json" % id(self))
        self.launched = []
        self.patches = [mock.patch.object(ow.time, "time", self.clock.time), mock.patch.object(ow.time, "sleep", self.clock.sleep),
                        mock.patch.object(ow, "port_open", return_value=True), mock.patch.object(ow, "LAST", self.last),
                        mock.patch.object(ow, "launch", side_effect=self.launched.append)]
        self.patches.append(contextlib.redirect_stdout(io.StringIO()))
        for p in self.patches: p.__enter__() if isinstance(p, contextlib.redirect_stdout) else p.start()
        self.addCleanup(lambda: [p.__exit__(None, None, None) if isinstance(p, contextlib.redirect_stdout) else p.stop() for p in self.patches])

    def run_main(self, argv, win):
        with mock.patch.object(ow, "windows", side_effect=win if callable(win) else (lambda: win)):
            return ow.main(argv)

    def test_second_task_one_second_later_gets_its_window(self):
        # C3-B1 : A à t, B à t+1 s : B attend la fin de la garde globale puis ouvre sa fenêtre
        self.run_main(["session", "aaaa1111"], (0, 60, {}, 0))
        self.clock.t += 1
        t_b = self.clock.t
        self.run_main(["session", "bbbb2222"], lambda: (1, 60, {"aaaa1111": 1}, 1))
        self.assertEqual(self.launched, [ow.URL + "#s-aaaa1111", ow.URL + "#s-bbbb2222"])
        self.assertAlmostEqual(self.clock.t - t_b, ow.GLOBAL_GUARD - 1, places=3)

    def test_global_guard_wait_then_task_shown_does_not_open(self):
        # pendant l'attente, la fenêtre de B se déclare : pas de doublon
        self.run_main(["session", "aaaa1111"], (0, 60, {}, 0))
        self.clock.t += 1
        calls = []
        def win():
            calls.append(1)
            return (2, 60, {"aaaa1111": 1, "bbbb2222": 1}, 2)
        self.run_main(["session", "bbbb2222"], win)
        self.assertEqual(len(self.launched), 1)

    def test_auto_window_slow_to_declare_no_duplicate_for_hook(self):
        # C3-B2 : /hub ouvre une fenêtre auto à t0 ; elle se déclare à t0+6 s ; le hook de la même tâche à t0+4 s
        t0 = self.clock.t
        self.run_main(["auto"], (0, 60, {}, 0))
        self.assertEqual(self.launched, [ow.URL])
        self.clock.t = t0 + 4
        def win():
            return (1, 60, {"aaaa1111": 1}, 1) if self.clock.t >= t0 + 6 else (0, 60, {}, 0)
        self.run_main(["session", "aaaa1111"], win)
        self.assertEqual(self.launched, [ow.URL])
        self.assertLess(self.clock.t - t0, ow.GRACE)

    def test_auto_window_never_declares_hook_opens_after_grace(self):
        t0 = self.clock.t
        self.run_main(["auto"], (0, 60, {}, 0))
        self.clock.t = t0 + 4
        self.run_main(["session", "aaaa1111"], (0, 60, {}, 0))
        self.assertEqual(self.launched, [ow.URL, ow.URL + "#s-aaaa1111"])
        self.assertGreaterEqual(self.clock.t - t0, ow.GRACE)

    def test_auto_window_showing_other_task_hook_opens_its_own(self):
        t0 = self.clock.t
        self.run_main(["auto"], (0, 60, {}, 0))
        self.clock.t = t0 + 4
        self.run_main(["session", "bbbb2222"], lambda: (1, 60, {"aaaa1111": 1}, 1))
        self.assertEqual(self.launched[-1], ow.URL + "#s-bbbb2222")


if __name__ == "__main__":
    unittest.main()
