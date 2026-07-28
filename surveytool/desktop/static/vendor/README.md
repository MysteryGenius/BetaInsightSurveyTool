# Vendored assets

`plotly.min.js` — plotly.js-basic v2.35.2, downloaded from https://cdn.plot.ly/plotly-basic-2.35.2.min.js
and committed here so the packaged desktop app has no runtime network dependency and no npm/build step.
The "basic" bundle covers bar traces, which is all this app's charts use. To upgrade, download a newer
`plotly-basic-<version>.min.js` and replace this file.
