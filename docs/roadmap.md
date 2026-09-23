# Roadmap

## Completed in 0.2.0

- Automatic and explicit content profiles for photos, portraits, objects, documents, and line drawings.
- Multi-scale local-contrast contour extraction and topology cleanup for diagonal corner shortcuts.
- Checksum-verified optional model manager with UI, API, CLI, and Windows workflow.
- A zero-dependency client and end-to-end instructions for processing from another PC.
- Portable startup smoke test and SHA-256 release checksum.

## Next photo-to-vector work

- Benchmark and tune presets against a versioned public image corpus.
- Add foreground-aware detail control and better junction/spur simplification.
- Add cancellation and periodic TTL cleanup while the server remains running.
- Add constraint-aware route optimization beyond greedy nearest neighbour.
- ONNX Runtime and DirectML acceleration.
- SAM 2-assisted subject masks and Qwen3-VL via the optional OpenAI-compatible/Ollama adapter.

## Later, outside the current focus

- Safe, separately packaged Serial/G-code/ROS/vendor robot plugins.
- Tauri desktop client and local project history.

Any real-hardware milestone requires independent safety design and testing. Developed by maggogerka.
