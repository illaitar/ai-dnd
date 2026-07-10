from aidnd.server.play.handlers.freeform import _DISRUPTIVE_RE

DISRUPTIVE = [
    "выхватываю меч и рычу на весь зал",
    "громко спрашиваю: кто здесь главный?",
    "швыряю кружку об стену",
    "ору: тихо все!",
    "хватаюсь за нож",
    "бью кулаком по столу",
    "угрожаю всем в зале",
    "достаю клинок из-за пояса",
]
BENIGN = [
    "спрашиваю про слухи",
    "спрашиваю, где купить меч",
    "как дела, хозяин?",
    "сажусь за стол и осматриваюсь",
    "заказываю эль",
    "подхожу к стойке",
]


def test_disruptive_lines_match():
    for t in DISRUPTIVE:
        assert _DISRUPTIVE_RE.search(t), f"should be disruptive: {t!r}"


def test_benign_lines_do_not_match():
    for t in BENIGN:
        assert not _DISRUPTIVE_RE.search(t), f"should NOT be disruptive: {t!r}"
