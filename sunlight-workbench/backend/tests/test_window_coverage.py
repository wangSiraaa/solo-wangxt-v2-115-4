"""窗面测点覆盖统计测试（验收口径）。

核心验收：同窗 3 个测点只有 1 个晒到时，该时刻覆盖率为 1/3 而非 100%；
夜间不计入分母；不同 window_id 的测点不混算；完整覆盖时段按细步长折叠；
真实场景算出的窗面时间轴与逐点 fine_samples（trace 数据源）逐样本一致。
"""
import pytest

from app.analysis import (MeasurePointGeom, analyze_point, analyze_windows,
                          STATUS_NIGHT, STATUS_SUNLIT, STATUS_SHADED)
from app.geometry import BuildingGeom, build_scene
from app.seed import scene_specs

T = "2026-01-15T{h:02d}:{m:02d}:00+08:00"
STEP = 5


def _s(h, m, status, occluder=None):
    return {"time": T.format(h=h, m=m),
            "status": status,
            "elevation": 20.0 if status != STATUS_NIGHT else -8.0,
            "azimuth": 180.0, "occluder": occluder}


def _res(pid, window_id, samples):
    return {"point_id": pid, "point_name": f"测点{pid}",
            "window_id": window_id, "fine_samples": samples}


def test_one_of_three_sunlit_coverage_is_one_third():
    """验收：同窗 3 测点只晒到 1 个 → 覆盖率 1/3，而非 100%。"""
    day = [(9, 0), (9, 5), (9, 10)]
    r1 = _res(1, "W1", [_s(h, m, STATUS_SUNLIT) for h, m in day])
    r2 = _res(2, "W1", [_s(h, m, STATUS_SHADED, "B1") for h, m in day])
    r3 = _res(3, "W1", [_s(h, m, STATUS_SHADED, "B1") for h, m in day])
    (w,) = analyze_windows([r1, r2, r3], step_minutes=STEP)
    assert w["window_id"] == "W1"
    assert len(w["timeline"]) == 3
    for e in w["timeline"]:
        assert e["sunlit"] == 1 and e["total"] == 3
        assert e["coverage"] == pytest.approx(1 / 3, abs=1e-4)
        assert e["coverage"] != 1.0
    assert w["summary"]["average_coverage"] == pytest.approx(1 / 3, abs=1e-4)
    assert w["summary"]["full_coverage_intervals"] == []
    assert w["summary"]["longest_full_coverage_minutes"] == 0


def test_night_excluded_from_denominator():
    """夜间样本整行剔除：平均分母只含白天时刻。"""
    samples = [_s(7, 0, STATUS_NIGHT), _s(7, 5, STATUS_NIGHT),
               _s(12, 0, STATUS_SUNLIT), _s(12, 5, STATUS_SHADED, "B1"),
               _s(19, 0, STATUS_NIGHT)]
    (w,) = analyze_windows([_res(1, "W1", samples)], step_minutes=STEP)
    assert w["summary"]["daylight_samples"] == 2
    assert [e["time"] for e in w["timeline"]] == [
        T.format(h=12, m=0), T.format(h=12, m=5)]
    # (1 + 0) / 2 个白天样本 = 0.5；若夜间计入分母则得 1/5
    assert w["summary"]["average_coverage"] == pytest.approx(0.5)


def test_different_windows_not_mixed():
    """不同 window_id 各自成组；无 window_id 的测点也绝不合并。"""
    day = [(10, 0), (10, 5)]
    r1 = _res(1, "W1", [_s(h, m, STATUS_SUNLIT) for h, m in day])
    r2 = _res(2, "W1", [_s(h, m, STATUS_SHADED, "B1") for h, m in day])
    r3 = _res(3, "W2", [_s(h, m, STATUS_SUNLIT) for h, m in day])
    r4 = _res(4, "", [_s(h, m, STATUS_SUNLIT) for h, m in day])
    r5 = _res(5, "", [_s(h, m, STATUS_SHADED, "B2") for h, m in day])
    ws = analyze_windows([r1, r2, r3, r4, r5], step_minutes=STEP)
    by_key = {(w["window_id"], tuple(w["point_ids"])): w for w in ws}
    assert len(ws) == 4  # W1 / W2 / 两个匿名单点各自独立
    w1 = by_key[("W1", (1, 2))]
    assert all(e["coverage"] == pytest.approx(0.5) for e in w1["timeline"])
    assert by_key[("W2", (3,))]["summary"]["average_coverage"] == 1.0
    anon = [w for (wid, _), w in by_key.items() if wid == ""]
    assert len(anon) == 2
    assert sorted(w["summary"]["average_coverage"] for w in anon) == [0.0, 1.0]


