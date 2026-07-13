import * as React from "react"

/* Tracks a min-width media query. Used where layout structure (not just CSS)
   depends on the breakpoint — e.g. whether clicking a table row selects into
   an inspector rail or navigates directly. */
export function useMinWidth(px: number) {
  const query = `(min-width: ${px}px)`
  const [matches, setMatches] = React.useState(() => window.matchMedia(query).matches)

  React.useEffect(() => {
    const mql = window.matchMedia(query)
    const onChange = () => setMatches(mql.matches)
    mql.addEventListener("change", onChange)
    setMatches(mql.matches)
    return () => mql.removeEventListener("change", onChange)
  }, [query])

  return matches
}
