from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APPLICATION_FILES = (
    ROOT / "src" / "cloudtrim" / "gui.py",
    ROOT / "src" / "cloudtrim" / "downsample.py",
    ROOT / "src" / "cloudtrim" / "split_crop.py",
)
CJK_PATTERN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")


class UiLanguageTests(unittest.TestCase):
    def test_application_source_contains_no_cjk_user_facing_text(self) -> None:
        matches: list[str] = []

        for path in APPLICATION_FILES:
            for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if CJK_PATTERN.search(line):
                    matches.append(f"{path.relative_to(ROOT)}:{line_number}: {line.strip()}")

        self.assertEqual(matches, [], "CJK text remains:\n" + "\n".join(matches))


if __name__ == "__main__":
    unittest.main()
