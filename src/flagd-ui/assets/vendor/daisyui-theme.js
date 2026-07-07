const plugin = require("tailwindcss/plugin")

module.exports = plugin.withOptions(() => {
  return function ({ addBase }) {
  addBase({
    ":root": {
      "--color-base-100": "oklch(98% 0 0)",
      "--color-base-200": "oklch(96% 0.001 286.375)",
      "--color-base-300": "oklch(92% 0.004 286.32)",
      "--color-base-content": "oklch(21% 0.006 285.885)",
      "--color-primary": "oklch(70% 0.213 47.604)",
      "--color-primary-content": "oklch(98% 0.016 73.684)",
      "--color-secondary": "oklch(55% 0.027 264.364)",
      "--color-secondary-content": "oklch(98% 0.002 247.839)",
      "--color-accent": "oklch(0% 0 0)",
      "--color-accent-content": "oklch(100% 0 0)",
      "--color-neutral": "oklch(44% 0.017 285.786)",
      "--color-neutral-content": "oklch(98% 0 0)",
      "--color-info": "oklch(62% 0.214 259.815)",
      "--color-info-content": "oklch(97% 0.014 254.604)",
      "--color-success": "oklch(70% 0.14 182.503)",
      "--color-success-content": "oklch(98% 0.014 180.72)",
      "--color-warning": "oklch(66% 0.179 58.318)",
      "--color-warning-content": "oklch(98% 0.022 95.277)",
      "--color-error": "oklch(65% 0.241 354.308)",
      "--color-error-content": "oklch(97% 0.014 343.198)",
      "--radius-selector": "0.25rem",
      "--radius-field": "0.25rem",
      "--radius-box": "0.5rem",
      "--size-selector": "0.21875rem",
      "--size-field": "0.21875rem",
      "--border": "1.5px",
      "--depth": "1",
      "--noise": "0"
    }
    })
  }
})
