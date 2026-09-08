import pytest

from talx_to_stac.__main__ import main


def test_an_unreachable_event_is_reported_rather_than_raised(capsys):
    assert main(["https://example.invalid/nope/schedule/"]) == 1
    assert "error:" in capsys.readouterr().err


def test_the_event_url_is_required():
    with pytest.raises(SystemExit):
        main([])


def test_an_unknown_option_is_rejected():
    with pytest.raises(SystemExit):
        main(["https://example.invalid/e/schedule/", "--nope"])
