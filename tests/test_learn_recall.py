"""Memory recall before a reply (jarvis/learn.py): only close facts, and earlier chats only when asked for.

  .venv/bin/python -m unittest tests.test_learn_recall
"""
import unittest
from datetime import datetime
from unittest import mock

from jarvis import learn


class Recall(unittest.TestCase):
    def run_recall(self, **kwargs):
        conn = mock.MagicMock()
        execute = conn.__enter__.return_value.execute
        execute.return_value.fetchall.return_value = [("User has a red car", datetime(2026, 11, 1))]
        with mock.patch.object(learn, "embed", return_value=[[0.1, 0.2]]), \
                mock.patch.object(learn, "_connect", return_value=conn):
            found = learn.recall("my car", **kwargs)
        return found, [c.args[1] for c in execute.call_args_list]

    def test_close_facts_only_and_no_earlier_chats_unless_asked(self):
        found, queries = self.run_recall(episodes=0)
        self.assertEqual(found, ["(01 Nov 2026) User has a red car"])
        self.assertEqual(len(queries), 1)
        kind, _, distance, _, most = queries[0]
        self.assertEqual((kind, distance, most), ("fact", 0.42, 3))

    def test_earlier_chats_when_asked(self):
        found, queries = self.run_recall()
        self.assertEqual([q[0] for q in queries], ["fact", "episode"])
        self.assertEqual(queries[1][4], 2)
        self.assertEqual(found[1], "(01 Nov 2026) earlier chat: User has a red car")


if __name__ == "__main__":
    unittest.main()
