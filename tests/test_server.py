import http.client, json, os, shutil, socket, subprocess, sys, tempfile, time, unittest

REPO = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))


def read(p):
    with open(p) as f: return f.read()


def write(p, t):
    with open(p, "w") as f: f.write(t)


def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


class ServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="hub-server-")
        cls.home = os.path.join(cls.tmp, "home"); os.makedirs(cls.home)
        cls.port = free_port()
        env = {**os.environ, "HOME": cls.home, "AGENTS_HUB_DATA": os.path.join(cls.tmp, "data"), "AGENTS_HUB_PORT": str(cls.port)}
        env.pop("CLAUDE_CONFIG_DIR", None)
        cls.errfile = os.path.join(cls.tmp, "stderr.txt")
        cls.err = open(cls.errfile, "w")
        cls.proc = subprocess.Popen([sys.executable, os.path.join(REPO, "bin", "server.py")], env=env,
                                    stdout=subprocess.DEVNULL, stderr=cls.err)
        for _ in range(50):
            try: socket.create_connection(("127.0.0.1", cls.port), 0.2).close(); break
            except OSError: time.sleep(0.1)
        else: raise RuntimeError("le serveur ne démarre pas")

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate(); cls.proc.wait(5); cls.err.close()
        shutil.rmtree(cls.tmp, True)

    def get(self, path, host=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        c.putrequest("GET", path, skip_host=True)
        c.putheader("Host", host or f"127.0.0.1:{self.port}"); c.endheaders()
        r = c.getresponse(); body = r.read(); c.close()
        return r, body

    def test_index_has_theme_switch(self):
        r, body = self.get("/")
        self.assertEqual(r.status, 200)
        self.assertEqual(r.getheader("X-Content-Type-Options"), "nosniff")
        self.assertIsNone(r.getheader("Access-Control-Allow-Origin"))
        self.assertIn(b'aria-label="Th', body)
        self.assertEqual(self.get("/index.html")[0].status, 200)
        self.assertEqual(self.get("/", host=f"localhost:{self.port}")[0].status, 200)

    def test_bad_host_forbidden(self):
        self.assertEqual(self.get("/", host="evil.com")[0].status, 403)
        self.assertEqual(self.get("/api/agents", host=f"evil.com:{self.port}")[0].status, 403)
        self.assertEqual(self.get("/api/events", host="127.0.0.1")[0].status, 403)

    def test_unknown_paths_404(self):
        for p in ("/foo", "/ui/index.html", "/bin/server.py", "/../bin/server.py", "/api/nope"):
            self.assertEqual(self.get(p)[0].status, 404, p)

    def test_transcript_path_traversal(self):
        proj = os.path.join(self.home, ".claude", "projects", "p", "s"); os.makedirs(proj)
        outside = os.path.join(self.tmp, "secret.jsonl")
        write(outside, json.dumps({"message": {"role": "user", "content": "secret"}}) + "\n")
        write(os.path.join(proj, "ok.jsonl"), json.dumps({"message": {"role": "user", "content": "bonjour"}}) + "\n")
        os.symlink(outside, os.path.join(proj, "lien.jsonl"))
        def items(qs):
            r, b = self.get("/api/transcript?" + qs); self.assertEqual(r.status, 200); return json.loads(b)["items"]
        root = os.path.join(self.home, ".claude", "projects")
        self.assertEqual(items("path=/etc/passwd"), [])
        self.assertEqual(items("path=" + outside), [])
        self.assertEqual(items("path=" + root + "/p/s/../../../../secret.jsonl"), [])
        self.assertEqual(items("path=" + os.path.join(proj, "lien.jsonl")), [])
        self.assertEqual(items("agent_id=..%2F..%2Fx"), [])
        self.assertEqual(items("source=codex&session=../../x"), [])
        self.assertEqual(items("source=inconnu&session=abc"), [])
        self.assertEqual(items("codex_session=zzz"), [])
        got = items("path=" + os.path.join(proj, "ok.jsonl"))
        self.assertEqual([i["t"] for i in got], ["bonjour"])

    def test_since_not_a_number(self):
        r, b = self.get("/api/events?since=abc")
        self.assertEqual(r.status, 200); self.assertIn("events", json.loads(b))

    def test_client_disconnect_leaves_no_trace(self):
        for _ in range(5):
            s = socket.create_connection(("127.0.0.1", self.port))
            s.sendall(f"GET /api/agents HTTP/1.1\r\nHost: 127.0.0.1:{self.port}\r\n\r\n".encode())
            s.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, b"\x01\x00\x00\x00\x00\x00\x00\x00")  # RST
            s.close()
        c = http.client.HTTPConnection("127.0.0.1", self.port); c.request("GET", "/api/alive"); c.getresponse().close(); c.close()
        time.sleep(3.5)
        self.err.flush()
        self.assertNotIn("Traceback", read(self.errfile))
        self.assertEqual(self.get("/api/windows")[0].status, 200)

    def test_windows_follow_sse(self):
        def windows(): return json.loads(self.get("/api/windows")[1])
        def wait(n):
            for _ in range(80):
                if windows()["n"] == n: return True
                time.sleep(0.2)
            return False
        self.assertTrue(wait(0))
        self.assertGreaterEqual(windows()["up"], 0)
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5); c.request("GET", "/api/alive?view=x")
        r = c.getresponse(); self.assertEqual(r.status, 200)
        self.assertTrue(wait(1))
        r.close(); c.close()
        self.assertTrue(wait(0))


    def test_windows_reports_views(self):
        conns = []
        for q in ("view=abc12345&pin=1", "view=abc12345&pin=0", "view=zzz"):
            c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5); c.request("GET", "/api/alive?" + q)
            r = c.getresponse(); self.assertEqual(r.status, 200); conns.append((c, r))
        try:
            for _ in range(50):
                d = json.loads(self.get("/api/windows")[1])
                if d["n"] == 3: break
                time.sleep(0.1)
            self.assertEqual(d["views"], {"abc12345": 2, "zzz": 1})
            self.assertEqual(d["unpinned"], 2)  # C3-B3 : la fenêtre épinglée ne compte pas
            self.assertEqual(json.loads(self.get("/api/events?since=0")[1])["pinned"], ["abc12345"])
        finally:
            for c, r in conns: r.close(); c.close()

    def title_env(self, name, lines, sid="aaaa1111"):
        d = os.path.join(self.home, ".claude", "projects", name); os.makedirs(d, exist_ok=True)
        p = os.path.join(d, sid + "-0000-0000.jsonl")
        write(p, "".join(l if isinstance(l, str) else json.dumps(l) + "\n" for l in lines))
        return p

    def title(self, sid): return json.loads(self.get("/api/titles?s=" + sid)[1]).get(sid)

    def test_title_custom_beats_ai_and_last_wins(self):
        self.title_env("t1", [{"type": "ai-title", "aiTitle": "Auto 1"}, {"type": "custom-title", "customTitle": "Mon titre", "sessionId": "x"},
                              {"type": "ai-title", "aiTitle": "Auto 2"}, {"type": "custom-title", "customTitle": "Titre final"}], "t1t1t1t1")
        self.assertEqual(self.title("t1t1t1t1"), "Titre final")

    def test_title_ai_when_no_custom(self):
        self.title_env("t2", [{"type": "ai-title", "aiTitle": "Auto 1"}, {"type": "ai-title", "aiTitle": "Auto 2"}], "t2t2t2t2")
        self.assertEqual(self.title("t2t2t2t2"), "Auto 2")

    def test_title_absent_or_corrupt(self):
        self.title_env("t3", [{"type": "user", "message": {"role": "user", "content": "salut"}}], "t3t3t3t3")
        self.assertIsNone(self.title("t3t3t3t3"))
        self.assertIsNone(self.title("nexistepas"))
        self.title_env("t4", ['{"type":"custom-title","customTitle":"cass\n', "pas du json ai-title\n", "[1,2]\n",
                              {"type": "ai-title", "aiTitle": "Valide"}], "t4t4t4t4")
        self.assertEqual(self.title("t4t4t4t4"), "Valide")
        self.title_env("t5", ['{"type":"custom-title","customTitle":\n', '{"type":"ai-title","aiTitle":42}\n'], "t5t5t5t5")
        self.assertIsNone(self.title("t5t5t5t5"))

    def test_title_picks_up_appended_lines(self):
        p = self.title_env("t6", [{"type": "ai-title", "aiTitle": "Avant"}], "t6t6t6t6")
        self.assertEqual(self.title("t6t6t6t6"), "Avant")
        with open(p, "a") as f: f.write(json.dumps({"type": "custom-title", "customTitle": "Après"}) + "\n")
        self.assertEqual(self.title("t6t6t6t6"), "Après")

    def test_title_transcript_outside_projects_ignored(self):
        outside = os.path.join(self.tmp, "dehors.jsonl")
        write(outside, json.dumps({"type": "custom-title", "customTitle": "Secret"}) + "\n")
        d = os.path.join(self.home, ".claude", "projects", "t7"); os.makedirs(d, exist_ok=True)
        os.symlink(outside, os.path.join(d, "t7t7t7t7.jsonl"))
        ev = os.path.join(self.tmp, "data", "events.jsonl")
        with open(ev, "a") as f:
            f.write(json.dumps({"session": "t7t7t7t7", "transcript": outside}) + "\n")
            f.write(json.dumps({"session": "t8t8t8t8", "transcript": "/etc/../tmp/x.jsonl"}) + "\n")
        self.assertIsNone(self.title("t7t7t7t7")); self.assertIsNone(self.title("t8t8t8t8"))

    def test_title_found_through_event_transcript(self):
        p = self.title_env("t9", [{"type": "custom-title", "customTitle": "Via événement"}], "zzzz9999")
        sub = os.path.join(p[:-6], "subagents", "agent-1.jsonl")
        ev = os.path.join(self.tmp, "data", "events.jsonl")
        with open(ev, "a") as f: f.write(json.dumps({"session": "e9e9e9e9", "transcript": sub, "source": "claude"}) + "\n")
        # l'id de session de l'événement ne correspond pas au nom de fichier : seul le champ transcript permet de retrouver le titre
        self.assertEqual(self.title("e9e9e9e9"), "Via événement")

    def test_events_stop_at_incomplete_line(self):
        ev = os.path.join(self.tmp, "data", "events.jsonl")
        full = b'{"event":"A"}\n'
        with open(ev, "wb") as f: f.write(full + b'{"event":"B')
        d = json.loads(self.get("/api/events?since=0")[1])
        self.assertEqual([e["event"] for e in d["events"]], ["A"])
        self.assertEqual(d["next"], len(full))
        with open(ev, "ab") as f: f.write(b'"}\n')
        d2 = json.loads(self.get(f"/api/events?since={d['next']}")[1])
        self.assertEqual([e["event"] for e in d2["events"]], ["B"])

    def test_ui_scripts_parse_and_sync_alive_is_global(self):
        import re
        html = read(os.path.join(REPO, "ui", "index.html"))
        scripts = re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", html, re.S)
        self.assertTrue(scripts)
        node = shutil.which("node")
        if not node: self.skipTest("node absent")
        for i, s in enumerate(scripts):
            p = os.path.join(self.tmp, f"ui{i}.js"); write(p, s)
            r = subprocess.run([node, "--check", p], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
        # syncAlive doit être une déclaration de niveau supérieur (profondeur d'accolades 0)
        js = "\n".join(scripts)
        depth = 0; top = False
        for line in js.split("\n"):
            if depth == 0 and line.startswith("function syncAlive"): top = True
            depth += line.count("{") - line.count("}")
        self.assertTrue(top, "syncAlive n'est pas global")

    def test_ui_escapes_and_whitelists_severity(self):
        html = read(os.path.join(REPO, "ui", "index.html"))
        self.assertNotIn('class="sev ${b.severity}"', html)
        self.assertIn("SEVS.includes(b.severity)", html)


if __name__ == "__main__":
    unittest.main()
