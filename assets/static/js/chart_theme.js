/* Chart.js theme bridge.
 *
 * Points Chart.js's chrome (ticks, gridlines, legend text, tooltips) at the
 * design tokens in style.css, so charts stay legible in light and dark and
 * follow the palette. Loaded by the analytics templates after the Chart.js
 * CDN tag and app.js (for themeToken), before their own chart scripts.
 * Theme switches reload the page, so reading the tokens once here is enough.
 */
(function () {
  if (typeof Chart === 'undefined' || !window.themeToken) return;

  Chart.defaults.color = themeToken('--chart-tick');
  Chart.defaults.borderColor = themeToken('--chart-grid');
  Chart.defaults.plugins.tooltip.backgroundColor = themeToken('--surface');
  Chart.defaults.plugins.tooltip.titleColor = themeToken('--text');
  Chart.defaults.plugins.tooltip.bodyColor = themeToken('--text-muted');
  Chart.defaults.plugins.tooltip.borderColor = themeToken('--border');
  Chart.defaults.plugins.tooltip.borderWidth = 1;

  // rgba() from a hex token + alpha (canvas colors can't use var()).
  function alpha(hex, a) {
    var h = hex.replace('#', '');
    if (h.length === 3) h = h[0] + h[0] + h[1] + h[1] + h[2] + h[2];
    return 'rgba(' + parseInt(h.substring(0, 2), 16) + ',' +
                     parseInt(h.substring(2, 4), 16) + ',' +
                     parseInt(h.substring(4, 6), 16) + ',' + a + ')';
  }

  // The Actual / Planned / Projected category families, resolved per theme.
  window.chartPalette = function () {
    return {
      actual: themeToken('--chart-actual'),
      actualStrong: themeToken('--chart-actual-strong'),
      planned: themeToken('--chart-planned'),
      plannedStrong: themeToken('--chart-planned-strong'),
      projected: themeToken('--chart-projected'),
      projectedStrong: themeToken('--chart-projected-strong'),
      alpha: alpha,
    };
  };
})();
