// Phone listings sheet: visible share of the screen at each snap point. Shared by the sheet itself
// and the map (which centers a selected pin in the part of the map the sheet doesn't cover).
export const SNAPS = { peek: 0.2, half: 0.52, full: 0.92 }
export const MIN_PEEK_PX = 96 // the handle + summary line must always fit
