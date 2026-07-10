from aidnd.server.play.engine.session.config import PB
from aidnd.server.play.engine.world import _work_lift


def test_worker_on_shift_gets_lift():
    # кузница open 7-18 (open_hours canonical); 10:00 = 600 min
    lift = _work_lift("smith", {"smith"}, "Кузница «Железный зуб»", 10 * 60)
    assert lift == PB["workplace_purpose_lift"] > 0


def test_worker_off_hours_no_lift():
    # 03:00 = 180 min — smithy closed
    assert _work_lift("smith", {"smith"}, "Кузница «Железный зуб»", 3 * 60) == 0.0


def test_non_worker_no_lift():
    assert _work_lift("guest", {"smith"}, "Кузница «Железный зуб»", 10 * 60) == 0.0
