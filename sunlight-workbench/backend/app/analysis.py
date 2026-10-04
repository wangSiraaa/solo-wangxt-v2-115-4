"""日照分析核心：逐时采样 与 连续遮挡时段 是两套独立口径。

- 逐时采样(hourly)：只在每个整点判定 晒到/遮挡/夜晚，用于快速浏览，
  **不能**把整点晴亮直接累加成"日照小时数"。
- 连续时段(continuous)：用细步长（默认 5 分钟）扫描全天，输出最大连续
  晒到/遮挡区间及其遮挡物集合，这才是"连续日照时段"口径。
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
    window_id: str = ""                 # 同一窗面的测点共用；空串视为各自独立


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
        "window_id": point.window_id,
        "hourly_samples": hourly,          # 逐时口径（快览）
        "continuous_intervals": to_intervals(fine),  # 连续口径（时段）
        "fine_samples": fine,
        "step_minutes": step_minutes,
        "summary": summarize(fine, step_minutes),
    }


# ---------- 窗面测点覆盖统计（基于现有 window_id 分组，不生成新网格） ----------

def _full_coverage_intervals(timeline: list[dict],
                             step_minutes: int) -> list[dict]:
    """完整覆盖（该窗全部测点同时晒到）的最大连续时段。

    时段按细步长相邻判定延伸；夜间本就不在 timeline 中，天然被排除。
    """
    intervals: list[dict] = []
    prev_time = None
    prev_full = False
    for e in timeline:
        t = pd.Timestamp(e["time"])
        full = e["sunlit"] == e["total"]
        adjacent = (prev_time is not None
                    and t - prev_time == pd.Timedelta(minutes=step_minutes))
        if full and prev_full and adjacent:
            intervals[-1]["end"] = e["time"]
            intervals[-1]["samples"] += 1
        elif full:
            intervals.append({"start": e["time"], "end": e["time"],
                              "samples": 1})
        prev_time, prev_full = t, full
    for iv in intervals:
        iv["minutes"] = iv["samples"] * step_minutes
    return intervals


def analyze_windows(point_results: list[dict], *,
                    step_minutes: int) -> list[dict]:
    """窗面测点覆盖统计：同一 window_id 的测点为一组，逐时刻汇总。

    口径（现有离散测点的示例统计，非面积加权、非规范条文）：
    - 只统计有太阳的细采样时刻；夜间（全组太阳在地平线下）整行剔除，
      **不计入分母**；
    - 每个白天时刻 coverage = 晒到测点数 / 该窗测点总数——一个点晒到
      不代表整窗晒到，3 个测点只晒到 1 个时覆盖率为 1/3；
    - average_coverage = 白天各时刻 coverage 的算术平均；
    - full_coverage_intervals = 完整覆盖（coverage=1）的最大连续时段。
    无 window_id 的测点各自成组，不同窗面的测点绝不混算。
    """
    groups: dict[str, list[dict]] = {}
    for r in point_results:
        key = r["window_id"] or f"__point__{r['point_id']}"
        groups.setdefault(key, []).append(r)

    out = []
    for key in sorted(groups):
        members = sorted(groups[key], key=lambda r: str(r["point_id"]))
        window_id = members[0]["window_id"]
        # 同一运行共用同一时间网格，以时间为键对齐各测点细样本
        per_point = [{s["time"]: s for s in r["fine_samples"]}
                     for r in members]
        common = sorted(set.intersection(*(set(p) for p in per_point)))
        timeline = []
        for t in common:
            samples = [p[t] for p in per_point]
            if all(s["status"] == STATUS_NIGHT for s in samples):
                continue  # 夜间不计入分母
            sunlit = sum(1 for s in samples if s["status"] == STATUS_SUNLIT)
            total = len(samples)
            timeline.append({
                "time": t,
                "elevation": max(s["elevation"] for s in samples),
                "sunlit": sunlit,
                "total": total,
                "coverage": round(sunlit / total, 4),
                "points": [{
                    "point_id": r["point_id"], "name": r["point_name"],
                    "status": s["status"], "occluder": s.get("occluder"),
                } for r, s in zip(members, samples)],
            })
        full = _full_coverage_intervals(timeline, step_minutes)
        avg = (round(sum(e["coverage"] for e in timeline) / len(timeline), 4)
               if timeline else 0.0)
        out.append({
            "window_id": window_id,
            "point_ids": [r["point_id"] for r in members],
            "summary": {
                "window_id": window_id,
                "point_ids": [r["point_id"] for r in members],
                "point_names": [r["point_name"] for r in members],
                "point_count": len(members),
                "daylight_samples": len(timeline),
                "average_coverage": avg,
                "full_coverage_intervals": full,
                "full_coverage_minutes":
                    sum(iv["samples"] for iv in full) * step_minutes,
                "longest_full_coverage_minutes":
                    max((iv["samples"] for iv in full), default=0) * step_minutes,
                "criterion": ("示例口径：窗面覆盖率=晒到测点数/该窗测点总数，"
                              "为现有离散测点的示例统计（非面积加权），"
                              "不构成规划合规结论"),
            },
            "timeline": timeline,
        })
    return out
