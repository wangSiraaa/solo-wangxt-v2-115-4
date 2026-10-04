import React, { useEffect, useMemo, useState } from 'react'
import { api } from './api.js'
import SceneViewer from './components/SceneViewer.jsx'
import ResultsPanel from './components/ResultsPanel.jsx'

const DATES = ['2026-01-15', '2026-03-20', '2026-07-15'] // 跨冬夏算例日期

export default function App() {
  const [scenes, setScenes] = useState([])
  const [sceneId, setSceneId] = useState(null)
  const [payload, setPayload] = useState(null)   // 场景或快照内容
  const [date, setDate] = useState(DATES[0])
  const [sunpath, setSunpath] = useState(null)
  const [timeIdx, setTimeIdx] = useState(30)
  const [run, setRun] = useState(null)
  const [selectedPointId, setSelectedPointId] = useState(null)
  const [highlightOccluder, setHighlightOccluder] = useState(null)
  const [trace, setTrace] = useState(null)
  const [error, setError] = useState(null)
  const [pickedTime, setPickedTime] = useState(null)  // 窗面时间轴点选时刻

  useEffect(() => { api.scenes().then(setScenes).catch((e) => setError(String(e))) }, [])

  useEffect(() => {
    if (!sceneId) return
    setRun(null); setSelectedPointId(null); setTrace(null); setPickedTime(null)
    api.scene(sceneId).then(setPayload)
    api.sunpath(sceneId, date).then(setSunpath)
  }, [sceneId, date])

  const doSeed = async () => { await api.seed(); setScenes(await api.scenes()) }

  const doRun = async () => {
    setError(null)
    const r = await api.run(sceneId, date, 5)
    const full = await api.runResult(r.run_id)
    setRun(full)
    setPickedTime(null)
    // 结果关联快照：渲染切换到快照内容，保证结果-场景一致可追溯
    const snap = await api.snapshot(full.snapshot_id)
    setPayload(snap.payload)
  }

  // 窗面时间轴点选时刻 → 同步三维时刻滑块（15min 网格取最近），
  // 并选中午夜前/后最近的点，避免夜→昼跳跃问题
  const pickTime = (time) => {
    setPickedTime(time)
    if (sunpath?.points?.length) {
      let bi = 0
      sunpath.points.forEach((p, i) => {
        if (Math.abs(p.time.localeCompare(time)) <
            Math.abs(sunpath.points[bi].time.localeCompare(time))) bi = i
      })
      setTimeIdx(bi)
    }
  }

  // 当前生效时刻：窗面时间轴点选优先，否则用滑块时刻
  const activeTime = pickedTime ?? sunpath?.points?.[timeIdx]?.time ?? null

  // 当前时刻各测点状态（取最近细样本）
  const pointStatus = useMemo(() => {
    if (!run || !activeTime) return null
    const out = {}
    for (const res of run.results) {
      let best = null
      for (const s of res.fine_samples) {
        if (!best || Math.abs(s.time.localeCompare(activeTime)) <
          Math.abs(best.time.localeCompare(activeTime))) best = s
      }
      out[res.point_id] = best
    }
    return out
  }, [run, activeTime])

  const selectedResult = run?.results.find((r) => r.point_id === selectedPointId)

  const doTrace = async (pointId) => {
    setTrace(await api.trace(run.run_id, pointId))
  }

  return (
    <div className="layout">
      <header>
        <b>日照分析工作台</b>
        <span className="badge">合成场景 · 示例评价口径 · 非规划合规结论</span>
      </header>
      <aside>
        <label>场景（坐标基准统一挂在场景上）</label>
        <select value={sceneId ?? ''} onChange={(e) => setSceneId(+e.target.value)}>
          <option value="" disabled>选择场景</option>
          {scenes.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
        </select>
        {!scenes.length && <button onClick={doSeed}>初始化合成场景</button>}
        {payload && (
          <div className="meta">
            <div>经纬度 {payload.scene.latitude}, {payload.scene.longitude}</div>
            <div>时区 {payload.scene.timezone}</div>
            <div>模型北偏角 {payload.scene.north_offset_deg}°</div>
            <div className="warn">未建模遮挡：{payload.scene.unmodeled_occluders}</div>
          </div>
        )}
        <label>日期（跨冬夏算例）</label>
        <select value={date} onChange={(e) => setDate(e.target.value)}>
          {DATES.map((d) => <option key={d}>{d}</option>)}
        </select>
        <button disabled={!sceneId} onClick={doRun}>运行当日分析（5min 步长）</button>
        {run && <div className="muted small">run #{run.run_id} · 快照 #{run.snapshot_id}</div>}
        {error && <div className="error">{error}</div>}
        {sunpath && (
          <>
            <label>时刻 {sunpath.points[timeIdx]?.time.slice(11, 16)}
              {pickedTime && <span className="muted">（窗面轴点选：{pickedTime.slice(11, 16)}，三维显示取最近）</span>}
            </label>
            <input type="range" min={0} max={sunpath.points.length - 1}
              value={timeIdx}
              onChange={(e) => { setTimeIdx(+e.target.value); setPickedTime(null) }} />
          </>
        )}
        {trace && (
          <div className="trace">
            <h4>遮挡物追查（测点 #{trace.point_id}）</h4>
            <div>遮挡物：{trace.occluders.join('、') || '无'}</div>
            <div className="muted small">{trace.note}</div>
            <button onClick={() => setTrace(null)}>关闭</button>
          </div>
        )}
      </aside>
      <main>
        <SceneViewer
          payload={payload} sunpath={sunpath} timeIdx={timeIdx}
          pointStatus={pointStatus} selectedPointId={selectedPointId}
          highlightOccluder={highlightOccluder}
          onSelectPoint={setSelectedPointId}
          onSelectBuilding={setHighlightOccluder} />
      </main>
      <aside className="right">
        <ResultsPanel
          run={run} result={selectedResult} payload={payload}
          activeTime={activeTime}
          onHoverInterval={(iv) => setHighlightOccluder(iv?.occluder ?? null)}
          onTrace={doTrace}
          onPickTime={pickTime}
          onSelectPoint={setSelectedPointId} />
      </aside>
    </div>
  )
}
