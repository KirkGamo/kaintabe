import { useEffect, useLayoutEffect, useRef, useState } from 'react'

import { MIN_PEEK_PX, SNAPS } from '../lib/sheet'

/**
 * Phone-only listings panel over a full-screen map. Drag the handle (or tap it) to move
 * between peek / half / full. Only the handle area drags, so the list inside scrolls normally.
 */
export default function BottomSheet({ snap, onSnap, summary, children }) {
  const rootRef = useRef(null)
  const [parentH, setParentH] = useState(0)
  const [dragY, setDragY] = useState(null) // px offset while dragging, null when idle
  const drag = useRef(null)

  useLayoutEffect(() => {
    const parent = rootRef.current?.parentElement
    if (!parent) return
    const measure = () => setParentH(parent.clientHeight)
    measure()
    const ro = new ResizeObserver(measure)
    ro.observe(parent)
    return () => ro.disconnect()
  }, [])

  const sheetH = parentH * SNAPS.full
  const offsetFor = (name) => {
    const visible = name === 'peek' ? Math.max(parentH * SNAPS.peek, MIN_PEEK_PX) : parentH * SNAPS[name]
    return Math.max(0, sheetH - visible)
  }
  const offset = dragY ?? offsetFor(snap)

  // Keep the list scrolled to the top when collapsing, so "peek" always shows the summary
  const listRef = useRef(null)
  useEffect(() => {
    if (snap === 'peek' && listRef.current) listRef.current.scrollTop = 0
  }, [snap])

  function onPointerDown(e) {
    drag.current = { startY: e.clientY, startOffset: offset, t: performance.now(), moved: false }
    e.currentTarget.setPointerCapture(e.pointerId)
  }

  function onPointerMove(e) {
    if (!drag.current) return
    const dy = e.clientY - drag.current.startY
    if (Math.abs(dy) > 4) drag.current.moved = true
    setDragY(Math.min(offsetFor('peek'), Math.max(0, drag.current.startOffset + dy)))
  }

  function onPointerUp(e) {
    const d = drag.current
    drag.current = null
    if (!d) return
    if (!d.moved) {
      // a tap on the handle cycles peek -> half -> full -> peek
      onSnap({ peek: 'half', half: 'full', full: 'peek' }[snap])
      setDragY(null)
      return
    }
    const end = offset
    const velocity = (e.clientY - d.startY) / Math.max(1, performance.now() - d.t) // px/ms, + = down
    let target
    if (velocity > 0.6) target = snap === 'full' ? 'half' : 'peek'
    else if (velocity < -0.6) target = snap === 'peek' ? 'half' : 'full'
    else
      target = Object.keys(SNAPS).reduce((a, b) =>
        Math.abs(offsetFor(a) - end) < Math.abs(offsetFor(b) - end) ? a : b,
      )
    onSnap(target)
    setDragY(null)
  }

  return (
    <div
      ref={rootRef}
      className="absolute inset-x-0 bottom-0 z-500 flex flex-col rounded-t-2xl bg-slate-50 shadow-[0_-4px_20px_rgba(0,0,0,0.15)]"
      style={{
        height: sheetH || '92%',
        transform: `translateY(${offset}px)`,
        transition: dragY === null ? 'transform 220ms cubic-bezier(.2,.8,.2,1)' : 'none',
      }}
    >
      <div
        role="button"
        tabIndex={0}
        aria-label={`Listings panel, ${snap}. Tap to expand or collapse`}
        onKeyDown={(e) =>
          (e.key === 'Enter' || e.key === ' ') && onSnap({ peek: 'half', half: 'full', full: 'peek' }[snap])
        }
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={() => {
          drag.current = null
          setDragY(null)
        }}
        className="shrink-0 cursor-grab touch-none select-none px-4 pt-2 pb-2 min-h-11"
      >
        <div className="mx-auto h-1.5 w-10 rounded-full bg-slate-300" />
        <div className="mt-2 text-sm font-semibold text-slate-700">{summary}</div>
      </div>
      {/* The sheet is always full height and slides down to peek/half, so part of it sits below the
          screen; padding by that hidden amount lets the last cards scroll up into view */}
      <div
        ref={listRef}
        className="flex-1 min-h-0 overflow-y-auto overscroll-contain px-3 space-y-2"
        style={{ paddingBottom: offset + 24 }}
      >
        {children}
      </div>
    </div>
  )
}
