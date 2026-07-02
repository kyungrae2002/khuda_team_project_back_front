import unittest

from app.services.geo import haversine_km


class TestHaversine(unittest.TestCase):
    def test_zero_distance_for_identical_points(self) -> None:
        self.assertEqual(haversine_km(35.0, 129.0, 35.0, 129.0), 0.0)

    def test_known_distance_one_degree_latitude(self) -> None:
        # 1 degree of latitude is ~111 km everywhere on Earth.
        distance = haversine_km(35.0, 129.0, 36.0, 129.0)
        self.assertAlmostEqual(distance, 111.0, delta=1.0)


if __name__ == "__main__":
    unittest.main()
