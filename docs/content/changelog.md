---
hide:
  - navigation
---

# Changelog

The notable changes to ManimGX, release by release. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and ManimGX follows
[Semantic Versioning](https://semver.org/).

<!--
### Added
### Changed
### Fixed
### Removed
-->

## Unreleased

### Added

- Add a local Panini-Animgx Studio for Ollama storyboards, editable animation shots,
  Manim-style equations, graphs, geometry, calculus and vectors, Windows voice-over,
  ambient music, and MP4 previews.
- Add Studio profile settings for OpenAI, Gemini, and compatible planning APIs,
  session API keys, an interactive workflow guide, and animated job feedback.
- Add a one-command Windows Studio launcher that opens the default browser, and
  a separate ndimensions.AI MIT notice for the Studio additions.
- Add Panini branding, editable scene compositions with per-element timelines,
  concurrent appearance and movement, and storyboard-driven music scores to Studio.

### Changed

- Show measured render times in a static benchmark chart.
- Use a Markdown table for the benchmark comparison images.
- Install ManimGX in the Quickstart with one command, `pip install manimgx`, and run `manimgx` directly throughout the docs.
- Move the benchmark to `benchmarks/`, whose README explains its scenes, method and results; the README's numbers link to it.
- Arrange the Rendering and sharing page by command, with settings, tall videos and rendering from Python under Render.

### Fixed

- Preserve unfinished Studio edits across reloads and scene changes, prevent renders
  from using older values, and allow returning from a sketch to the rendered video.
- Improve Studio's secondary text and placeholder contrast, mobile input sizes,
  touch targets, and validation feedback.
- Keep previous export artifacts together on failure, retain recovery files when
  rollback is blocked, and preserve literal text in WebVTT captions.
- Serialize provider validation with job submission and handle stopped queues and
  oversized media ranges without leaving a stuck job or dropping the response.
- Make benchmark platform guards pass type checking on Windows.
- Remove Studio's canned visual presets and sample storyboard library, distinguish
  restored work from the current brief, and detect servers that need restarting.
- Remove Studio's automatic project backups and delete obsolete browser draft
  storage on startup.
- Include OpenAI's JSON instruction in the planning input and distinguish failed
  planning requests from the previous Studio storyboard.
- Preserve model-authored scene counts and durations; require mathematical inputs
  explicitly and begin fresh Studio drafts without an automatically loaded example.
- Ground local planning prompts in their JSON schema and read bounded streamed
  storyboards without waiting for trailing model output.
- Preserve the benchmark comparison images' aspect ratios when PyPI narrows the README table.
- Credit Filament, whose code the 3D lighting is adapted from, in the README and the wheels' third-party notices.

## 0.1.1

### Changed

- Updated package author metadata to Academa Team. The font packages have metadata-only post-releases; their font files are unchanged.

### Fixed

- Fixed GPU validation failures when meshes with materials share a scene with ordinary meshes, overlays, or point sprites, including during fades.

## 0.1.0

First release of ManimGX.
