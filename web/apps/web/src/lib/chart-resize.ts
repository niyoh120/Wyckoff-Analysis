import type { IChartApi } from 'lightweight-charts'

/** Keep a lightweight-charts instance width in sync with its container; returns a cleanup fn. */
export function watchChartResize(container: HTMLElement | null, chart: IChartApi): () => void {
  const resize = () => {
    if (container) chart.applyOptions({ width: container.clientWidth })
  }
  window.addEventListener('resize', resize)
  resize()
  return () => window.removeEventListener('resize', resize)
}
