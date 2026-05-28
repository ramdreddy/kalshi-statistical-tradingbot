from kalshi_bot.exchange.live_ws import snapshot_from_message


def test_parse_empty_snapshot() -> None:
    msg = {"market_ticker": "kxhighny-26may27", "market_id": ""}
    book = snapshot_from_message(msg, "KXHIGHNY-26MAY27")
    assert book is not None
    assert book.ticker == "KXHIGHNY-26MAY27"
    assert book.best_bid_cents is None
    assert book.best_ask_cents is None


def test_parse_dollars_fp_snapshot() -> None:
    msg = {
        "market_ticker": "FED-23DEC-T3.00",
        "market_id": "9b0f6b43-5b68-4f9f-9f02-9a2d1b8ac1a1",
        "yes_dollars_fp": [["0.0800", "300.00"], ["0.2200", "333.00"]],
        "no_dollars_fp": [["0.5400", "20.00"], ["0.5600", "146.00"]],
    }
    book = snapshot_from_message(msg, "FED-23DEC-T3.00")
    assert book is not None
    assert book.best_bid_cents == 22
    assert book.best_ask_cents == 44  # 100 - 56 (best / lowest YES ask)
