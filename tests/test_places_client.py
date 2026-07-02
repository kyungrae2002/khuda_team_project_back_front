import unittest
from unittest.mock import MagicMock

import httpx

from app.schemas.query_builder import PlaceCategory, PlaceQuery
from app.services.places_client import PlacesAPIError, PlacesClient


def _make_response(status_code: int, json_body: dict | None = None, text: str = "") -> httpx.Response:
    request = httpx.Request("POST", "https://places.googleapis.com/v1/places:searchText")
    if json_body is not None:
        return httpx.Response(status_code, request=request, json=json_body)
    return httpx.Response(status_code, request=request, text=text)


def _sample_query(search_type: str = "text") -> PlaceQuery:
    return PlaceQuery(
        query_text="부산 회 맛집", search_type=search_type, category=PlaceCategory.restaurant
    )


_SAMPLE_PLACE_PAYLOAD = {
    "places": [
        {
            "id": "ChIJ_operational",
            "displayName": {"text": "동래회센타"},
            "location": {"latitude": 35.1, "longitude": 129.0},
            "rating": 4.5,
            "userRatingCount": 1200,
            "businessStatus": "OPERATIONAL",
            "regularOpeningHours": {"openNow": True},
        },
        {
            "id": "ChIJ_closed",
            "displayName": {"text": "폐업한 가게"},
            "location": {"latitude": 35.2, "longitude": 129.1},
            "rating": 3.0,
            "userRatingCount": 10,
            "businessStatus": "CLOSED_PERMANENTLY",
        },
    ]
}


class TestPlacesClientParsing(unittest.TestCase):
    def test_search_excludes_non_operational_places(self) -> None:
        fake_http = MagicMock()
        fake_http.post.return_value = _make_response(200, _SAMPLE_PLACE_PAYLOAD)
        client = PlacesClient(api_key="test-key", http_client=fake_http)

        results = client.search(_sample_query())

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["place_id"], "ChIJ_operational")
        self.assertEqual(results[0]["name"], "동래회센타")

    def test_sends_field_mask_and_api_key_headers(self) -> None:
        fake_http = MagicMock()
        fake_http.post.return_value = _make_response(200, {"places": []})
        client = PlacesClient(api_key="test-key", http_client=fake_http)

        client.search(_sample_query())

        headers = fake_http.post.call_args.kwargs["headers"]
        self.assertEqual(
            headers["X-Goog-FieldMask"],
            "places.id,places.displayName,places.location,places.rating,"
            "places.userRatingCount,places.businessStatus,places.regularOpeningHours,"
            "places.primaryType",
        )
        self.assertEqual(headers["X-Goog-Api-Key"], "test-key")

    def test_text_search_payload(self) -> None:
        fake_http = MagicMock()
        fake_http.post.return_value = _make_response(200, {"places": []})
        client = PlacesClient(api_key="test-key", http_client=fake_http)

        client.search(_sample_query("text"))

        call = fake_http.post.call_args
        self.assertEqual(call.args[0], "https://places.googleapis.com/v1/places:searchText")
        self.assertEqual(call.kwargs["json"]["textQuery"], "부산 회 맛집")

    def test_nearby_search_requires_location(self) -> None:
        client = PlacesClient(api_key="test-key", http_client=MagicMock())

        with self.assertRaises(ValueError):
            client.search(_sample_query("nearby"))

    def test_nearby_search_payload_uses_location(self) -> None:
        fake_http = MagicMock()
        fake_http.post.return_value = _make_response(200, {"places": []})
        client = PlacesClient(api_key="test-key", http_client=fake_http)

        client.search(_sample_query("nearby"), location=(35.1, 129.0))

        call = fake_http.post.call_args
        self.assertEqual(call.args[0], "https://places.googleapis.com/v1/places:searchNearby")
        circle = call.kwargs["json"]["locationRestriction"]["circle"]
        self.assertEqual(circle["center"], {"latitude": 35.1, "longitude": 129.0})


class TestPlacesClientRetry(unittest.TestCase):
    def test_retries_on_429_then_succeeds(self) -> None:
        fake_http = MagicMock()
        fake_http.post.side_effect = [
            _make_response(429, text="rate limited"),
            _make_response(200, {"places": []}),
        ]
        client = PlacesClient(
            api_key="test-key", http_client=fake_http, max_retries=3, base_delay_seconds=0
        )

        client.search(_sample_query())

        self.assertEqual(fake_http.post.call_count, 2)

    def test_exhausts_retries_on_persistent_server_error(self) -> None:
        fake_http = MagicMock()
        fake_http.post.return_value = _make_response(500, text="server error")
        client = PlacesClient(
            api_key="test-key", http_client=fake_http, max_retries=3, base_delay_seconds=0
        )

        with self.assertRaises(PlacesAPIError):
            client.search(_sample_query())

        self.assertEqual(fake_http.post.call_count, 4)

    def test_does_not_retry_on_client_error(self) -> None:
        fake_http = MagicMock()
        fake_http.post.return_value = _make_response(400, text="bad request")
        client = PlacesClient(
            api_key="test-key", http_client=fake_http, max_retries=3, base_delay_seconds=0
        )

        with self.assertRaises(PlacesAPIError):
            client.search(_sample_query())

        self.assertEqual(fake_http.post.call_count, 1)

    def test_retries_on_network_error(self) -> None:
        fake_http = MagicMock()
        fake_http.post.side_effect = [
            httpx.ConnectError("connection failed"),
            _make_response(200, {"places": []}),
        ]
        client = PlacesClient(
            api_key="test-key", http_client=fake_http, max_retries=3, base_delay_seconds=0
        )

        client.search(_sample_query())

        self.assertEqual(fake_http.post.call_count, 2)


if __name__ == "__main__":
    unittest.main()
