import os, sys, tempfile, unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "bin"))
from adapters import codex


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
            self.assertEqual(evs[0]["session"], "abcdef12")
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


if __name__ == "__main__":
    unittest.main()
