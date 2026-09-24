"""Telegram Mini App initData verification (pure; no network)."""
import time

import pytest

from app import tg_auth

TOKEN = "123456:TEST-TOKEN"
OTHER_BOT = "654321:OTHER-TOKEN"
USER = {"id": 7380008596, "first_name": "Kirk"}


def test_valid_init_data_returns_user():
    assert tg_auth.verify_init_data(tg_auth.sign_init_data(USER, TOKEN), TOKEN)["id"] == USER["id"]


def test_tampered_user_rejected():
    init = tg_auth.sign_init_data(USER, TOKEN).replace("Kirk", "Mallory")
    with pytest.raises(tg_auth.InvalidInitData, match="bad signature"):
        tg_auth.verify_init_data(init, TOKEN)


def test_signed_for_another_bot_rejected():
    """The dev bot's Mini App data must not be accepted by the prod backend (and vice versa)."""
    with pytest.raises(tg_auth.InvalidInitData, match="bad signature"):
        tg_auth.verify_init_data(tg_auth.sign_init_data(USER, OTHER_BOT), TOKEN)


def test_expired_rejected():
    old = tg_auth.sign_init_data(USER, TOKEN, auth_date=int(time.time()) - 25 * 3600)
    with pytest.raises(tg_auth.InvalidInitData, match="expired"):
        tg_auth.verify_init_data(old, TOKEN)


@pytest.mark.parametrize("init", ["", "hash=abc", "auth_date=1&user=%7B%7D"])
def test_missing_or_malformed_rejected(init):
    with pytest.raises(tg_auth.InvalidInitData):
        tg_auth.verify_init_data(init, TOKEN)
