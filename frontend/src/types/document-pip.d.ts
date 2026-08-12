// Ambient declaration for the Document Picture-in-Picture API — not yet in the
// TS DOM libs (see 0049 plan § Slice 3 / feature #131). Optional on `Window` so
// the runtime feature-detect narrows cleanly.

interface DocumentPictureInPictureOptions {
  width?: number
  height?: number
}

interface DocumentPictureInPicture {
  requestWindow(options?: DocumentPictureInPictureOptions): Promise<Window>
  readonly window: Window | null
}

interface Window {
  documentPictureInPicture?: DocumentPictureInPicture
}
