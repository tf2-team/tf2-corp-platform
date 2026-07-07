const plugin = require("tailwindcss/plugin")

module.exports = plugin.withOptions(() => {
  return function ({ addComponents }) {
  addComponents({
    ".alert": {
      "display": "flex",
      "align-items": "center",
      "gap": "0.75rem",
      "border-radius": "var(--radius-box, 0.5rem)",
      "padding": "0.75rem 1rem",
      "background-color": "var(--color-base-200)",
      "color": "var(--color-base-content)"
    },
    ".alert-info": {
      "background-color": "var(--color-info)",
      "color": "var(--color-info-content)"
    },
    ".alert-error": {
      "background-color": "var(--color-error)",
      "color": "var(--color-error-content)"
    },
    ".btn": {
      "display": "inline-flex",
      "min-height": "2.5rem",
      "align-items": "center",
      "justify-content": "center",
      "gap": "0.5rem",
      "border-radius": "var(--radius-field, 0.25rem)",
      "border": "var(--border, 1px) solid transparent",
      "padding": "0.5rem 1rem",
      "font-weight": "600",
      "line-height": "1",
      "background-color": "var(--color-base-200)",
      "color": "var(--color-base-content)"
    },
    ".btn-primary": {
      "background-color": "var(--color-primary)",
      "color": "var(--color-primary-content)"
    },
    ".btn-soft": {
      "background-color": "color-mix(in oklab, var(--color-primary) 14%, transparent)",
      "color": "var(--color-primary)"
    },
    ".card": {
      "border-radius": "var(--radius-box, 0.5rem)",
      "background-color": "var(--color-base-100)",
      "color": "var(--color-base-content)"
    },
    ".input, .select, .textarea": {
      "width": "100%",
      "border-radius": "var(--radius-field, 0.25rem)",
      "border": "var(--border, 1px) solid var(--color-base-300)",
      "background-color": "var(--color-base-100)",
      "color": "var(--color-base-content)"
    },
    ".input, .select": {
      "min-height": "2.5rem",
      "padding": "0 0.75rem"
    },
    ".textarea": {
      "min-height": "6rem",
      "padding": "0.75rem"
    },
    ".input-error, .select-error, .textarea-error": {
      "border-color": "var(--color-error)"
    },
    ".navbar": {
      "display": "flex",
      "min-height": "4rem",
      "align-items": "center"
    },
    ".table": {
      "width": "100%",
      "border-collapse": "collapse"
    },
    ".table th, .table td": {
      "padding": "0.75rem",
      "text-align": "left",
      "border-bottom": "1px solid var(--color-base-200)"
    },
    ".table-zebra tbody tr:nth-child(even)": {
      "background-color": "var(--color-base-200)"
    }
    })
  }
})
