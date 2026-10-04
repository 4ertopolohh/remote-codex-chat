import { useEffect, useRef } from 'react'

export function useViewportDock() {
  const dock = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const viewport = window.visualViewport
    if (!viewport) return
    let previousHeight = viewport.height
    const syncHeight = (revealComposer: boolean) => {
      document.documentElement.style.setProperty('--app-height', `${viewport.height}px`)
      const element = dock.current
      if (revealComposer && viewport.height < 480 && element) element.scrollTop = element.scrollHeight
    }
    const onResize = () => {
      const shrunk = previousHeight - viewport.height > 30
      previousHeight = viewport.height
      const active = document.activeElement
      const composerFocused = dock.current?.querySelector('textarea') === active
      syncHeight(shrunk && composerFocused)
      if (shrunk && !composerFocused && active instanceof HTMLElement && dock.current?.contains(active)) {
        active.scrollIntoView?.({ block: 'nearest' })
      }
    }
    const onScroll = () => syncHeight(false)
    syncHeight(true)
    viewport.addEventListener('resize', onResize)
    viewport.addEventListener('scroll', onScroll)
    return () => {
      viewport.removeEventListener('resize', onResize)
      viewport.removeEventListener('scroll', onScroll)
      document.documentElement.style.removeProperty('--app-height')
    }
  }, [dock])
  return dock
}
