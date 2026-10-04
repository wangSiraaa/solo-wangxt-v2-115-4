"""日照分析核心：逐时采样 与 连续遮挡时段 是两套独立口径。

- 逐时采样(hourly)：只在每个整点判定 晒到/遮挡/夜晚，用于快速浏览，
  **不能**把整点晴亮直接累加成"日照小时数"。
- 连续时段(continuous)：用细步长（默认 5 分钟）扫描全天，输出最大连续
  晒到/遮挡区间及其遮挡物集合，这才是"连续日照时段"口径。
- 窗面覆盖(window coverage)：把一次运行中**同一 window_id 的现有离散
  测点**分在一组（不生成新网格），在每个有太阳的细采样时刻统计
  "晒到测点数/同窗测点数"；夜间样本不计入分母。逐点状态仍以细样本为
  唯一数据源，因此"一个点晒到"不等于整窗晒到（3 个点只 1 个晒到 → 1/3）。
每个采样都记录遮挡物名称，支持单点追查。
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .geometry import BuiltScene, cast_sun_ray, RAY_ORIGIN_OFFSET
from .solar import enu_to_model, sun_vector_enu, solar_positions

STATUS_NIGHT = "night"      # 太阳在地平线下，不参与日照统计
STATUS_SUNLIT = "sunlit"
STATUS_SHADED = "shaded"


@dataclass
class MeasurePointGeom:
    id: str
    name: str
    position: tuple[float, float, float]
    normal: tuple[float, float, float]  # 窗面外法线（模型坐标）
    host_building: str | None = None
    window_id: str = ""                 # 同一窗面可布多个测点


def _flags_at_times(scene: BuiltScene, point: MeasurePointGeom,
                    times_local: pd.DatetimeIndex,
                    latitude: float, longitude: float,
                    north_offset_deg: float) -> list[dict]:
    pos = solar_positions(latitude, longitude, str(times_local.tz), times_local)
    origin = np.array(point.position) + np.array(point.normal) * RAY_ORIGIN_OFFSET
    out = []
    for t, row in zip(times_local, pos.itertuples()):
        el = float(row.apparent_elevation)
        az = float(row.azimuth)
        if el <= 0:
            out.append({"time": t.isoformat(), "status": STATUS_NIGHT,
                        "elevation": round(el, 3), "azimuth": round(az, 3),
                        "occluder": None})
            continue
        d = enu_to_model(sun_vector_enu(el, az), north_offset_deg)
        hit = cast_sun_ray(scene, origin, d)
        out.append({
            "time": t.isoformat(),
            "status": STATUS_SHADED if hit else STATUS_SUNLIT,
            "elevation": round(el, 3), "azimuth": round(az, 3),
            "occluder": hit["occluder"] if hit else None,
            "occluder_distance": hit["distance"] if hit else None,
            "hit_point": hit["hit_point"] if hit else None,
        })
    return out


def to_intervals(samples: list[dict]) -> list[dict]:
    """把细步长采样折叠成最大连续区间（含遮挡物集合）。"""
    intervals = []
    for s in samples:
        if (intervals and intervals[-1]["status"] == s["status"]
                and intervals[-1]["occluder"] == s["occluder"]):
            intervals[-1]["end"] = s["time"]
            intervals[-1]["samples"] += 1
        else:
            intervals.append({"start": s["time"], "end": s["time"],
                              "status": s["status"], "occluder": s["occluder"],
                              "samples": 1})
    return intervals


def summarize(samples: list[dict], step_minutes: int) -> dict:
    """示例评价口径（非规划合规结论）：

    - daylight_minutes: 白天（太阳在地平线上）总分钟数
    - sunlit_minutes:   连续口径下晒到太阳的分钟数
    - longest_continuous_sunlit_minutes: 最长连续日照时长
    """
    day = [s for s in samples if s["status"] != STATUS_NIGHT]
    sunlit = [s for s in day if s["status"] == STATUS_SUNLIT]
    longest = 0
    run = 0
    for s in day:
        run = run + 1 if s["status"] == STATUS_SUNLIT else 0
        longest = max(longest, run)
    return {
        "daylight_minutes": len(day) * step_minutes,
        "sunlit_minutes": len(sunlit) * step_minutes,
        "longest_continuous_sunlit_minutes": longest * step_minutes,
        "criterion": "示例口径：连续时段扫描，非任何规范条文",
    }


def analyze_point(scene: BuiltScene, point: MeasurePointGeom, *,
                  latitude: float, longitude: float, tz: str, date: str,
                  north_offset_deg: float, step_minutes: int = 5) -> dict:
    from .solar import local_time_grid, hourly_times
    fine_times = local_time_grid(date, tz, step_minutes)
    fine = _flags_at_times(scene, point, fine_times, latitude, longitude,
                           north_offset_deg)
    hourly = _flags_at_times(scene, point, hourly_times(date, tz),
                             latitude, longitude, north_offset_deg)
    return {
        "point_id": point.id,
        "point_name": point.name,
        "window_id": getattr(point, "window_id", "") or "",
        "hourly_samples": hourly,          # 逐时口径（快览）
        "continuous_intervals": to_intervals(fine),  # 连续口径（时段）
        "fine_samples": fine,
        "step_minutes": step_minutes,
        "summary": summarize(fine, step_minutes),
    }


# ---------- 窗面覆盖（现有离散测点的示例统计，非新网格） ----------

WINDOW_FALLBACK_PREFIX = "__point_"
WINDOW_COVERAGE_CRITERION = (
    "示例口径：对该窗面已布设的离散测点统计，未生成新网格、未做窗面插值；"
    "覆盖率=晒到测点数/同窗测点数，仅在太阳位于地平线上的细采样时刻计入。")


def window_key_of(window_id: str | None, point_id) -> str:
    """测点 -> 窗面分组键。有 window_id 归该窗；否则该点单独成组，
    保证没有窗号的测点不会互相混算。"""
    window_id = (window_id or "").strip()
    return window_id if window_id else f"{WINDOW_FALLBACK_PREFIX}{point_id}"


def window_coverages(point_results: list[dict], step_minutes: int) -> list[dict]:
    """按 window_id 聚合一次运行的各测点细样本，输出每窗面的覆盖统计。

    入参 point_results: analyze_point() 的返回列表（每个含 point_id /
    point_name / window_id / fine_samples）。
    同一时刻网格上的同窗测点逐时刻配对；任一测点夜间即视为该时刻无太阳，
    夜间不计入分母；同一时刻网格的连续性按采样下标判定，天然不跨夜合并。
    """
    groups: dict[str, list[dict]] = {}
    for r in point_results:
        key = window_key_of(r.get("window_id"), r["point_id"])
        groups.setdefault(key, []).append(r)

    out = []
    for key, members in groups.items():
        members.sort(key=lambda m: int(m["point_id"]))
        point_ids = [int(m["point_id"]) for m in members]
        # 各测点使用同一时间网格生成；以第一个测点的网格为基准对齐
        base = members[0]["fine_samples"]
        per_point = [{s["time"]: s for s in m["fine_samples"]} for m in members]
        samples = []
        full_run = 0
        longest_full = 0
        full_intervals = []
        for idx, s0 in enumerate(base):
            at = [pm.get(s0["time"]) for pm in per_point]
            if any(a is None for a in at):
                raise ValueError("同窗测点细样本时间网格不一致，无法配对")
            # 夜间（太阳在地平线下）不计入窗面覆盖
            if any(a["status"] == STATUS_NIGHT for a in at):
                continue
            sunlit = sum(1 for a in at if a["status"] == STATUS_SUNLIT)
            total = len(at)
            samples.append({"time": s0["time"], "sunlit": sunlit, "total": total})
            is_full = sunlit == total
            if is_full:
                full_run += 1
                longest_full = max(longest_full, full_run)
                if full_run == 1:
                    full_intervals.append({"start": s0["time"], "end": s0["time"],
                                           "samples": 1})
                else:
                    iv = full_intervals[-1]
                    iv["end"] = s0["time"]
                    iv["samples"] += 1
            else:
                full_run = 0

        daylight_samples = len(samples)
        mean = (sum(x["sunlit"] for x in samples)
                / sum(x["total"] for x in samples)) if samples else 0.0
        singleton = key.startswith(WINDOW_FALLBACK_PREFIX)
        out.append({
            "window_id": key,
            "label": key if not singleton
            else (members[0].get("point_name") or f"测点 #{point_ids[0]}"),
            "singleton": singleton,
            "point_ids": point_ids,
            "point_count": len(point_ids),
            "samples": samples,
            "full_intervals": full_intervals,
            "summary": {
                "daylight_samples": daylight_samples,
                "mean_coverage": round(mean, 4),
                "full_coverage_minutes": longest_full * step_minutes,
                "total_full_coverage_minutes": sum(
                    iv["samples"] for iv in full_intervals) * step_minutes,
                "full_interval_count": len(full_intervals),
                "criterion": WINDOW_COVERAGE_CRITERION,
            },
        })
    out.sort(key=lambda w: (w["singleton"], w["window_id"]))
    return out
