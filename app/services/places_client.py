"""Google Places API (New) client with DB-backed caching.

get_or_fetch_place() is cache-first: a query is only sent to the Places API
if no matching (query_text, search_type, category) search was recorded in
the last 24 hours. Results are always upserted into the Place table, keyed
by Google's place_id, so callers never see duplicate rows for the same
place."""

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from typing import Sequence

import httpx
from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.place import Place
from app.models.place_search_cache import PlaceSearchCache
from app.schemas.query_builder import PlaceQuery

_TEXT_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
_NEARBY_SEARCH_URL = "https://places.googleapis.com/v1/places:searchNearby"

_FIELD_MASK = (
    "places.id,places.displayName,places.location,places.rating,"
    "places.userRatingCount,places.businessStatus,places.regularOpeningHours,"
    "places.primaryType"
)

_OPERATIONAL_STATUS = "OPERATIONAL"

DEFAULT_MAX_RETRIES = 3
DEFAULT_BASE_DELAY_SECONDS = 1.0
DEFAULT_NEARBY_RADIUS_METERS = 5000.0
# A text query like "제주도 점심 맛집" carries no geographic constraint of its
# own — Google's text relevance ranking can still surface a same-themed
# place hundreds of km away (observed: a "제주" fusion restaurant matched from
# Seongnam). locationBias doesn't hard-exclude far results, but strongly
# prefers this area; the hard guarantee is the post-fetch distance filter in
# pipeline.py.
DEFAULT_TEXT_LOCATION_BIAS_RADIUS_METERS = 60000.0
DEFAULT_MAX_RESULT_COUNT = 20
CACHE_FRESHNESS = timedelta(hours=24)


class PlacesAPIError(RuntimeError):
    """Raised when a Google Places API request fails after exhausting all retries."""


class PlacesClient:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        http_client: httpx.Client | None = None,
        max_retries: int = DEFAULT_MAX_RETRIES,
        base_delay_seconds: float = DEFAULT_BASE_DELAY_SECONDS,
    ) -> None:
        self._api_key = api_key if api_key is not None else settings.GOOGLE_PLACES_API_KEY
        self._http_client = http_client or httpx.Client(timeout=10.0)
        self._max_retries = max_retries
        self._base_delay_seconds = base_delay_seconds

    def search(
        self, query: PlaceQuery, *, location: tuple[float, float] | None = None
    ) -> list[dict]:
        if query.search_type == "text":
            url = _TEXT_SEARCH_URL
            payload = {"textQuery": query.query_text, "includedType": query.category.value}
            if location is not None:
                lat, lng = location
                payload["locationBias"] = {
                    "circle": {
                        "center": {"latitude": lat, "longitude": lng},
                        "radius": DEFAULT_TEXT_LOCATION_BIAS_RADIUS_METERS,
                    }
                }
        else:
            if location is None:
                raise ValueError("nearby 검색에는 location(lat, lng)이 필요합니다")
            lat, lng = location
            url = _NEARBY_SEARCH_URL
            payload = {
                "includedTypes": [query.category.value],
                "maxResultCount": DEFAULT_MAX_RESULT_COUNT,
                "locationRestriction": {
                    "circle": {
                        "center": {"latitude": lat, "longitude": lng},
                        "radius": DEFAULT_NEARBY_RADIUS_METERS,
                    }
                },
            }

        data = self._post_with_retry(url, payload)
        return self._parse_places(data)

    def _post_with_retry(self, url: str, payload: dict) -> dict:
        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": self._api_key,
            "X-Goog-FieldMask": _FIELD_MASK,
        }

        last_error: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                response = self._http_client.post(url, json=payload, headers=headers)
            except httpx.TransportError as exc:
                last_error = exc
            else:
                if response.status_code == 429 or response.status_code >= 500:
                    last_error = PlacesAPIError(
                        f"Google Places API 요청 실패 (status={response.status_code}): "
                        f"{response.text}"
                    )
                elif response.status_code >= 400:
                    # Non-retryable client error (bad request, invalid category,
                    # auth failure, ...) — fail immediately instead of burning
                    # retries or letting httpx.HTTPStatusError escape unhandled.
                    raise PlacesAPIError(
                        f"Google Places API 요청 실패 (status={response.status_code}): "
                        f"{response.text}"
                    )
                else:
                    return response.json()

            if attempt < self._max_retries:
                time.sleep(self._base_delay_seconds * (2**attempt))

        raise PlacesAPIError(
            f"Google Places API 요청이 {self._max_retries + 1}회 시도 후 실패했습니다: {last_error}"
        ) from last_error

    @staticmethod
    def _parse_places(data: dict) -> list[dict]:
        parsed = []
        for place in data.get("places", []):
            business_status = place.get("businessStatus")
            if business_status != _OPERATIONAL_STATUS:
                continue

            location = place.get("location", {})
            display_name = place.get("displayName", {})
            parsed.append(
                {
                    "place_id": place["id"],
                    "name": display_name.get("text", ""),
                    "primary_type": place.get("primaryType"),
                    "lat": location.get("latitude"),
                    "lng": location.get("longitude"),
                    "rating": place.get("rating"),
                    "review_count": place.get("userRatingCount"),
                    "business_status": business_status,
                    "opening_hours": place.get("regularOpeningHours"),
                }
            )
        return parsed


