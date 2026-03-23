if ('serviceWorker' in navigator) navigator.serviceWorker.register('sw.js');

/** Query the active SW for its cache version. Returns { cacheName } or null. */
function getSWVersion() {
  return new Promise(function (resolve) {
    if (!navigator.serviceWorker || !navigator.serviceWorker.controller) {
      resolve(null);
      return;
    }
    var ch = new MessageChannel();
    ch.port1.onmessage = function (e) { resolve(e.data); };
    navigator.serviceWorker.controller.postMessage({ type: 'GET_VERSION' }, [ch.port2]);
    setTimeout(function () { resolve(null); }, 1000);
  });
}
