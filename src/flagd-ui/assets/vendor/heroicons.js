const fs = require("fs")
const path = require("path")

const iconSets = [
  ["", "24/outline"],
  ["-solid", "24/solid"],
  ["-mini", "20/solid"],
  ["-micro", "16/solid"]
]

function readIcons() {
  const icons = {}
  const optimizedDir = path.join(__dirname, "../../deps/heroicons/optimized")

  for (const [suffix, subdir] of iconSets) {
    const iconDir = path.join(optimizedDir, subdir)

    if (!fs.existsSync(iconDir)) {
      continue
    }

    for (const file of fs.readdirSync(iconDir)) {
      if (!file.endsWith(".svg")) {
        continue
      }

      const name = file.replace(/\.svg$/, "") + suffix
      const svg = fs
        .readFileSync(path.join(iconDir, file), "utf8")
        .replace(/\r?\n|\r/g, "")
      icons[name] = encodeURIComponent(svg)
    }
  }

  return icons
}

module.exports = function ({ matchComponents }) {
  matchComponents(
    {
      hero: (svg) => ({
        "--hero": `url("data:image/svg+xml;utf8,${svg}")`,
        "-webkit-mask": "var(--hero)",
        "mask": "var(--hero)",
        "-webkit-mask-repeat": "no-repeat",
        "mask-repeat": "no-repeat",
        "-webkit-mask-size": "100% 100%",
        "mask-size": "100% 100%",
        "background-color": "currentColor",
        "display": "inline-block",
        "vertical-align": "middle"
      })
    },
    { values: readIcons() }
  )
}
