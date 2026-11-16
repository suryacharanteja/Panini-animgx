# SPDX-FileCopyrightText: 2026 Panini-Animgx contributors
# SPDX-License-Identifier: MIT
# ruff: noqa: PT009
"""Retained drafts cannot be mistaken for a failed or pending model response."""

from __future__ import annotations

import unittest

from studio.tests.test_frontend_math import NODE, run_javascript

DOM = r"""
const fields = new Map();
let selectedMode = 'math';
globalThis.document = {
  getElementById(id) {
    if (!fields.has(id)) {
      const classes = new Set();
      const progress = {style:{}};
      fields.set(id, {
        value:'', checked:true, textContent:'', innerHTML:'', disabled:false,
        hidden:false, style:{},
        classList:{
          toggle(name, value) {if (value) classes.add(name); else classes.delete(name);},
          add(name) {classes.add(name);}, remove(name) {classes.delete(name);},
          contains(name) {return classes.has(name);}
        },
        reportValidity:()=>true, setAttribute(){}, removeAttribute(){},
        querySelector:()=>progress, scrollIntoView(){}
      });
    }
    return fields.get(id);
  },
  querySelector:()=>({value:selectedMode}), querySelectorAll:()=>[]
};
globalThis.window = {matchMedia:()=>({matches:true})};
globalThis.requestAnimationFrame = (callback) => callback();
let storedDraft;
globalThis.localStorage = {setItem(key, value) {
  if (key === draftKey) storedDraft = JSON.parse(value);
}};
for (const [id,value] of Object.entries({
  prompt:'Pythagorean theorem', duration:'30', plannerProvider:'openai',
  cloudModel:'gpt-4.1-mini', model:'local-model', musicVolume:'0.18', quality:'preview'
})) $(id).value = value;
services.engine.available = true;
statusLoaded = true;
runtimeReady = true;
providerSettings.providers.find((provider) => provider.id === 'openai').configured = true;
plan = clone(samples.anime);
draftOrigin = 'saved';
draftBrief = {prompt:'An illustrated story',mode:'anime',duration:'30'};
"""


@unittest.skipIf(NODE is None, "Node is needed to test browser helpers")
class FrontendPlanningTests(unittest.TestCase):
    """Keep the user's previous work while making its provenance visible."""

    def test_changed_brief_or_style_labels_draft_and_preview_as_previous(self) -> None:
        self.assertTrue(
            run_javascript(
                DOM
                + """
const retained = clone(plan);
updateDraftContext();
assert.deepEqual(plan, retained);
assert.equal($('draftBadge').textContent, 'Previous draft');
assert.equal($('draftContext').hidden, false);
assert.match($('draftContextText').textContent, /Illustrated story.*previous brief/);
assert.equal($('draftStyle').textContent, 'Illustrated story');
assert.equal($('sketchBadge').textContent, 'PREVIOUS DRAFT SKETCH');
assert.equal($('renderLabel').textContent, 'Render previous draft');
selectedMode = 'anime';
$('prompt').value = draftBrief.prompt;
updateDraftContext();
assert.equal($('draftBadge').textContent, 'Saved draft');
assert.equal($('draftContext').hidden, true);
assert.equal($('renderLabel').textContent, 'Render video');
console.log(JSON.stringify(true));
"""
            )
        )

    def test_failed_request_preserves_draft_and_reports_no_new_storyboard(self) -> None:
        self.assertTrue(
            run_javascript(
                DOM
                + """
const retained = clone(plan);
const states = [];
setBusy = (value, kind) => {busy=value; busyKind=value ? kind : null; updateButtons();};
api = async (path, payload) => {
  assert.equal(path, '/api/plan');
  assert.equal(payload.mode, 'math');
  assert.equal(payload.prompt, 'Pythagorean theorem');
  states.push(planningState);
  assert.match($('draftContextText').textContent, /kept until the new plan is ready/);
  throw new Error('OpenAI rejected the planning request.');
};
(async () => {
  await planVideo();
  assert.deepEqual(states, ['pending']);
  assert.equal(busy, false);
  assert.equal(planningState, 'failed');
  assert.deepEqual(plan, retained);
  assert.equal($('draftBadge').textContent, 'Previous draft');
  assert.match($('draftContextText').textContent, /^No new storyboard was loaded/);
  assert.match($('draftContextText').textContent, /Retry planning or start a new project/);
  assert.equal($('noticeText').textContent, 'OpenAI rejected the planning request.');
  assert.deepEqual(storedDraft.plan, retained);
  assert.equal(storedDraft.mode, 'math');
  assert.equal(storedDraft.draftBrief.mode, 'anime');
  assert.equal(storedDraft.planningState, 'failed');
  console.log(JSON.stringify(true));
})().catch((error) => {console.error(error);process.exitCode=1;});
"""
            )
        )

    def test_successful_retry_replaces_old_draft_and_resets_provenance(self) -> None:
        self.assertTrue(
            run_javascript(
                DOM
                + """
planningState = 'failed';
previousDraft = true;
setBusy = (value, kind) => {busy=value; busyKind=value ? kind : null; updateButtons();};
setMode = (value) => {selectedMode=value;};
refreshPlan = () => {updateDraftBadge(); persistDraft();};
showSketch = () => {};
showToast = () => {};
api = async () => ({id:'new-plan'});
waitForJob = async () => ({plan:clone(mathExamples.pythagoras)});
(async () => {
  await planVideo();
  assert.deepEqual(plan, mathExamples.pythagoras);
  assert.equal(draftOrigin, 'generated');
  assert.equal(planningState, null);
  assert.equal(previousDraft, false);
  assert.equal($('draftBadge').textContent, 'Model draft');
  assert.equal($('draftContext').hidden, true);
  assert.equal($('draftStyle').textContent, 'Math / Manim');
  assert.equal($('sketchBadge').textContent, 'SCHEMATIC SKETCH');
  assert.deepEqual(storedDraft.draftBrief, {
    prompt:'Pythagorean theorem',mode:'math',duration:'30'
  });
  console.log(JSON.stringify(true));
})().catch((error) => {console.error(error);process.exitCode=1;});
"""
            )
        )

    def test_previous_render_is_not_presented_as_result_of_new_brief(self) -> None:
        self.assertTrue(
            run_javascript(
                DOM
                + """
activeRenderId = 'previous-video';
renderedFingerprint = JSON.stringify({plan,options:renderOptions()});
updateDraftContext();
assert.match($('videoCaption').textContent, /^Previous render of the earlier draft/);
assert.match($('videoCaption').textContent, /new storyboard has not been loaded/);
console.log(JSON.stringify(true));
"""
            )
        )

    def test_reload_keeps_selected_math_brief_and_previous_story_draft(self) -> None:
        self.assertTrue(
            run_javascript(
                DOM
                + """
planningState = 'failed';
persistDraft();
const retained = clone(plan);
plan = clone(samples.math);
planningState = null;
$('prompt').value = '';
selectedMode = 'anime';
setMode = (value) => {selectedMode=value;};
restoreDraft(storedDraft);
updateDraftContext();
assert.deepEqual(plan, retained);
assert.equal(mode(), 'math');
assert.equal($('prompt').value, 'Pythagorean theorem');
assert.equal(planningState, 'failed');
assert.equal($('draftBadge').textContent, 'Previous draft');
assert.match($('draftContextText').textContent, /^No new storyboard was loaded/);
console.log(JSON.stringify(true));
"""
            )
        )


if __name__ == "__main__":
    unittest.main()
