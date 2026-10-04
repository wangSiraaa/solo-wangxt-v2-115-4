import React from 'react'
import { fmtMin, fmtTime } from '../util.js'
import WindowCoverage from './WindowCoverage.jsx'

function PointResult({ run, result, onHoverInterval, onTrace }) {
  const s = result.summary
  return (
    <div className="point-result">
      <h4>测点 #{result.point_id} · 单点结果</h4>
      <table className="summary">
        <tbody>
          <tr><td>白天时长</td><td>{fmtMin(s.daylight_minutes)}</td></tr>
          <tr><td>连续口径·累计日照</td><td><b>{fmtMin(s.sunlit_minutes)}</b></td></tr>
          <tr><td>连续口径·最长连续日照</td><td><b>{fmtMin(s.longest_continuous_sunlit_minutes)}</b></td></tr>
        </tbody>
      </table>
      <div className="muted small">{s.criterion}</div>

      <div className="muted small">连续遮挡/日照时段（步长 {run.step_minutes} min）</div>
      <div className="intervals">
        {result.continuous_intervals
          .filter((iv) => iv.status !== 'night')
          .map((iv, i) => (
            <div key={i}
              className={`interval ${iv.status}`}
              onMouseEnter={() => onHoverInterval?.(iv)}
              onMouseLeave={() => onHoverInterval?.(null)}>
              {fmtTime(iv.start)}–{fmtTime(iv.end)}
              {iv.status === 'shaded' ? ` 遮挡:${iv.occluder}` : ' 日照'}
            </div>
          ))}
      </div>

      <div className="muted small">逐时采样（仅整点快览，<u>不可</u>累加为日照时长）</div>
      <div className="hourly">
        {result.hourly_samples.map((h, i) => (
          <span key={i} className={`cell ${h.status}`}
            title={`${fmtTime(h.time)} ${h.status}${h.occluder ? ' ' + h.occluder : ''}`}>
            {fmtTime(h.time).slice(0, 2)}
          </span>
        ))}
      </div>
      <button onClick={() => onTrace?.(result.point_id)}>追查该点全部遮挡物</button>
    </div>
  )
}

/** 结果面板：窗面测点覆盖（教学：一个点晒到≠整窗晒到）在上，
    原单点结果（逐时快览 / 连续时段）在下，两者均保留。 */
export default function ResultsPanel({ run, result, payload, activeTime,
  onHoverInterval, onTrace, onPickTime, onSelectPoint }) {
  if (!run) {
    return <div className="panel muted">选择测点后显示结果。运行分析后点击三维视图中的测点球。</div>
  }
  return (
    <div className="panel">
      <WindowCoverage run={run} payload={payload} activeTime={activeTime}
        onPickTime={onPickTime} onSelectPoint={onSelectPoint} />
      <hr />
      {result
        ? <PointResult run={run} result={result}
            onHoverInterval={onHoverInterval} onTrace={onTrace} />
        : <div className="muted small">点击三维视图或窗面测点列表中的测点，查看该点单点结果与遮挡追查。</div>}
    </div>
  )
}
