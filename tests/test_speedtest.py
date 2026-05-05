import unittest

from module_speedtest import BandwidthTester


class BandwidthTesterTests(unittest.TestCase):
    def test_bytes_to_count_truncates_chunk_at_max_bytes(self):
        self.assertEqual(BandwidthTester.bytes_to_count(0, 8, 10), 8)
        self.assertEqual(BandwidthTester.bytes_to_count(8, 8, 10), 2)
        self.assertEqual(BandwidthTester.bytes_to_count(10, 8, 10), 0)


if __name__ == "__main__":
    unittest.main()
