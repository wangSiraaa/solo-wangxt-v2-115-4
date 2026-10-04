import React, { useMemo, useState } from 'react'
import { fmtMin, fmtTime, coverageColor, pct } from '../util.js'

const STATUS_LABEL = { sunlit: '晒到', shaded: '遮挡', night: '夜间' }

function nearestSample(samples, time) {
  if (!time) return null
  let best = null
  for (const s of samples) {
    if (!best || Math.abs(s.time.localeCompare(time)) <
      Math.abs(best.time.localeCompare(time))) best = s
  }
  return best
}

/** 窗面测点覆盖时间轴：
    覆盖率 = 该窗面**现有离散测点**中无遮挡测点数 / 同窗测点数，
    只统计有太阳的细采样时刻（夜间不入分母，也不画入时间轴）。 */
export default function WindowCoverage({ run, payload, activeTime,
  onPickTime, onSelectPoint }) {
  const windows = run?.windows ?? []
  const [wid, setWid] = useState(null)
  const win = windows.find((w) => w.window_id === wid) ?? windows[0]

  // point_id -> { time: fine_sample }，与逐点 trace 同一份 fine_samples
  const pointSamples = useMemo(() => {
    const m = {}
    for (const r of run?.results ?? []) {
      m[r.point_id] = Object.fromEntries(r.fine_samples.map((s) => [s.time, s]))
    }
    return m
  }, [run])
  const pointName = (id) =>
    payload?.points?.find((p) => p.id === id)?.name ?? `测点 #${id}`

  if (!windows.length) {
    return <div className="muted small">本次运行无窗面覆盖统计。</div>
  }

  // 当前时刻落在哪个白天样本（与 App 里取最近样本同一口径）
  const activeSample = win ? nearestSample(win.samples, activeTime) : null
  const activeExact = win && activeTime && activeSample &&
    win.samples.some((s) => s.time === activeTime)
  const step = run.step_minutes

  return (
    <div className="window-coverage">
      <h4>窗面测点覆盖（现有离散测点示例统计，非新网格）</h4>
      <div className="muted small">{run.window_coverage_note}</div>
      <div className="win-tabs">
        {windows.map((w) => (
          <button key={w.window_id}
            className={win?.window_id === w.window_id ? 'active' : ''}
            onClick={() => setWid(w.window_id)}
            title={`${w.point_count} 个同窗测点：${w.point_ids.map(pointName).join('、')}`}>
            {w.label}{w.point_count > 1 ? ` (${w.point_count}点)` : ''}
          </button>
        ))}
      </div>

      {win && (
        <>
          <table className="summary">
            <tbody>
              <tr><td>白天平均覆盖率</td><td>
                <b>{pct(win.summary.mean_coverage)}</b>
                <span className="muted small"> （{win.point_count} 个测点 ×
                  {' '}{win.summary.daylight_samples} 个白天时刻，晒到点次/总点次）</span>
              </td></tr>
              <tr><td>最长连续完整覆盖</td><td>
                {fmtMin(win.summary.full_coverage_minutes)}
                {win.summary.full_interval_count > 0 &&
                  <span className="muted small">（共 {win.summary.full_interval_count} 段，
                    累计 {fmtMin(win.summary.total_full_coverage_minutes)}）</span>}
              </td></tr>
            </tbody>
          </table>
          <div className="muted small">{win.summary.criterion}</div>

          {win.full_intervals.length > 0 && (
            <>
              <div className="muted small">完整覆盖时段（{step} min 步长，夜间自动断开）：</div>
              <div className="intervals">
                {win.full_intervals.map((iv, i) => (
                  <span key={i} className="interval sunlit"
                    onClick={() => onPickTime?.(iv.start)}
                    title="点选跳到该时刻">
                    {fmtTime(iv.start)}–{fmtTime(iv.end)}
                  </span>
                ))}
              </div>
            </>
          )}

          <div className="muted small">
            白天覆盖时间轴（每格 {step} min；点击查看该时刻各测点与遮挡物；夜间不入图）
          </div>
          <div className="cov-axis">
            {win.samples.map((s, i) => {
              const ratio = s.sunlit / s.total
              const selected = activeSample && activeSample.time === s.time
              // 每整点给一个刻度
              const tick = s.time.slice(11, 14) === '00'
              return (
                <span key={s.time} className="cov-cell-wrap">
                  <span className={`cov-cell${selected ? ' selected' : ''}`}
                    style={{ background: coverageColor(ratio) }}
                    onClick={() => onPickTime?.(s.time)}
                    title={`${fmtTime(s.time)} 覆盖率 ${s.sunlit}/${s.total} = ${pct(ratio)}`} />
                  {tick && i !== 0 &&
                    <span className="cov-tick">{s.time.slice(11, 16)}</span>}
                </span>
              )
            })}
          </div>
          <div className="cov-legend muted small">
            <span style={{ background: coverageColor(0) }} />0%
            <span style={{ background: coverageColor(0.5) }} />50%
            <span style={{ background: coverageColor(1) }} />100%
            <span>（晒到测点数/同窗测点数）</span>
          </div>

          <div className="cov-detail">
            <div className="muted small">
              {activeSample
                ? <>时刻 <b>{fmtTime(activeSample.time)}</b> 覆盖率
                  {' '}<b>{activeSample.sunlit}/{activeSample.total}</b>
                  {!activeExact && '（取最近白天样本）'}</>
                : '当前为夜间，无白天样本；请在时间轴上点选白天时刻。'}
            </div>
            {activeSample && win.point_ids.map((id) => {
              const s = pointSamples[id]?.[activeSample.time]
              const status = s?.status ?? 'night'
              return (
                <div key={id}
                  className={`cov-point ${status}`}
                  onClick={() => onSelectPoint?.(id)}
                  title="点选查看该测点的单点结果与追查">
                  <span className="dot" />
                  <span className="pname">{pointName(id)}</span>
                  <span className="pstatus">
                    {STATUS_LABEL[status]}
                    {s?.occluder ? ` · 遮挡物：${s.occluder}` : ''}
                  </span>
                </div>
              )
            })}
          </div>
        </>
      )}
    </div>
  )
}
