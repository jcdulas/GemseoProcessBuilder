// A Web Worker computing layouts with ELK, so that the page never freezes.
//
// elkjs's worker script answers the messages of the ELK API of the page: the
// page creates it with ``new ELK({workerFactory})`` (see
// views/canvas/auto_layout.js). The page starts this worker from a Blob that
// sets ``self.GPB_BASE``, the address of the application, since Chromium does
// not start workers from scripts of the gpb:// scheme.
importScripts(`${self.GPB_BASE}vendor/elk-worker.min.js`);