def _find_fresh_cache(
    db: Session, query_text: str, search_type: str, category: str
) -> PlaceSearchCache | None:
    cutoff = datetime.now(timezone.utc) - CACHE_FRESHNESS
    return (
        db.query(PlaceSearchCache)
        .filter(
            PlaceSearchCache.query_text == query_text,
            PlaceSearchCache.search_type == search_type,
            PlaceSearchCache.category == category,
            PlaceSearchCache.searched_at >= cutoff,
        )
        .one_or_none()
    )


def _load_places_by_ids(db: Session, place_ids: Sequence[str]) -> list[Place]:
    if not place_ids:
        return []
    rows = db.query(Place).filter(Place.place_id.in_(place_ids)).all()
    by_id = {place.place_id: place for place in rows}
    return [by_id[place_id] for place_id in place_ids if place_id in by_id]


def _upsert_places(db: Session, parsed_places: list[dict]) -> list[Place]:
    if not parsed_places:
        return []

    stmt = pg_insert(Place).values(parsed_places)
    stmt = stmt.on_conflict_do_update(
        index_elements=[Place.place_id],
        set_={
            "name": stmt.excluded.name,
            "primary_type": stmt.excluded.primary_type,
            "lat": stmt.excluded.lat,
            "lng": stmt.excluded.lng,
            "rating": stmt.excluded.rating,
            "review_count": stmt.excluded.review_count,
            "business_status": stmt.excluded.business_status,
            "opening_hours": stmt.excluded.opening_hours,
            "cached_at": func.now(),
        },
    ).returning(Place)
    places = list(db.execute(stmt).scalars().all())
    db.commit()
    return places


def _record_search(
    db: Session, query_text: str, search_type: str, category: str, place_ids: list[str]
) -> None:
    stmt = pg_insert(PlaceSearchCache).values(
        query_text=query_text,
        search_type=search_type,
        category=category,
        place_ids=place_ids,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[
            PlaceSearchCache.query_text,
            PlaceSearchCache.search_type,
            PlaceSearchCache.category,
        ],
        set_={"place_ids": place_ids, "searched_at": func.now()},
    )
    db.execute(stmt)
    db.commit()


def get_or_fetch_place(
    db: Session,
    query: PlaceQuery,
    *,
    location: tuple[float, float] | None = None,
    client: PlacesClient | None = None,
) -> list[Place]:
    cached = _find_fresh_cache(db, query.query_text, query.search_type, query.category.value)
    if cached is not None:
        return _load_places_by_ids(db, cached.place_ids)

    places_client = client or PlacesClient()
    parsed_places = places_client.search(query, location=location)

    places = _upsert_places(db, parsed_places)
    _record_search(
        db,
        query.query_text,
        query.search_type,
        query.category.value,
        [place.place_id for place in places],
    )
    return places


DEFAULT_BATCH_MAX_WORKERS = 8


def batch_search(
    db: Session,
    queries: Sequence[PlaceQuery],
    *,
    location: tuple[float, float] | None = None,
    client: PlacesClient | None = None,
    max_workers: int = DEFAULT_BATCH_MAX_WORKERS,
) -> list[list[Place]]:
    """Same result as calling get_or_fetch_place once per query, but the
    network leg for cache-misses runs concurrently across threads instead of
    one request at a time — with 5-10+ queries per itinerary (one per meal
    slot/day plus attractions), sequential requests were the dominant cost of
    itinerary generation. The DB session itself isn't touched from worker
    threads (SQLAlchemy Sessions aren't thread-safe); every cache read/write
    still happens sequentially on the caller's thread, only the outbound
    HTTP calls are parallelized. httpx.Client is documented as safe to share
    across threads, so a single client is reused for all requests."""
    places_client = client or PlacesClient()

    cache_hits: dict[int, list[Place]] = {}
    to_fetch: list[tuple[int, PlaceQuery]] = []
    for index, query in enumerate(queries):
        cached = _find_fresh_cache(db, query.query_text, query.search_type, query.category.value)
        if cached is not None:
            cache_hits[index] = _load_places_by_ids(db, cached.place_ids)
        else:
            to_fetch.append((index, query))

    fetched: dict[int, list[dict] | None] = {}
    if to_fetch:
        with ThreadPoolExecutor(max_workers=min(max_workers, len(to_fetch))) as executor:
            future_to_index = {
                executor.submit(places_client.search, query, location=location): index
                for index, query in to_fetch
            }
            for future in as_completed(future_to_index):
                index = future_to_index[future]
                try:
                    fetched[index] = future.result()
                except ValueError:
                    # e.g. a "nearby" query with no resolvable destination
                    # location — skip it rather than failing the whole batch.
                    fetched[index] = None

    results: list[list[Place]] = [[] for _ in queries]
    for index, query in to_fetch:
        parsed_places = fetched[index]
        if parsed_places is None:
            continue
        places = _upsert_places(db, parsed_places)
        _record_search(
            db, query.query_text, query.search_type, query.category.value,
            [place.place_id for place in places],
        )
        results[index] = places
    for index, places in cache_hits.items():
        results[index] = places
    return results
