// ARIA device bootstrap.
//
// Max creates the jweb at its default 320x240 when the patcher is loaded from
// disk and ignores the stored box rect, so the panel would come up tiny. A
// javascript object is the one place that reliably resizes the box after the
// patcher exists, so: size the browser to the device area, then (re)load the
// panel URL so the page lays out at the real viewport size.

autowatch = 0;
inlets = 1;
outlets = 0;

var W = 460;
var H = 620;
var URL = "http://127.0.0.1:8765/";

function bang() {
  var w = this.patcher.getnamed("aria-web");
  if (!w) {
    post("ARIA: jweb object not found\n");
    return;
  }
  w.rect = [0, 0, W, H];
  w.message("read", URL);
  post("ARIA: panel " + W + "x" + H + " -> " + URL + "\n");
}
