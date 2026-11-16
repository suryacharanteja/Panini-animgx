<!-- SPDX-FileCopyrightText: 2026 Panini-Animgx contributors -->
<!-- SPDX-FileCopyrightText: 2026 ndimensions.AI -->
<!-- SPDX-License-Identifier: MIT -->

# Panini-Animgx Studio

![Panini-Animgx logo](web/assets/branding/panini-animgx-lockup.png)

A local authoring app for model-assisted storyboards and ManimGX videos. Describe an idea,
generate a storyboard, edit every shot, choose narration and music, and render an MP4.
The frontend and server run on your PC. Ollama and manual authoring work without
a cloud account or API key. OpenAI, Google Gemini, and compatible APIs are optional
planning providers. No frontend build or additional Python dependencies are
required beyond this repository's environment.

## Run

On Windows, with the ManimGX environment already installed, launch the app from
the repository root with one command:

```powershell
.\panini.cmd
```

The launcher opens <http://127.0.0.1:7860> in your default browser. Keep the
terminal running; Ctrl+C stops the server after the current job finishes.
If Windows asks **Terminate batch job (Y/N)?**, enter **Y** to close the launcher.
It uses `uv` and this checkout's `.venv`, without rebuilding the engine or
changing PowerShell's script execution settings. If the browser cannot open,
the terminal prints the URL so you can open it yourself.

The command also accepts server options:

```powershell
.\panini.cmd --port 7861
.\panini.cmd --no-open
```

From another working directory, use the launcher's full path. For this checkout:

```powershell
& "D:\AI\Lab\Panini-animgx\panini.cmd"
```

The existing `./studio/start.ps1` and `just studio` commands also open the
browser. A direct command, usable on other platforms too, is:

```powershell
uv run --frozen --no-sync python -m studio.server --open
```

The launcher requires `uv` on PATH and `.venv` already set up. If the environment
is missing, follow the repository's Developer Guide and run `just sync` first;
`uv sync` sets up the Python environment when `just` is unavailable. Source
installation requires Rust and the Windows C++ build tools. The launcher reports
missing prerequisites and exits so setup can be completed before launching.

Start the Ollama desktop app or `ollama serve` before generating a plan. Studio
lists models already installed on your computer. It does not download a model.
Select an installed model in the dropdown. Small models can return invalid
timelines or miss requested movement; review their drafts and try another
installed model when needed. Inference and rendering run in one queue, and
Ollama unloads the planning model afterwards to free GPU memory.
Allow time for the first model load. You can also add a scene and author its
composition or mathematical inputs yourself when Ollama is unavailable.

Use `--port 7861` for another Studio port or `--ollama-port 11435` for another
local Ollama port. Both services use loopback addresses.

## License

The Panini-Animgx Studio and launcher additions by **ndimensions.AI** are provided
under the [MIT license](../LICENSE-NDIMENSIONS-AI), copyright 2026 ndimensions.AI.
The upstream ManimGX [MIT notice](../LICENSE) and the repository's third-party
notices apply to the underlying engine and bundled components.

## Planning providers and admin settings

Open the profile icon in the top-right corner, then **Admin settings**. Choose
Ollama, OpenAI, Google Gemini, or an OpenAI-compatible API. Set the model ID and,
for a cloud provider, enter its API key. A compatible provider also needs its
base URL. Compatible servers on explicit loopback addresses can plan locally
without a key. **Test connection** checks the provider's model listing without asking
it to generate a plan. **Save & use provider** makes it the planning default;
the provider selector beside your brief can switch between configured providers.
Model access and generation charges depend on the provider and your account.

Keys entered here stay in the local server's memory for the current run. They are
never written to project files or browser storage, and API responses never return
them. A blank key field keeps the current key; **Clear key** removes it for this
run. To supply keys again after a restart, set `OPENAI_API_KEY`, `GEMINI_API_KEY`,
or `COMPATIBLE_API_KEY` in the server's environment. Provider/model preferences
are saved without keys in the ignored `studio/.data/provider-settings.json`.
This menu configures this computer; it is not a user account or login system.

Ollama keeps planning on this PC. Cloud planning sends your brief and storyboard
instructions to the selected provider. Rendering, installed Windows voices,
music, and exported videos still run locally. Settings cannot change while a
planning or rendering job is in progress. No cloud API key is needed to author
scenes manually or render them with the local engine.

If planning fails, the previous storyboard stays open and is labeled separately
from the new request. Retry or switch providers to plan again, or start a new
project and author your own scenes. A successful **Test connection** checks model
listing; generation still requires access to the selected text model and available
API quota. Errors distinguish model access, JSON format support, and billing when
the provider supplies those details.

