from stringutils import shout


def test_shout():
    assert shout("hello") == "HELLO!"
