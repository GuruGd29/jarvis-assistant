"""Settings that change what Jarvis does in the background."""
import unittest
from unittest import mock

from jarvis import config
from jarvis.web import hermes


class WarmChatTest(unittest.TestCase):
    def test_off_sends_no_chat(self):
        """JARVIS_WARM_CHAT=off (a cloud chat model): the 20-minute warm-up must not send a paid request."""
        with mock.patch.object(config, "WARM_CHAT", False), \
                mock.patch.object(hermes, "create_session", side_effect=AssertionError("a chat was started")):
            hermes.warm_chat()


if __name__ == "__main__":
    unittest.main()
