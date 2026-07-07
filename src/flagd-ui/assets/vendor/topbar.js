let bar
let timer
let currentConfig = {
  barColors: { 0: "#29d" },
  shadowColor: "rgba(0, 0, 0, .3)"
}

function ensureBar() {
  if (bar) {
    return bar
  }

  bar = document.createElement("div")
  bar.style.cssText = [
    "position:fixed",
    "top:0",
    "left:0",
    "height:3px",
    "width:0",
    "z-index:9999",
    `background:${currentConfig.barColors[0] || "#29d"}`,
    `box-shadow:0 0 10px ${currentConfig.shadowColor}`,
    "transition:width 300ms ease-out, opacity 250ms ease-out",
    "opacity:0"
  ].join(";")

  document.body.appendChild(bar)
  return bar
}

function config(options) {
  currentConfig = { ...currentConfig, ...options }
}

function show(delay = 0) {
  clearTimeout(timer)
  timer = setTimeout(() => {
    const element = ensureBar()
    element.style.opacity = "1"
    element.style.width = "75%"
  }, delay)
}

function hide() {
  clearTimeout(timer)
  if (!bar) {
    return
  }

  bar.style.width = "100%"
  setTimeout(() => {
    if (!bar) {
      return
    }

    bar.style.opacity = "0"
    bar.style.width = "0"
  }, 200)
}

export default { config, show, hide }
