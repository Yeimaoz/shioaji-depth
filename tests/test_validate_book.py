"""5-level book invariant tests (tolerates fewer-than-5 filled levels)."""
from shioaji_depth.recorder import validate_book


def test_valid_full():
    assert validate_book(
        [100.0, 99.0], [1.0, 2.0], [101.0, 102.0], [1.0, 2.0]
    ) is True


def test_valid_partial_book():
    # Fewer than 5 levels is legal as long as the best level is present.
    assert validate_book([100.0], [1.0], [101.0], [1.0]) is True


def test_crossed():
    assert validate_book([101.0], [1.0], [100.0], [1.0]) is False


def test_touching_is_crossed():
    # best_bid == best_ask is rejected (>= check).
    assert validate_book([100.0], [1.0], [100.0], [1.0]) is False


def test_neg_qty():
    assert validate_book([100.0], [-1.0], [101.0], [1.0]) is False


def test_zero_qty_allowed():
    # A genuine zero-volume best level is permitted (qty >= 0).
    assert validate_book([100.0], [0.0], [101.0], [1.0]) is True


def test_unsorted_bids():
    # Bids must be strictly descending.
    assert validate_book([99.0, 100.0], [1.0, 1.0], [101.0], [1.0]) is False


def test_unsorted_asks():
    # Asks must be strictly ascending.
    assert validate_book([100.0], [1.0], [102.0, 101.0], [1.0, 1.0]) is False


def test_dup_price():
    assert validate_book([100.0, 100.0], [1.0, 1.0], [101.0], [1.0]) is False


def test_empty_best():
    assert validate_book([], [], [101.0], [1.0]) is False
