import json, os, shutil, subprocess, sys, tempfile, unittest

def read(p):
    with open(p) as f: return f.read()


def write(p, t, mode="w"):
    with open(p, mode) as f: f.write(t)


REPO = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))


class InstallTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hub-install-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        # copie du dépôt : les sauvegardes (ROOT/backups) ne touchent jamais le vrai dossier
        self.root = os.path.join(self.tmp, "repo")
        shutil.copytree(REPO, self.root, ignore=shutil.ignore_patterns(".git", "logs", "backups", "__pycache__"))
        self.home = os.path.join(self.tmp, "home"); os.makedirs(self.home)
        self.claude = os.path.join(self.home, ".claude")
        self.settings = os.path.join(self.claude, "settings.json")
        self.env = {**os.environ, "HOME": self.home, "AGENTS_HUB_DATA": os.path.join(self.tmp, "data")}
        self.env.pop("CLAUDE_CONFIG_DIR", None)

    def run_py(self, action, *args, root=None):
        return subprocess.run([sys.executable, os.path.join(root or self.root, "bin", "install.py"), action, *args],
                              env=self.env, capture_output=True, text=True)

    def read_settings(self):
        with open(self.settings) as f: return json.load(f)

    def write_settings(self, d):
        os.makedirs(self.claude, exist_ok=True)
        with open(self.settings, "w") as f: f.write(d if isinstance(d, str) else json.dumps(d))

    def commands(self, s=None):
        s = s or self.read_settings()
        return [h["command"] for gs in s.get("hooks", {}).values() for g in gs for h in g["hooks"]]

    def test_install_in_empty_home(self):
        r = self.run_py("install"); self.assertEqual(r.returncode, 0, r.stderr)
        s = self.read_settings()
        self.assertEqual(set(s["hooks"]), {"PreToolUse", "SubagentStart", "SubagentStop", "UserPromptSubmit", "Stop", "Notification"})
        self.assertEqual(len(self.commands(s)), 7)
        self.assertTrue(any("open_window.py" in c and "--hook" in c for c in self.commands(s)))
        self.assertTrue(all(h["timeout"] == 5 for gs in s["hooks"].values() for g in gs for h in g["hooks"]))
        skill = read(os.path.join(self.claude, "skills", "hub", "SKILL.md"))
        self.assertNotIn("__AGENTS_HUB__", skill)
        self.assertIn(self.root, skill)
        self.assertTrue(os.path.exists(os.path.join(self.claude, "agents", "reviewer.md")))
        self.assertTrue(os.path.exists(os.path.join(self.tmp, "data", "install-manifest.json")))

    def test_reinstall_no_duplicates(self):
        self.run_py("install"); first = self.read_settings()
        r = self.run_py("install"); self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.read_settings(), first)

    def test_existing_agent_kept(self):
        os.makedirs(os.path.join(self.claude, "agents"))
        mine = os.path.join(self.claude, "agents", "reviewer.md")
        write(mine, "mon reviewer", "w")
        r = self.run_py("install"); self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(read(mine), "mon reviewer")
        self.assertIn("conservé", r.stdout)
        self.run_py("uninstall")
        self.assertEqual(read(mine), "mon reviewer")  # pas à nous : jamais supprimé

    def test_modified_skill_kept(self):
        self.run_py("install")
        skill = os.path.join(self.claude, "skills", "hub", "SKILL.md")
        write(skill, "\nma modif", "a")
        r = self.run_py("install")
        self.assertIn("ma modif", read(skill))
        self.assertIn("Attention", r.stdout)

    def test_unmodified_skill_updated(self):
        self.run_py("install")
        with open(os.path.join(self.root, "skills", "hub", "SKILL.md"), "a") as f: f.write("\nnouveauté")
        self.run_py("install")
        self.assertIn("nouveauté", read(os.path.join(self.claude, "skills", "hub", "SKILL.md")))

    def test_third_party_hooks_intact(self):
        tiers = {"theme": "x", "hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "echo tiers"}]}],
                                         "Stop": [{"hooks": [{"type": "command", "command": "say fini"}]}]}}
        self.write_settings(tiers)
        self.assertEqual(self.run_py("install").returncode, 0)
        s = self.read_settings()
        self.assertEqual(s["theme"], "x")
        self.assertEqual(s["hooks"]["PreToolUse"][0], tiers["hooks"]["PreToolUse"][0])
        self.assertEqual(s["hooks"]["Stop"][0], tiers["hooks"]["Stop"][0])
        self.assertEqual(len(s["hooks"]["Stop"]), 2)

    def test_invalid_json_aborts(self):
        self.write_settings("{ pas du json")
        r = self.run_py("install")
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(read(self.settings), "{ pas du json")
        self.assertFalse(os.path.exists(os.path.join(self.claude, "agents")))
        self.assertFalse(os.path.exists(os.path.join(self.root, "backups")))

    def test_backup_made(self):
        self.write_settings({"theme": "x"})
        self.run_py("install")
        b = os.path.join(self.root, "backups")
        files = os.listdir(b)
        self.assertEqual(len(files), 1)
        self.assertEqual(json.loads(read(os.path.join(b, files[0]))), {"theme": "x"})

    def test_uninstall_removes_only_ours(self):
        tiers = {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "say fini"}]}]}}
        self.write_settings(tiers)
        self.run_py("install")
        skill = os.path.join(self.claude, "skills", "hub", "SKILL.md")
        agent = os.path.join(self.claude, "agents", "developpeur.md")
        write(agent, "\nperso", "a")  # modifié : conservé
        r = self.run_py("uninstall"); self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.read_settings(), tiers)
        self.assertFalse(os.path.exists(skill))
        self.assertTrue(os.path.exists(agent))
        self.assertFalse(os.path.exists(os.path.join(self.claude, "agents", "reviewer.md")))
        self.assertTrue(os.path.isdir(REPO))

    def test_uninstall_drops_empty_keys(self):
        self.run_py("install"); self.run_py("uninstall")
        self.assertNotIn("hooks", self.read_settings())

    def test_conflict_refused_without_force(self):
        other = "python3 /autre/AgentsHub/bin/log_event.py"
        self.write_settings({"hooks": {"Stop": [{"hooks": [{"type": "command", "command": other}]}]}})
        r = self.run_py("install")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("/autre/AgentsHub", r.stderr)
        self.assertEqual(self.commands(), [other])
        r = self.run_py("install", "--force")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(other, self.commands())
        self.assertEqual(len(self.commands()), 8)

    def test_root_change_replaces_old_commands(self):
        self.run_py("install")
        root2 = os.path.join(self.tmp, "repo2")
        shutil.copytree(self.root, root2, ignore=shutil.ignore_patterns("backups"))
        r = self.run_py("install", root=root2); self.assertEqual(r.returncode, 0, r.stderr)
        cmds = self.commands()
        self.assertEqual(len(cmds), 7)
        self.assertTrue(all(root2 in c for c in cmds))


    def test_refuses_dangerous_root(self):
        for bad in ['a"b', "a$b", "a`b", "a\\b"]:
            root = os.path.join(self.tmp, bad); shutil.copytree(self.root, root)
            r = self.run_py("install", root=root)
            self.assertNotEqual(r.returncode, 0, bad)
            self.assertIn("caractère interdit", r.stderr)
            self.assertFalse(os.path.exists(self.settings))
        root = os.path.join(self.tmp, "with space"); shutil.copytree(self.root, root)
        r = self.run_py("install", root=root); self.assertEqual(r.returncode, 0, r.stderr)

    def test_bad_hooks_shape_refused_before_copy(self):
        for bad in ('{"hooks": []}', '{"hooks": null}', '{"hooks": {"PreToolUse": {}}}'):
            self.write_settings(bad)
            r = self.run_py("install")
            self.assertEqual(r.returncode, 1, bad)
            self.assertIn("forme attendue", r.stderr)
            self.assertFalse(os.path.exists(os.path.join(self.claude, "agents")), bad)
            self.assertFalse(os.path.exists(os.path.join(self.claude, "skills")), bad)
            self.assertFalse(os.path.exists(os.path.join(self.tmp, "data", "install-manifest.json")), bad)
            self.assertEqual(read(self.settings), bad)

    def test_identical_file_without_manifest_is_recorded(self):
        self.assertEqual(self.run_py("install").returncode, 0)
        os.remove(os.path.join(self.tmp, "data", "install-manifest.json"))
        self.assertEqual(self.run_py("install").returncode, 0)
        with open(os.path.join(self.tmp, "data", "install-manifest.json")) as f: man = json.load(f)
        self.assertTrue(man["files"])
        self.assertEqual(self.run_py("uninstall").returncode, 0)
        self.assertFalse(os.path.exists(os.path.join(self.claude, "skills", "hub", "SKILL.md")))


if __name__ == "__main__":
    unittest.main()
