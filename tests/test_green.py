from siof.green_guard import GreenGuard


def test_green_run(tmp_path):
    g = GreenGuard(db_path=tmp_path / "siof.db")
    out = g.run_command(["python3", "-c", "print('ok')"])
    rep = g.report(out["run_id"])
    g.close()

    assert out["run_id"]
    assert rep["run_id"] == out["run_id"]
