"""窗面覆盖统计的手算核对测试。

教学核心：窗面上"一个点晒到"不等于整窗晒到——覆盖率只数该窗面
**现有离散测点**（不生成新网格），3 个测点只 1 个晒到就是 1/3。
夜间样本不计入分母；不同 window_id 绝不混算。
"""
from app.analysis import (analyze_point, window_coverages, window_key_of)
from app.seed import scene_specs, LAT, LON, TZ

STEP = 5
TZ0 = "+08:00"


def _pt(point_id, window_id, statuses):
    """把 (time, status, occluder) 序列构造成一个测点的 fine_samples。"""
    def s(h, m):
        return f"2026-01-15T{h:02d}:{m:02d}:00{TZ0}"

    return {
        "point_id": point_id, "point_name": f"P{point_id}",
        "window_id": window_id,
        "fine_samples": [
            {"time": s(7, 0), "status": "night", "occluder": None},
            {"time": s(8, 0), "status": statuses[0],
             "occluder": "B1" if statuses[0] == "shaded" else None},
            {"time": s(9, 0), "status": statuses[1],
             "occluder": "B1" if statuses[1] == "shaded" else None},
            {"time": s(10, 0), "status": statuses[2],
             "occluder": "B1" if statuses[2] == "shaded" else None},
            {"time": s(18, 0), "status": "night", "occluder": None},
        ],
    }


def test_one_of_three_is_one_third_not_full():
    """验收：同窗三个测点只有一个晒到 → 覆盖率 1/3，而非 100%。"""
    results = [
        _pt(1, "W1", ("sunlit", "shaded", "sunlit")),
        _pt(2, "W1", ("shaded", "shaded", "sunlit")),
        _pt(3, "W1", ("shaded", "shaded", "sunlit")),
    ]
    cov = window_coverages(results, STEP)
    assert len(cov) == 1
    w = cov[0]
    assert w["window_id"] == "W1" and w["point_count"] == 3
    # 夜间两个样本被剔除，只剩 3 个白天样本
    assert w["summary"]["daylight_samples"] == 3
    # 8:00 只 1/3 晒到；逐时刻分子分母都落库
    assert w["samples"][0] == {"time": w["samples"][0]["time"],
                               "sunlit": 1, "total": 3}
    assert w["samples"][1]["sunlit"] == 0
    assert w["samples"][2]["sunlit"] == 3
    # 平均 = (1+0+3)/(3+3+3) = 4/9，绝不是 1.0
    assert w["summary"]["mean_coverage"] == round(4 / 9, 4)
    assert w["summary"]["mean_coverage"] < 0.5


def test_full_coverage_intervals_and_night_excluded():
    """完整覆盖=全部测点同时晒到；夜间打断连续性且不计入分母。"""
    results = [
        _pt(1, "W1", ("sunlit", "shaded", "sunlit")),
        _pt(2, "W1", ("sunlit", "shaded", "sunlit")),
    ]
    w = window_coverages(results, STEP)[0]
    # 仅 8:00 与 10:00 完整覆盖；二者被 9:00 隔开 → 两个时段，各 5 分钟
    assert [(iv["start"][11:16], iv["end"][11:16], iv["samples"])
            for iv in w["full_intervals"]] == [
        ("08:00", "08:00", 1), ("10:00", "10:00", 1)]
    assert w["summary"]["full_coverage_minutes"] == STEP       # 最长连续
    assert w["summary"]["total_full_coverage_minutes"] == 2 * STEP
    assert w["summary"]["daylight_samples"] == 3


def test_different_windows_never_mixed():
    """不同窗面（含无 window_id 测点）各自成组，不混算。"""
    results = [
        _pt(1, "W1", ("sunlit", "sunlit", "sunlit")),
        _pt(2, "W2", ("shaded", "shaded", "shaded")),
        _pt(3, "", ("sunlit", "shaded", "sunlit")),
        _pt(4, "", ("shaded", "sunlit", "shaded")),
    ]
    cov = {w["window_id"]: w for w in window_coverages(results, STEP)}
    assert set(cov) == {"W1", "W2", window_key_of("", 3),
                        window_key_of("", 4)}
    assert cov["W1"]["summary"]["mean_coverage"] == 1.0
    assert cov["W2"]["summary"]["mean_coverage"] == 0.0
    # 两个无窗号测点即便状态互补也不并组：各自是 2/3 与 1/3
    assert cov[window_key_of("", 3)]["point_count"] == 1
    assert cov[window_key_of("", 3)]["summary"]["mean_coverage"] == round(2 / 3, 4)
    assert cov[window_key_of("", 4)]["summary"]["mean_coverage"] == round(1 / 3, 4)


def test_seed_scene_window_grouping_with_real_geometry():
    """用真实几何+pvl ib 跑种子场景：W1 三测点同组、E1 单测点成组，
    且逐时刻晒到数不超过同窗测点数。"""
    from types import SimpleNamespace as NS
    from geoalchemy2.shape import from_shape
    from shapely.geometry import Point, Polygon

    spec = scene_specs()[0]
    scene = NS(latitude=LAT, longitude=LON, timezone=TZ,
               north_offset_deg=spec["north_offset_deg"])
    buildings = [NS(id=i, name=b["name"], kind=b["kind"], color=b["color"],
                    footprint=from_shape(Polygon(b["footprint"]), srid=0),
                    base_height=b["base_height"], top_height=b["top_height"])
                 for i, b in enumerate(spec["buildings"], 1)]
    points = [NS(id=i, name=p["name"], window_id=p["window_id"],
                 geom=from_shape(Point(*p["position"]), srid=0),
                 normal=list(p["normal"]))
              for i, p in enumerate(spec["points"], 1)]
    from app.main import _geom_from_bundle
    built, pts = _geom_from_bundle(buildings, points)
    analyzed = [analyze_point(built, pt, latitude=scene.latitude,
                              longitude=scene.longitude, tz=scene.timezone,
                              date="2026-01-15",
                              north_offset_deg=scene.north_offset_deg,
                              step_minutes=30)
                for pt in pts]
    cov = {w["window_id"]: w for w in window_coverages(analyzed, 30)}
    assert set(cov) == {"W1", "W2", "W3", "E1"}
    w1 = cov["W1"]
    assert w1["point_count"] == 3 and w1["point_ids"] == [1, 2, 3]
    for smp in w1["samples"]:
        assert 0 <= smp["sunlit"] <= smp["total"] == 3
    # 白天样本数与单点白天样本数一致（夜间未混入分母）
    day_per_point = sum(1 for s in analyzed[0]["fine_samples"]
                        if s["status"] != "night")
    assert w1["summary"]["daylight_samples"] == day_per_point
    # 完整覆盖时段的逐时刻确实三个点都 sunlit（与 fine_samples 同源）
    by_time = {s["time"]: [a["fine_samples"][i]["status"]
                           for a in analyzed]
               for i, s in enumerate(analyzed[0]["fine_samples"])}
    for iv in w1["full_intervals"]:
        assert by_time[iv["start"]] == ["sunlit"] * 3
