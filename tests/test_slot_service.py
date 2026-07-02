import unittest

from app.models.slot import Slot, SlotField, SlotStatus
from app.services.slot_service import build_slot_summary


def _slot(field: SlotField, value: str, status: SlotStatus = SlotStatus.confirmed) -> Slot:
    return Slot(
        session_id=1,
        field=field,
        value=value,
        status=status,
        evidence_message_ids=[0],
        confidence=0.9,
    )


class TestBuildSlotSummary(unittest.TestCase):
    def test_confirmed_singular_field_returns_its_value(self) -> None:
        summary = build_slot_summary([_slot(SlotField.destination, "서울")])

        self.assertEqual(summary["destination"], "서울")

    def test_missing_field_entirely_is_null(self) -> None:
        summary = build_slot_summary([_slot(SlotField.destination, "서울")])

        self.assertIsNone(summary["date"])
        self.assertIsNone(summary["budget"])

    def test_conflict_only_field_is_null(self) -> None:
        summary = build_slot_summary(
            [
                _slot(SlotField.destination, "서울", status=SlotStatus.conflict),
                _slot(SlotField.destination, "대전", status=SlotStatus.conflict),
            ]
        )

        self.assertIsNone(summary["destination"])

    def test_undecided_only_field_is_null(self) -> None:
        summary = build_slot_summary([_slot(SlotField.date, "21일", status=SlotStatus.undecided)])

        self.assertIsNone(summary["date"])

    def test_confirmed_list_field_returns_all_confirmed_values(self) -> None:
        summary = build_slot_summary(
            [
                _slot(SlotField.wishlist, "찜질방"),
                _slot(SlotField.wishlist, "술 마시기"),
                _slot(SlotField.wishlist, "안 갈래", status=SlotStatus.undecided),
            ]
        )

        self.assertEqual(summary["wishlist"], ["찜질방", "술 마시기"])

    def test_empty_list_field_is_null_not_empty_list(self) -> None:
        summary = build_slot_summary([])

        self.assertIsNone(summary["wishlist"])
        self.assertIsNone(summary["constraint"])


if __name__ == "__main__":
    unittest.main()
