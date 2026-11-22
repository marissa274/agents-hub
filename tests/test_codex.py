import json, os, sys, tempfile, time, unittest
from unittest import mock

os.environ["AGENTS_HUB_DATA"] = tempfile.mkdtemp(prefix="hub-codex-data-")  # common crée ce dossier à l'import : jamais ROOT/logs
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "bin"))
from adapters import codex
from common import task_key


class OffsetTest(unittest.TestCase):
    def test_offset_counts_bytes_actually_read(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "r.jsonl")
            with open(p, "w") as f: f.write('{"type":"session_meta","payload":{"id":"abcdef123456"}}\n{"type":"x"}\n')
            n = os.path.getsize(p)
            fl = codex.File(p)
            # le fichier grossit entre la mesure de la taille et la lecture : off ne doit pas dépasser ce qui a été lu
            with mock.patch.object(codex.os.path, "getsize", return_value=n + 100):
                fl.read()
            self.assertEqual(fl.off, n)


class MetaAndUtf8Test(unittest.TestCase):
    META = '{"type":"session_meta","payload":{"id":"abcdef123456","cwd":"/w"}}\n'
    CALL = '{"type":"response_item","payload":{"type":"function_call","name":"sh","arguments":"{\\"cmd\\": \\"caf\u00e9\\"}"}}\n'

    def test_meta_written_after_file_creation(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "r.jsonl")
            open(p, "w").close()
            fl = codex.File(p)
            self.assertEqual(fl.read(), [])
            with open(p, "w") as f: f.write(self.META + self.CALL)
            evs = fl.read()
            self.assertEqual(len(evs), 1)
            self.assertEqual(evs[0]["session"], "ef123456")  # 8 derniers caractères
            self.assertEqual(evs[0]["cwd"], "/w")

    def test_utf8_char_split_between_reads(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "r.jsonl")
            data = (self.META + self.CALL).encode()
            cut = data.index("\u00e9".encode()) + 1  # au milieu du caractère
            with open(p, "wb") as f: f.write(data[:cut])
            fl = codex.File(p)
            evs = fl.read()
            with open(p, "ab") as f: f.write(data[cut:])
            evs += fl.read()
            self.assertEqual(len(evs), 1)
            self.assertIn("\u00e9", evs[0]["detail"])


def write(p, t):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as f: f.write(t)


def U(tail8): return f"019fcab7-7be9-73c1-a013-0123{tail8}"


def meta(**kw): return json.dumps({"type": "session_meta", "payload": kw}) + "\n"


class SessionIdTest(unittest.TestCase):
    def test_session_id_beats_parent_and_id(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "r.jsonl")
            child, root, par = U("c0c0c0c0"), U("a1a1a1a1"), U("b2b2b2b2")
            write(p, meta(id=child, session_id=root, parent_thread_id=par, cwd="/w"))
            self.assertEqual(codex.File(p).session, "a1a1a1a1")
            write(p, meta(id=child, parent_thread_id=par))
            self.assertEqual(codex.File(p).session, "b2b2b2b2")
            write(p, meta(id=child))
            self.assertEqual(codex.File(p).session, "c0c0c0c0")

    def test_uuidv7_same_prefix_gives_different_keys(self):
        a, b = "019fcab7-7be9-73c1-a013-165682ee3abb", "019fcab7-7bea-7f02-9c44-0123456789ab"
        self.assertEqual(a[:8], b[:8])
        self.assertNotEqual(task_key(a, "codex"), task_key(b, "codex"))
        self.assertEqual(task_key(a, "codex"), "5682ee3abb"[-8:])
        self.assertEqual(task_key(a), "019fcab7")  # Claude : 8 premiers, inchangé
        self.assertEqual(task_key(None, "codex"), "")

    def test_same_thread_same_key_everywhere(self):
        """Hook, adaptateur (session, titre, recherche) et score donnent la même clé ; un sous-agent revient à la racine."""
        root, sub = "019fcab7-7be9-73c1-a013-165682ee3abb", "019fcab7-7c00-7aaa-8bbb-0123456789ab"
        key = task_key(root, "codex")
        with tempfile.TemporaryDirectory() as d:
            pr = os.path.join(d, "2026", "01", "02", f"rollout-x-{root}.jsonl"); ps = os.path.join(d, "2026", "01", "02", f"rollout-x-{sub}.jsonl")
            write(pr, meta(id=root, cwd="/w")); write(ps, meta(id=sub, session_id=root, parent_thread_id=root, cwd="/w"))
            idx = os.path.join(d, "session_index.jsonl"); write(idx, json.dumps({"id": root, "thread_name": "Ma tâche"}) + "\n")
            with mock.patch.object(codex, "SESS", d), mock.patch.object(codex, "INDEX", idx), \
                 mock.patch.dict(codex._TITLES, {"sig": None, "off": 0, "map": {}}):
                self.assertEqual(codex.File(pr).session, key)
                self.assertEqual(codex.File(ps).session, key)  # sous-agent : racine
                self.assertEqual(codex.title(key), "Ma tâche")
                self.assertEqual(codex.find_session(key), pr)
                self.assertEqual(task_key(codex.root_session(sub), "codex"), key)


