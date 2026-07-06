import unittest

from app.models.place import Place
from app.services.place_taxonomy import is_food_place


def _place(primary_type: str | None) -> Place:
    return Place(place_id="ext-1", name="place", lat=0.0, lng=0.0, primary_type=primary_type)


class TestIsFoodPlace(unittest.TestCase):
    def test_generic_types_are_food(self) -> None:
        for t in ["restaurant", "cafe", "bakery"]:
            self.assertTrue(is_food_place(_place(t)), t)

    def test_google_cuisine_and_style_subtypes_are_food(self) -> None:
        # Regression test: Google Places API (New) tags a specific place with
        # a cuisine/style subtype rather than the generic category it was
        # searched under, e.g. searching category=restaurant can return a
        # place whose own primaryType is "barbecue_restaurant". These were
        # previously misclassified as attractions, breaking the day-rhythm
        # meal floors (no dinner-time push) for days made up mostly of these.
        for t in [
            "barbecue_restaurant",
            "seafood_restaurant",
            "brunch_restaurant",
            "korean_restaurant",
            "japanese_restaurant",
            "fine_dining_restaurant",
            "cat_cafe",
        ]:
            self.assertTrue(is_food_place(_place(t)), t)

    def test_non_suffix_food_shop_types_are_food(self) -> None:
        for t in ["noodle_shop", "steak_house", "tea_house", "pub", "bar"]:
            self.assertTrue(is_food_place(_place(t)), t)

    def test_non_food_types_are_not_food(self) -> None:
        for t in ["tourist_attraction", "museum", "park", "gift_shop", "book_store", None]:
            self.assertFalse(is_food_place(_place(t)), t)


if __name__ == "__main__":
    unittest.main()
