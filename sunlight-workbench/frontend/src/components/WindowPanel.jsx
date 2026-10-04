import React, { useState } from 'react'
import { fmtMin, fmtTime, STATUS_COLOR } from '../util.js'

/* 覆盖率配色：0=遮挡蓝 → 1=日照金（与测点状态色一致） */
function covColor(c) {
  const a = [0x4a, 0x6f, 0xa5]
  const b = [0xf6, 0xc4, 0x53]
  const m = a.map((v, i) => Math.round(v + (b[i] - v) * c))
  return `rgb(${m[0]},${m[1]},${m[2]})`
}

function frac(e) {
  return `${e.sunlit}/${e.total}`
}

/** 单个窗面的覆盖时间轴：每个白天细采样时刻一格，颜色=覆盖率。
    点选某格展示该时刻各测点状态及遮挡物。 */
function WindowTimeline({ w, sel, onSelect }) {
  const tl = w.timeline
  if (!tl.length) return <div className="muted small">当日无白天样本。</div>
  const selEntry = sel && tl.find((e) => e.time === sel)
  return (
    <>
      <svg className="win-timeline" viewBox={`0 0 ${tl.length} 10`}
        preserveAspectRatio="none">
        {tl.map((e, i) => (
          <rect key={e.time} x={i} y={0} width={1} height={10}
            fill={covColor(e.coverage)}
            stroke={sel === e.time ? '#ff4081' : 'none'}
            strokeWidth={sel === e.time ? 0.35 : 0}
            onClick={() => onSelect(sel === e.time ? null : e.time, e.time)}>
            <title>{fmtTime(e.time)} 覆盖 {frac(e)}（{(e.coverage * 100).toFixed(0)}%）</title>
          </rect>
        ))}
      </svg>
      <div className="win-axis muted small">
        <span>{fmtTime(tl[0].time)}</span>
        <span>仅白天时刻 · 夜间不计入分母</span>
        <span>{fmtTime(tl[tl.length - 1].time)}</span>
      </div>
      {selEntry && (
        <div className="win-detail">
          <div>
            <b>{fmtTime(selEntry.time)}</b> 覆盖率 <b>{frac(selEntry)}</b>
            （{(selEntry.coverage * 100).toFixed(1)}%）
            · 高度角 {selEntry.elevation.toFixed(1)}°
          </div>
          {selEntry.points.map((p) => (
            <div key={p.point_id} className="win-pt">
              <span className="dot"
                style={{ background: STATUS_COLOR[p.status] ?? '#999' }} />
              <span>{p.name}</span>
              <span className="muted">
                {p.status === 'sunlit' ? '晒到'
                  : p.status === 'night' ? '夜间' : `遮挡：${p.occluder}`}
              </span>
            </div>
          ))}
        </div>
      )}
    </>
  )
}

/** 窗面覆盖统计面板：同一 window_id 的离散测点为一组。
    覆盖率 = 晒到测点数/测点总数（现有离散测点的示例统计，非面积加权）。 */
export default function WindowPanel({ run, onPickTime }) {
  const [sel, setSel] = useState(null) // { key, time }
  if (!run?.windows?.length) return null
  const select = (key) => (time, iso) => {
    setSel(time === null ? null : { key, time })
    if (time !== null) onPickTime?.(iso)
  }
  return (
    <div className="panel">
      <h3>窗面覆盖统计（按 window_id 分组）</h3>
      <div className="muted small">
        一个点晒到 ≠ 整窗晒到：覆盖率为该窗现有离散测点中晒到的比例，
        是示例统计（非面积加权），夜间不计入分母。
      </div>
      {run.windows.map((w) => {
        const key = `${w.window_id}|${w.point_ids.join(',')}`
        const s = w.summary
        return (
          <div key={key} className="win">
            <h4>窗面 {w.window_id || '（未命名）'} · {s.point_count} 个测点</h4>
            <div className="muted small">{s.point_names.join('、')}</div>
            <table className="summary">
              <tbody>
                <tr><td>白天平均覆盖率</td>
                  <td><b>{(s.average_coverage * 100).toFixed(1)}%</b>
                    <span className="muted small">（{s.daylight_samples} 个白天样本）</span></td></tr>
                <tr><td>完整覆盖合计</td><td>{fmtMin(s.full_coverage_minutes)}</td></tr>
                <tr><td>最长连续完整覆盖</td>
                  <td><b>{fmtMin(s.longest_full_coverage_minutes)}</b></td></tr>
              </tbody>
            </table>
            {s.full_coverage_intervals.length > 0 && (
              <div className="intervals">
                {s.full_coverage_intervals.map((iv, i) => (
                  <div key={i} className="interval sunlit">
                    {fmtTime(iv.start)}–{fmtTime(iv.end)} 全覆盖
                  </div>
                ))}
              </div>
            )}
            <WindowTimeline w={w}
              sel={sel?.key === key ? sel.time : null}
              onSelect={select(key)} />
            <div className="muted small">{s.criterion}</div>
          </div>
        )
      })}
    </div>
  )
}
