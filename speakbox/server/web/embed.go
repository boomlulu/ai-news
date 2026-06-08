// Package web embeds the speakbox front-end assets into the binary so the
// server ships as a single static file. Go forbids ".." in embed paths, so the
// declaration lives alongside the assets.
package web

import "embed"

//go:embed index.html style.css js
var Files embed.FS
