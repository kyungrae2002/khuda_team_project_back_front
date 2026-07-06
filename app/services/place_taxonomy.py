"""Shared classification of Google Places API (New) "primaryType" values into
food-establishment vs. attraction, used identically by itinerary_builder.py
(day rhythm ordering, meal-time floors) and narrator.py (아침/점심/저녁 vs.
오전/오후 labels) — a single definition so the two can never drift apart.

Google returns a specific cuisine/style subtype (e.g. "barbecue_restaurant",
"seafood_restaurant", "noodle_shop") rather than always the generic
"restaurant"/"cafe" category that was searched under, so matching only the
generic values misses most real restaurants."""

from app.models.place import Place

_FOOD_PRIMARY_TYPE_SUFFIXES = ("_restaurant", "_cafe")

# Table A food/drink types that don't follow the "_restaurant"/"_cafe" suffix
# pattern. Deliberately not matching a bare "_shop"/"_store" suffix, since
# that would also catch non-food types like "gift_shop"/"book_store".
_FOOD_PRIMARY_TYPES = frozenset(
    {
        "restaurant",
        "cafe",
        "bakery",
        "bar",
        "bar_and_grill",
        "bagel_shop",
        "buffet_restaurant",
        "cafeteria",
        "candy_store",
        "chocolate_factory",
        "chocolate_shop",
        "coffee_shop",
        "confectionery",
        "deli",
        "dessert_shop",
        "diner",
        "donut_shop",
        "fast_food_restaurant",
        "food_court",
        "ice_cream_shop",
        "juice_shop",
        "meal_delivery",
        "meal_takeaway",
        "noodle_shop",
        "pub",
        "sandwich_shop",
        "steak_house",
        "tea_house",
        "wine_bar",
    }
)


def is_food_place(place: Place) -> bool:
    primary_type = place.primary_type or ""
    return primary_type in _FOOD_PRIMARY_TYPES or primary_type.endswith(_FOOD_PRIMARY_TYPE_SUFFIXES)
