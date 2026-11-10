# Third-party notices

Vox is MIT licensed. It ships and depends on the following third-party work.

## VoxLock (voice model and inference code)

- Project: https://github.com/arbazsiddiqui/voxlock
- Pinned revision: `2413b292bc2c337bfc19a9802aaf3e011e68e9c4`
- License: Apache License 2.0
- Copyright 2026 Arbaz Siddiqui

The VoxLock model weights are fine-tuned from the REAL-TSE
`tfmap_context_causal_100` baseline checkpoint, trained by Ke Zhang and
released through the REAL-TSE WeSep project
(https://github.com/REAL-TSE/wesep-real-tse). Ke Zhang has confirmed that the
inference code he wrote and the parameters he trained are available under
Apache-2.0. This notice is attribution only and does not imply endorsement by
the REAL-TSE organizers.

`wesep/` is the WeSep model code from the REAL-TSE challenge baseline
(https://github.com/REAL-TSE/wesep-real-tse), Apache-2.0 per its source
headers, used unchanged.

`demo/ort/` is ONNX Runtime Web 1.20.1
(https://github.com/microsoft/onnxruntime), MIT License, Copyright Microsoft.

Demo recordings: Krisp Voice Isolation Benchmark (CC BY-NC 4.0, Krisp) and the
AMI Meeting Corpus (CC BY 4.0). Second talker in the demo: LibriSpeech
test-clean (CC BY 4.0), room-simulated.

The full Apache-2.0 text is installed with the model files as
`models/LICENSE`, and the original notice as `models/NOTICE`.

## Runtime libraries

| Component | License |
| --- | --- |
| ONNX Runtime, DirectML provider | MIT |
| PySide6 / Qt 6 | LGPL-3.0 (dynamic linking) |
| NumPy | BSD-3-Clause |
| sounddevice, PortAudio | MIT |
| soundfile | BSD-3-Clause |
| libsndfile (bundled by soundfile) | LGPL-2.1 |
| python-soxr, libsoxr | LGPL-2.1+ |
| PyInstaller bootloader | GPL-2.0 with a linking exception for bundled apps |

Qt and libsndfile are used as separate shared libraries in the installed
folder, so they can be replaced with compatible versions. Their source is
available from the projects above and from the Qt and libsndfile
distributions.

## VB-CABLE

VB-CABLE is a separate product by VB-Audio Software. It is not bundled with
Vox and is not covered by this license. Vox only routes audio to a device that
VB-CABLE creates. Install it from https://vb-audio.com/Cable/ and follow its
own terms.