After updating Studio's Python code, stop the running launcher with Ctrl+C and
launch it again. Refresh the browser to load frontend changes. The page detects
an older server or changed Python sources and blocks planning and rendering until
the server is restarted, with instructions shown in a persistent banner. Keys entered in
Admin settings must be entered again after restart unless supplied through the
server's environment. Older versions sent OpenAI's JSON instruction only in the
top-level `instructions` field; OpenAI JSON mode also requires `JSON` in the actual
request input. The current planner includes that instruction in both places.

## What the model and this repository do

The planning model drafts scene titles, narration, colors, scene durations,
mathematical values, visual elements and their animation timelines. It can also
compose a tempo and MIDI chord score. OpenAI or Gemini are alternative planners
to Ollama; their APIs do not generate the video frames in this app. You review
and edit the draft before rendering.

This repository does the rest:

- `studio/web/`, `studio/server.py`, and `studio/providers.py` handle the interface,
  provider requests, and job queue.
- `studio/math_spec.py` validates math; `studio/math_scenes.py` and
  `studio/renderer.py` turn scene data into local animations and audio.
- `studio/composition_spec.py` validates authored visual elements and timelines;
  `studio/composition_scenes.py` animates their supplied content and geometry.
  `studio/music_spec.py` validates supplied scores and derives scores for older drafts.
- `src/manimgx/` and `rust/engine/` typeset the equations, animate objects, draw
  frames on the GPU, and encode the video.
- `studio/.data/` holds your resulting MP4, subtitles, and editable storyboard.

The profile menu's **How it works** guide lets you explore each step in the UI.

## What this version produces

- **Math / Manim:** typeset equations drawn and transformed step by step, real
  function plots on axes, Pythagorean triangles with proportional side squares,
  moving tangents for derivatives, shaded integrals, and vector addition on a
  coordinate plane. This is the default style. Equations, functions, axis bounds,
  triangle dimensions, and vector components must be supplied explicitly.
  Voice-over, music, and subtitles work with math videos too.
- **Explainers and illustrated stories:** model-authored vector compositions
  with text, equations, rectangles, circles, lines, arrows and polygons. Content,
  positions, colors, entrance, movement and exit timing come from the storyboard.
  Edit the composition JSON under each scene. These are vector animations;
  image generation, lip sync and diffusion video require additional renderers.
- **Voice-over:** installed Windows desktop voices through `System.Speech`,
  generated locally. Select a voice or turn narration off. Narration text should
  match the selected voice's language. A shot extends when its spoken audio is
  longer than its planned duration.
- **Music:** a locally synthesized instrumental using the storyboard's optional
  tempo and MIDI chord score. Edit it in **Sound & output → Music score**.
  If no score is supplied, a score is derived from this storyboard's content.
  The volume slider controls its level underneath narration.
- **Export:** preview and final MP4 quality, subtitles, and an editable storyboard.

Fresh projects start empty; there is no production library of canned storyboards.
Planning preserves the model's scene count and individual durations. Missing
mathematical values or empty compositions block rendering with a validation error;
Studio does not substitute a sample topic. Preset orbit, process, bars, character,
and landscape renderers have been removed. Older projects using these visuals must
be planned again or authored as compositions. **New project** clears the current
storyboard. There are no automatic project backups; download the storyboard
yourself before clearing it if you want to keep it. Studio deletes obsolete browser
drafts and backup storage on startup, and discards invalid saved drafts.

The model returns validated JSON; Studio interprets its drawing and animation data
without executing model-written Python or shell commands. Each storyboard
has 1–8 shots, 3–20 seconds per shot, and at most 120 planned seconds. Longer
narration can extend the exported film. Start with a short preview before a final
export.

Local planning sends the same JSON schema in the prompt and Ollama's constrained
output format. Studio reads streamed output until the complete JSON object is
available, then validates it. Invalid data is reported without replacing it with
sample content. Validation checks the rendering contract; review the draft to
confirm that the model followed your intended story and movement.

Math scene controls edit the actual equations, function, axis bounds, triangle
legs, or vector components used in the render. Right-triangle legs accept
0.01–10,000, and the figure scales to fit the frame without changing those values.
Equation steps accept LaTeX; ManimGX typesets them with its bundled Typst engine.
Function expressions use
`x`, `pi`, `e`, `+ - * / **`, and `sin`, `cos`, `tan`, `sqrt`, `exp`, `log`, `abs`.
For example, use `x**2` or `sin(x)`. Expressions are parsed as bounded arithmetic,
never executed as Python. Choose an x range where the function is defined;
integral y bounds must include zero and the whole function. The five math
tools provide core animations; choose **Custom composition** for other diagrams,
proof layouts and choreography within the supported visual primitives.
Tangent slopes and integral readouts are numerical approximations and are labeled
accordingly. Choose smooth functions for derivative animations; an undefined
tangent produces an actionable render error.

