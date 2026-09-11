import { useEffect, useRef, useState } from 'react'

type MotionPoint = { x: number; y: number; born: number }
type GridSpec = { originX: number; originY: number; gapX: number; gapY: number; radius: number }
type Highlight = { x: number; y: number; opacity: number; radius: number }
type Rect = { x: number; y: number; width: number; height: number }

type CanvasEffectsProps = {
  containerRef: React.RefObject<HTMLElement | null>
  selectedIds: string[]
  enabled: boolean
  intensity: number
  accent: string
}

/** Map the V14 0..500 scale to a bounded contrast coefficient. */
export function motionCoefficient(scale: number): number {
  const value = Number.isFinite(Number(scale)) ? Math.max(0, Math.min(500, Number(scale))) : 30
  if (value <= 30) return value / 30
  if (value <= 100) return 1 + ((value - 30) * 2) / 70
  return (3 * value) / 100
}

function numericAttribute(element: Element, name: string, fallback = 0): number {
  const value = Number(element.getAttribute(name))
  return Number.isFinite(value) ? value : fallback
}

function translateAttribute(value: string | null, fallbackX: number, fallbackY: number): { x: number; y: number } {
  const match = value?.match(/translate\(\s*([-+\d.e]+)(?:[ ,]+([-+\d.e]+))?\s*\)/i)
  if (!match) return { x: fallbackX, y: fallbackY }
  const x = Number(match[1])
  const y = Number(match[2] ?? 0)
  return { x: Number.isFinite(x) ? x : fallbackX, y: Number.isFinite(y) ? y : fallbackY }
}

/**
 * Read the rendered XYFlow dot pattern instead of reimplementing its viewport
 * math. The overlay and Background then share the exact same CSS-pixel grid
 * under pan, zoom, resize, nested blackboxes, and high-DPI displays.
 */
function readGridSpec(container: HTMLElement): GridSpec | null {
  const pattern = container.querySelector<SVGPatternElement>('.react-flow__background pattern')
  const dot = pattern?.querySelector<SVGCircleElement>('circle')
  if (!pattern || !dot) return null
  const gapX = numericAttribute(pattern, 'width')
  const gapY = numericAttribute(pattern, 'height')
  if (gapX <= 0 || gapY <= 0) return null
  const patternX = numericAttribute(pattern, 'x')
  const patternY = numericAttribute(pattern, 'y')
  const translate = translateAttribute(pattern.getAttribute('patternTransform'), -gapX / 2, -gapY / 2)
  const cx = numericAttribute(dot, 'cx')
  const cy = numericAttribute(dot, 'cy')
  const radius = numericAttribute(dot, 'r', 0.65)
  if (radius <= 0) return null
  return { originX: patternX + translate.x + cx, originY: patternY + translate.y + cy, gapX, gapY, radius }
}

