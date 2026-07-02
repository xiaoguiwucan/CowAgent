import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class SchedulerUiTest(unittest.TestCase):
    def test_task_cards_show_receiver_name_as_target(self):
        console_js = (ROOT / "channel/web/static/js/console.js").read_text(encoding="utf-8")

        self.assertIn("const taskTarget = action.receiver_name || '--';", console_js)
        self.assertIn("目标", console_js)
        self.assertIn("${escapeHtml(taskTarget)}", console_js)


if __name__ == "__main__":
    unittest.main()