def test_full_coverage_intervals_folded_by_step():
    """完整覆盖（全部测点晒到）的最大连续时段按细步长折叠。"""
    seq = [STATUS_SUNLIT, STATUS_SUNLIT, STATUS_SHADED,
           STATUS_SUNLIT, STATUS_SUNLIT, STATUS_SUNLIT]
    ra = _res(1, "W1", [_s(9, i * STEP, s) for i, s in enumerate(seq)])
    rb = _res(2, "W1", [_s(9, i * STEP, s) for i, s in enumerate(seq)])
    (w,) = analyze_windows([ra, rb], step_minutes=STEP)
    iv = w["summary"]["full_coverage_intervals"]
    assert [(i["start"], i["samples"]) for i in iv] == [
        (T.format(h=9, m=0), 2), (T.format(h=9, m=15), 3)]
    assert iv[0]["end"] == T.format(h=9, m=5)
    assert w["summary"]["full_coverage_minutes"] == 5 * STEP
    assert w["summary"]["longest_full_coverage_minutes"] == 3 * STEP


# ---------- 真实场景：时间轴与逐点 trace 数据源一致 ----------

def _run_seed(spec_idx, date, step=30):
    spec = scene_specs()[spec_idx]
    geoms = [BuildingGeom(name=b["name"], footprint=b["footprint"],
                          base_height=b["base_height"],
                          top_height=b["top_height"])
             for b in spec["buildings"]]
    built = build_scene(geoms)
    results = []
    for i, p in enumerate(spec["points"], 1):
        pt = MeasurePointGeom(id=str(i), name=p["name"],
                              position=p["position"], normal=p["normal"],
                              window_id=p["window_id"])
        r = analyze_point(built, pt, latitude=39.9042, longitude=116.4074,
                          tz="Asia/Shanghai", date=date,
                          north_offset_deg=spec["north_offset_deg"],
                          step_minutes=step)
        r["point_id"] = i
        results.append(r)
    return results, analyze_windows(results, step_minutes=step)


def test_seed_w1_grouping_and_partial_coverage():
    """种子场景 W1 窗 3 个测点同组；夏季存在部分覆盖时刻（0<c<1）。"""
    _, windows = _run_seed(0, "2026-07-15")
    by_id = {w["window_id"]: w for w in windows}
    assert set(by_id) == {"W1", "W2", "W3", "E1"}
    w1 = by_id["W1"]
    assert len(w1["point_ids"]) == 3
    assert all(e["total"] == 3 for e in w1["timeline"])
    assert any(0 < e["coverage"] < 1 for e in w1["timeline"])
    # 单测点窗的覆盖率只能取 0/1
    assert all(e["coverage"] in (0.0, 1.0) for e in by_id["W2"]["timeline"])


def test_window_timeline_matches_point_trace():
    """刷新一致性：窗面时间轴每格各测点状态/遮挡物 == 该点 fine_samples。"""
    results, windows = _run_seed(0, "2026-01-15")
    traces = {r["point_id"]: {s["time"]: s for s in r["fine_samples"]}
              for r in results}
    for w in windows:
        for e in w["timeline"]:
            for p in e["points"]:
                s = traces[p["point_id"]][e["time"]]
                assert p["status"] == s["status"]
                assert p["occluder"] == s["occluder"]
            # 覆盖率定义核对：晒到数/总数，夜间不在时间轴中
            assert e["coverage"] == pytest.approx(
                e["sunlit"] / e["total"], abs=1e-4)
            assert any(traces[p["point_id"]][e["time"]]["status"]
                       != STATUS_NIGHT for p in e["points"])
        # 平均覆盖率 = 时间轴覆盖率算术平均（分母仅白天样本）
        assert w["summary"]["average_coverage"] == pytest.approx(
            sum(e["coverage"] for e in w["timeline"]) / len(w["timeline"]),
            abs=1e-4)


def test_window_coverage_rotation_invariance():
    """S1 与 S2（旋转 30°，物理等价）同窗覆盖率时间轴逐样本一致。"""
    _, w1 = _run_seed(0, "2026-01-15")
    _, w2 = _run_seed(1, "2026-01-15")
    cov1 = {w["window_id"]: [e["coverage"] for e in w["timeline"]]
            for w in w1}
    cov2 = {w["window_id"]: [e["coverage"] for e in w["timeline"]]
            for w in w2}
    assert cov1.keys() == cov2.keys()
    for wid in cov1:
        assert cov1[wid] == pytest.approx(cov2[wid], abs=1e-9), wid