function nodeRectCache(container: HTMLElement): Map<string, Rect> {
  const frame = container.getBoundingClientRect()
  const result = new Map<string, Rect>()
  for (const node of Array.from(container.querySelectorAll<HTMLElement>('.react-flow__node'))) {
    const id = node.dataset.id
    const rect = node.getBoundingClientRect()
    const style = window.getComputedStyle(node)
    if (!id || rect.width <= 0 || rect.height <= 0 || style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') continue
    result.set(id, { x: rect.left - frame.left, y: rect.top - frame.top, width: rect.width, height: rect.height })
  }
  return result
}

function gridKey(x: number, y: number): string {
  return `${Math.round(x * 100) / 100}:${Math.round(y * 100) / 100}`
}

export function CanvasEffects({ containerRef, selectedIds, enabled, intensity, accent }: CanvasEffectsProps) {
  const [highlights, setHighlights] = useState<Highlight[]>([])
  const selectedRef = useRef(selectedIds)
  const selectionBornRef = useRef<Record<string, number>>({})
  selectedRef.current = selectedIds
  const tint = /^#[0-9a-f]{6}$/i.test(accent.trim()) ? accent.trim() : '#987a5d'
  const motionIntensity = Number.isFinite(Number(intensity)) ? Math.max(0, Math.min(500, Number(intensity))) : 30

  useEffect(() => {
    const container = containerRef.current
    if (!container) return
    if (motionIntensity <= 0 || !enabled) {
      setHighlights([])
      return
    }
    const frameElement: HTMLElement = container
    let frameId = 0
    let stopped = false
    let lastFrame = performance.now()
    const pointerTrail: MotionPoint[] = []
    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)')
    const intensityRatio = motionCoefficient(motionIntensity)
    const selectionDuration = 1150
    const selectionWaveDuration = 950
    const selectionPadding = 54
    const selectionWaveWidth = 18
    const trailLifetime = 760
    const trailLimit = 24
    const pointerSpread = 3
    const pointerRadius = 92
    const contrastOpacity = (baseOpacity: number) => {
      const bounded = Math.max(0, Math.min(1, baseOpacity))
      return 1 - Math.pow(1 - bounded, intensityRatio)
    }
    const pointerOpacity = contrastOpacity(0.16)
    const selectionNow = performance.now()
    const previousBorn = selectionBornRef.current
    selectionBornRef.current = Object.fromEntries(selectedIds.map((id) => [id, previousBorn[id] || selectionNow]))

    const selectionIsActive = (now: number) => selectedRef.current.some((id) => now - (selectionBornRef.current[id] || now) < selectionDuration)

    const schedule = (force = false) => {
      if (stopped || frameId || !enabled || document.hidden) return
      if (reducedMotion.matches) {
        stop()
        return
      }
      if (!force && pointerTrail.length === 0 && !selectionIsActive(performance.now())) return
      frameId = window.requestAnimationFrame(draw)
    }

    const onPointerMove = (event: PointerEvent) => {
      if (reducedMotion.matches || !enabled || document.hidden) return
      const target = event.target
      if (target instanceof Element && target.closest('.react-flow__node, .react-flow__controls, .react-flow__minimap')) return
      const rect = container.getBoundingClientRect()
      pointerTrail.push({ x: event.clientX - rect.left, y: event.clientY - rect.top, born: performance.now() })
      if (pointerTrail.length > trailLimit) pointerTrail.splice(0, pointerTrail.length - trailLimit)
      schedule()
    }

    function draw(now: number) {
      frameId = 0
      if (stopped) return
      if (!enabled || document.hidden) {
        stop()
        return
      }
      // Some embedded WebViews update MediaQueryList.matches without
      // dispatching the change event.  Clear the already-painted frame when
      // the next bounded RAF observes that reduced motion is active.
      if (reducedMotion.matches) {
        stop()
        return
      }
      const elapsed = Math.min(80, now - lastFrame)
      lastFrame = now
      const grid = readGridSpec(frameElement)
      if (!grid) {
        schedule()
        return
      }
      const frame = frameElement.getBoundingClientRect()
      // Read every visible node rectangle once per frame. Highlights are then
      // rejected against this cache so no dot can be painted over card content.
      const nodeRects = nodeRectCache(frameElement)
      const visibleNodeRects = Array.from(nodeRects.values())
      const points = new Map<string, Highlight>()
      const add = (x: number, y: number, opacity: number) => {
        if (x < -grid.gapX || y < -grid.gapY || x > frame.width + grid.gapX || y > frame.height + grid.gapY || opacity <= 0) return
        if (visibleNodeRects.some((rect) => x >= rect.x && x <= rect.x + rect.width && y >= rect.y && y <= rect.y + rect.height)) return
        const key = gridKey(x, y)
        const previous = points.get(key)
        if (!previous || opacity > previous.opacity) points.set(key, { x, y, opacity: Math.min(1, Math.max(0, opacity)), radius: grid.radius })
      }
      const gridPoint = (column: number, row: number) => ({ x: grid.originX + column * grid.gapX, y: grid.originY + row * grid.gapY })

      // Selection diffusion is a bounded set of actual background grid cells
      // around each selected DOM card. No free-floating particles are emitted.
      const selected = new Set(selectedRef.current)
      for (const [nodeId, rect] of nodeRects) {
        if (!selected.has(nodeId)) continue
        const padding = selectionPadding
        const age = Math.max(0, now - (selectionBornRef.current[nodeId] || selectionNow))
        if (age >= selectionDuration) continue
        const waveRadius = Math.min(padding, (age / selectionWaveDuration) * padding)
        const fade = Math.max(0, 1 - age / selectionDuration)
        const minColumn = Math.floor((rect.x - padding - grid.originX) / grid.gapX)
        const maxColumn = Math.ceil((rect.x + rect.width + padding - grid.originX) / grid.gapX)
        const minRow = Math.floor((rect.y - padding - grid.originY) / grid.gapY)
        const maxRow = Math.ceil((rect.y + rect.height + padding - grid.originY) / grid.gapY)
        for (let column = minColumn; column <= maxColumn; column += 1) {
          for (let row = minRow; row <= maxRow; row += 1) {
            const point = gridPoint(column, row)
            const distanceX = Math.max(rect.x - point.x, 0, point.x - (rect.x + rect.width))
            const distanceY = Math.max(rect.y - point.y, 0, point.y - (rect.y + rect.height))
            const distance = Math.hypot(distanceX, distanceY)
            if (distance > padding) continue
            const wave = Math.max(0, 1 - Math.abs(distance - waveRadius) / selectionWaveWidth) * fade
            add(point.x, point.y, contrastOpacity(wave * 0.5))
            if (points.size >= 520) break
          }
          if (points.size >= 520) break
        }
      }

      // The pointer trail also snaps to nearby cells, so every highlighted
      // circle remains on the same grid as the real XYFlow background.
      for (const trail of pointerTrail) {
        const age = now - trail.born
        const decay = Math.max(0, 1 - age / trailLifetime)
        if (decay <= 0) continue
        const centerColumn = Math.round((trail.x - grid.originX) / grid.gapX)
        const centerRow = Math.round((trail.y - grid.originY) / grid.gapY)
        for (let column = centerColumn - pointerSpread; column <= centerColumn + pointerSpread; column += 1) {
          for (let row = centerRow - pointerSpread; row <= centerRow + pointerSpread; row += 1) {
            const point = gridPoint(column, row)
            const distance = Math.hypot(point.x - trail.x, point.y - trail.y)
            if (distance > pointerRadius) continue
            add(point.x, point.y, decay * Math.max(0, pointerOpacity * (1 - distance / pointerRadius)))
          }
        }
      }
      for (let index = pointerTrail.length - 1; index >= 0; index -= 1) {
        if (now - pointerTrail[index].born > trailLifetime) pointerTrail.splice(index, 1)
      }
      const next = Array.from(points.values())
      setHighlights(next)
      const selectionActive = selectionIsActive(now)
      if (pointerTrail.length > 0 || selectionActive) {
        // Force the boundary frame: schedule() may otherwise observe a later
        // performance.now() and reject the final frame before it clears.
        if (elapsed >= 0) schedule(true)
      } else {
        // The animation naturally expired. Clear the last SVG frame explicitly
        // and leave RAF idle until a new pointer/selection event arrives.
        setHighlights([])
      }
    }

    const stop = () => {
      if (frameId) window.cancelAnimationFrame(frameId)
      frameId = 0
      setHighlights((current) => current.length === 0 ? current : [])
    }
    const onVisibility = () => { if (document.hidden) stop(); else schedule() }
    const onMotionPreference = () => { if (reducedMotion.matches) stop(); else schedule() }
    const resizeObserver = new ResizeObserver(() => schedule())

    resizeObserver.observe(container)
    container.addEventListener('pointermove', onPointerMove, { passive: true })
    document.addEventListener('visibilitychange', onVisibility)
    reducedMotion.addEventListener?.('change', onMotionPreference)
    schedule()
    return () => {
      stopped = true
      stop()
      resizeObserver.disconnect()
      container.removeEventListener('pointermove', onPointerMove)
      document.removeEventListener('visibilitychange', onVisibility)
      reducedMotion.removeEventListener?.('change', onMotionPreference)
      pointerTrail.length = 0
    }
  }, [accent, containerRef, enabled, motionIntensity, selectedIds.join('|')])

  return <svg className="motion-canvas" data-testid="motion-canvas" data-motion-scale={motionIntensity} data-motion-coefficient={motionCoefficient(motionIntensity)} aria-hidden="true" role="presentation"><g fill={tint}>{highlights.map((point) => <circle key={gridKey(point.x, point.y)} className="motion-grid-arc" data-grid-highlight="true" cx={point.x} cy={point.y} r={point.radius} opacity={point.opacity} />)}</g></svg>
}
