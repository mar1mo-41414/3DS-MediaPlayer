"""一時ファイル / ディレクトリを通常の権限で作る fsutil。"""

import os
import stat
import tempfile
import unittest
from pathlib import Path

from helpers import skip_on_windows
from mkcia.fsutil import create_tmp_dir, create_tmp_file


class FsutilTest(unittest.TestCase):
    def setUp(self):
        self._d = tempfile.TemporaryDirectory()
        self.d = Path(self._d.name)
        self.addCleanup(self._d.cleanup)

    def test_file_is_created_empty_with_prefix_and_suffix(self):
        p = create_tmp_file(self.d, prefix=".x-", suffix=".tmp")
        self.assertEqual(p.parent, self.d)
        self.assertTrue(p.name.startswith(".x-") and p.name.endswith(".tmp"))
        self.assertTrue(p.is_file())
        self.assertEqual(p.stat().st_size, 0)

    def test_names_do_not_collide(self):
        names = {create_tmp_file(self.d, "a-", ".tmp").name for _ in range(50)}
        self.assertEqual(len(names), 50)
        names = {create_tmp_dir(self.d, "b-", ".tmp").name for _ in range(50)}
        self.assertEqual(len(names), 50)

    def test_dir_is_created(self):
        p = create_tmp_dir(self.d, prefix=".t-", suffix=".tmp")
        self.assertTrue(p.is_dir())
        self.assertEqual(list(p.iterdir()), [])

    def test_missing_parent_is_an_error(self):
        with self.assertRaises(OSError):
            create_tmp_file(self.d / "nope", "a-", ".tmp")
        with self.assertRaises(OSError):
            create_tmp_dir(self.d / "nope", "a-", ".tmp")

    @skip_on_windows
    def test_permissions_follow_umask_unlike_mkstemp(self):
        old = os.umask(0o022)
        try:
            f = create_tmp_file(self.d, "f-", ".tmp")
            d = create_tmp_dir(self.d, "d-", ".tmp")
        finally:
            os.umask(old)
        self.assertEqual(stat.S_IMODE(f.stat().st_mode), 0o644)
        self.assertEqual(stat.S_IMODE(d.stat().st_mode), 0o755)


if __name__ == "__main__":
    unittest.main()
