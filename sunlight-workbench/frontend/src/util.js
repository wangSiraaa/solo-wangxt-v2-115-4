/* 坐标映射：模型 ENU(x=东, y=北, z=上) → three.js(x, y=上, z)。
   (x,y,z)_model → (x, z, -y)_three 是行列式为 +1 的旋转，手性不变。 */
export const toThree = ([x, y, z]) => [x, z, -y]

export const STATUS_COLOR = {
  sunlit: '#f6c453',
  shaded: '#4a6fa5',
  night: '#666',
}

export function fmtMin(m) {
  const h = Math.floor(m / 60)
  const r = m % 60
  return h ? `${h}h${r ? `${r}m` : ''}` : `${r}m`
}

export function fmtTime(iso) {
  return iso.slice(11, 16)
}

/** 窗面覆盖率配色：0=蓝（遮）→ 0.5 过渡 → 1=金（全晒到）。
    只表示"现有离散测点中晒到的比例"，不是窗面真实受照面积。 */
export function coverageColor(ratio) {
  const r = Math.max(0, Math.min(1, ratio))
  // 蓝 (74,111,165) → 金 (246,196,83)
  const c = [74 + (246 - 74) * r, 111 + (196 - 111) * r, 165 + (83 - 165) * r]
    .map((v) => Math.round(v))
  return `rgb(${c[0]},${c[1]},${c[2]})`
}

export function pct(x) {
  return `${Math.round(x * 100)}%`
}