Composition coordinates use scene units, with x from −6 to 6 and y from −3 to 3.
Every element supplies `kind`, `start` and `end`. Times are fractions of the scene
duration: the entrance runs from `start` to `end`, then the element remains visible.
Optional `motion` supplies its own `start`, `end`, and final destination `x`, `y`.
Movement may overlap the entrance, so an object can fade or draw in while moving.
An optional `exit` starts after both entrance and movement finish.
Text/equations require `text`,
rectangles require `width`/`height`, circles require `radius`, and point-based
shapes require `points`. Up to 24 elements are allowed per shot. Composition
headings appear only when the storyboard supplies a text element.

The optional music object is `{ "tempo": 90, "chords": [[48, 55, 60], [50, 57, 62]] }`.
This is an editable example score. Tempo can be 40–180 BPM; each of 1–16 chords
contains 1–8 integer MIDI notes between 36 and 84.

The supplied ndimensions.AI artwork is stored unchanged in
`studio/web/assets/branding/` and appears in the header and browser icons.

Projects are written to `studio/.data/<job-id>/`: `plan.json`, `project.mp4`,
`project.srt`, `project.vtt`, narration WAVs, music, and actual timing information.
These generated files are ignored by Git. Job polling is kept in memory; after a
server restart the files remain, but the previous queue does not resume. The
browser retains the latest draft locally. Close the app when you have finished.

## Architecture and reliability

Studio uses a modular monolith: one local application with separate HTTP, provider,
validation, rendering, and UI modules. This suits a desktop workflow sharing one GPU.
The server accepts declarative scene data through typed, bounded validators; provider
adapters produce that same data contract, and the renderer owns frames and audio.
Keep new providers behind the planning boundary and new visual tools behind the
scene contract, with regression tests for each supported behavior.

A single worker serializes planning and rendering. Provider validation and queue
registration share a lock with settings changes, so another tab cannot change an
endpoint or credential between validation and submission. A stopped worker rejects
new work without leaving a phantom queued job. Media range requests remain bounded
and return a range error for unsupported offsets.

Exports are prepared in a staging directory before the completed artifacts replace
the previous video, captions, timing, and audio. Publication failures restore the
previous files. If a locked file also prevents rollback, the error reports the
retained recovery directory; close the application holding the file and restore
its original from that directory. Success and ordinary failure remove staging files.
Literal narration markup is escaped in WebVTT so captions display it as text.

## Design approach

The UI applies Google's [Material Design foundations](https://m3.material.io/foundations/):
consistent color roles, readable type, visible focus, generous controls, and an
adaptive layout. The workflow uses Google's
[People + AI feedback and control guidance](https://pair.withgoogle.com/chapter/feedback-controls/):
AI plans stay editable, progress uses real job states, and errors explain how to
recover. It is an independent app with Material-inspired styling.
Profile settings use accessible dialogs and visible focus. Loading buttons,
storyboard placeholders, scene transitions, and feedback make state changes
visible. Narration, music, scene preparation, and export use real renderer events;
scene counts describe preparation rather than claiming an overall encoding
percentage. Planning and encoding stay indeterminate when completion cannot yet
be measured. Motion respects the browser's reduced-motion preference.

Editing preserves unfinished composition JSON, music JSON, equation steps, and
duration fields across scene changes and reloads. Validation explains what needs
attention and blocks rendering until the draft is valid. The app never silently
renders an older valid value while an invalid edit is visible. Drafts over the
120-second limit can be restored and shortened. Removing an earlier scene keeps
the same selected content in view, and the screening room lets you switch between
the scene sketch and the last rendered video. Changed inputs mark that video as
out of date. Mobile fields use readable text and larger targets, with wrapping
controls, visible focus, and accessible error states.
Secondary labels and placeholders share a readable color role, with contrast
regressions checking the actual stylesheet against its background surfaces.

## Checks

```powershell
uv run --frozen --no-sync pytest studio/tests
uv run --frozen --no-sync ruff check studio
uv run --frozen --no-sync ty check studio
node --check studio/web/app.js
```

The test suite covers storyboard bounds, provider requests and credentials,
frontend provider state, job failures, API
request boundaries, seeking exported media, and generated audio. The renderer
can also be checked with a short real render; the engine and repository's normal
checks remain independent of Studio's unit tests.

The current extracted checkout has no `.git` metadata and no `just`/Bun command
on PATH, so the full `just check` and comparison against `main` cannot run here.
Studio checks above work directly. Whole-repository REUSE currently scans local
environment/build artifacts in this checkout and reports their license issues;
source-file licensing can be checked separately with `reuse lint-file`.
