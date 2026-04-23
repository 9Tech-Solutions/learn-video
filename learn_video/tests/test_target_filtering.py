import unittest

from learn_video.state import Target
from learn_video.target import _filter_targets


class TestFilterTargets(unittest.TestCase):
    def test_drops_edges(self):
        out = _filter_targets(
            [
                Target(t=1.0, why="too early"),
                Target(t=100.0, why="too late"),
                Target(t=30.0, why="keep"),
            ],
            duration_s=101.0,
        )
        self.assertEqual([t.t for t in out], [30.0])

    def test_collapses_near_duplicates(self):
        out = _filter_targets(
            [
                Target(t=10.0, why="a"),
                Target(t=10.5, why="b"),  # dropped — within 2s
                Target(t=20.0, why="c"),
            ],
            duration_s=100.0,
        )
        self.assertEqual([t.t for t in out], [10.0, 20.0])

    def test_sorts_output(self):
        out = _filter_targets(
            [
                Target(t=50.0, why="a"),
                Target(t=10.0, why="b"),
                Target(t=30.0, why="c"),
            ],
            duration_s=100.0,
        )
        self.assertEqual([t.t for t in out], [10.0, 30.0, 50.0])


if __name__ == "__main__":
    unittest.main()