class FindThreadTest(unittest.TestCase):
    def test_find_thread_validates_and_finds(self):
        with tempfile.TemporaryDirectory() as d:
            tid = "019fcab7-7be9-73c1-a013-165682ee3abb"
            p = os.path.join(d, "2026", "01", "02", f"rollout-2026-x-{tid}.jsonl")
            write(p, meta(id=tid, session_id="root0001-y"))
            write(os.path.join(d, "secret.jsonl"), "x")
            with mock.patch.object(codex, "SESS", d):
                self.assertEqual(codex.find_thread(tid), p)
                self.assertEqual(codex.root_session(tid), "root0001-y")
                self.assertEqual(codex.root_session("deadbeef-0000"), "deadbeef-0000")
                for bad in ("../secret", "..", "../../x", "*", "", "abc", "019fcab7/../x", None, 5, "g" * 12, tid + "*"):
                    self.assertEqual(codex.find_thread(bad), "", repr(bad))


class TitleTest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(); self.idx = os.path.join(self.d, "session_index.jsonl")
        self.patches = [mock.patch.object(codex, "INDEX", self.idx), mock.patch.dict(codex._TITLES, {"sig": None, "off": 0, "map": {}})]
        for pt in self.patches: pt.start()
        self.addCleanup(lambda: [pt.stop() for pt in self.patches])
        self.addCleanup(__import__("shutil").rmtree, self.d, True)

    def line(self, i, n): return json.dumps({"id": i, "thread_name": n, "updated_at": "2026"}) + "\n"

    def test_missing_file_and_garbage(self):
        self.assertEqual(codex.title("abcdef12"), "")
        write(self.idx, "pas du json\n[1]\n" + json.dumps({"id": 3, "thread_name": 4}) + "\n")
        self.assertEqual(codex.title("abcdef12"), "")
        self.assertEqual(codex.title(None), "")

    def test_last_line_wins_and_guardian_ignored(self):
        write(self.idx, self.line(U("abcdef12"), "Ancien") + self.line(U("abcdef12"), "Nouveau") + self.line(U("99999999"), "Autre")
              + self.line(U("11112222"), "Guardian review of x"))
        self.assertEqual(codex.title("abcdef12"), "Nouveau")
        self.assertEqual(codex.title("99999999"), "Autre")
        self.assertEqual(codex.title("11112222"), "")

    def test_incremental_cache_and_incomplete_line(self):
        write(self.idx, self.line(U("abcdef12"), "Un"))
        self.assertEqual(codex.title("abcdef12"), "Un")
        with open(self.idx, "a") as f: f.write('{"id":"019fcab7-7be9-73c1-a013-0123abcdef12","thread_na')  # ligne coupée
        self.assertEqual(codex.title("abcdef12"), "Un")
        with open(self.idx, "a") as f: f.write('me":"Deux"}\n')
        self.assertEqual(codex.title("abcdef12"), "Deux")
        calls = []
        real = open
        with mock.patch("builtins.open", side_effect=lambda *a, **k: (calls.append(a), real(*a, **k))[1]):
            self.assertEqual(codex.title("abcdef12"), "Deux")  # fichier inchangé : aucune relecture
        self.assertEqual(calls, [])
        write(self.idx, self.line(U("abcdef12"), "Court"))  # fichier remplacé, plus petit
        self.assertEqual(codex.title("abcdef12"), "Court")


class SpawnDetailTest(unittest.TestCase):
    def test_spawn_agent_detail_names_the_agent(self):
        d = lambda a: codex.tool_detail({"name": "spawn_agent", "arguments": json.dumps(a)})
        self.assertEqual(d({"message": "Analyse le module", "task_name": "analyse"}), "analyse: Analyse le module")
        self.assertEqual(d({"agent_type": "dev", "message": "m", "task_name": "t"}), "dev: m")
        self.assertEqual(d({"message": "Analyse le module"}), "Analyse le module")


class DelayTest(unittest.TestCase):
    def test_adapter_events_are_delayed(self):
        with tempfile.TemporaryDirectory() as d:
            got = []
            codex.STOP.clear()
            with mock.patch.object(codex, "SESS", d), mock.patch.object(codex, "DELAY", 2):
                import threading
                t = threading.Thread(target=codex.loop, args=(lambda evs: got.append((time.time(), evs)),), daemon=True); t.start()
                time.sleep(0.3)
                t0 = time.time()
                write(os.path.join(d, "2026", "01", "01", "rollout-x-" + U("abcdef12") + ".jsonl"), meta(id=U("abcdef12"), cwd="/w") + TOOL)
                time.sleep(1.6)
                self.assertEqual(got, [])  # pas encore émis : le hook a le temps de passer devant
                for _ in range(40):
                    if got: break
                    time.sleep(0.1)
                codex.STOP.set(); t.join(3)
            self.assertTrue(got)
            self.assertGreaterEqual(got[0][0] - t0, 1.9)
            self.assertEqual(got[0][1][0]["session"], "abcdef12")


TOOL = json.dumps({"type": "response_item", "payload": {"type": "function_call", "name": "sh", "arguments": "{}"}}) + "\n"


if __name__ == "__main__":
    unittest.main()
