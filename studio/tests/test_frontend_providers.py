# SPDX-FileCopyrightText: 2026 Panini-Animgx contributors
# SPDX-License-Identifier: MIT
# ruff: noqa: PT009
"""Exercise provider selection, secret boundaries, and honest workflow progress."""

from __future__ import annotations

import unittest
from pathlib import Path

from studio.tests.test_frontend_math import NODE, run_javascript


@unittest.skipIf(NODE is None, "Node is needed to test browser helpers")
class FrontendProviderTests(unittest.TestCase):
    """Keep settings and planning payloads consistent with the local server."""

    def test_planning_payload_uses_selected_provider_and_preserves_math(self) -> None:
        self.assertTrue(
            run_javascript(
                """
const fields = {
  plannerProvider:{value:'ollama'}, model:{value:'qwen2.5:3b-instruct'},
  cloudModel:{value:'remote-model'}, prompt:{value:'  Explain x squared  '},
  duration:{value:'30'}
};
globalThis.document = {
  getElementById: (id) => fields[id],
  querySelector: () => ({value:'math'})
};
assert.deepEqual(planningPayload(), {
  provider:'ollama', model:'qwen2.5:3b-instruct',
  prompt:'Explain x squared', mode:'math', duration:30
});
for (const provider of ['openai', 'gemini', 'compatible']) {
  fields.plannerProvider.value = provider;
  assert.equal(planningPayload().provider, provider);
  assert.equal(planningPayload().model, 'remote-model');
  assert.equal(planningPayload().mode, 'math');
}
console.log(JSON.stringify(true));
"""
            )
        )

    def test_blank_key_preserves_secret_and_keys_never_enter_browser_storage(
        self,
    ) -> None:
        self.assertTrue(
            run_javascript(
                """
const fields = {
  adminProvider:{value:'openai'}, adminModel:{value:'  model-id  '},
  adminBaseUrl:{value:'https://example.com/v1'}, adminApiKey:{value:''},
  prompt:{value:'Idea'}, duration:{value:'30'}, model:{value:'local-model'},
  voiceEnabled:{checked:true}, voice:{value:'Local voice'},
  musicEnabled:{checked:true}, musicVolume:{value:'0.18'}, quality:{value:'preview'},
  saveStatus:{innerHTML:'', classList:{remove(){}, add(){}}}
};
globalThis.document = {
  getElementById: (id) => fields[id],
  querySelector: () => ({value:'math'})
};
globalThis.requestAnimationFrame = (callback) => callback();
const writes = new Map();
globalThis.localStorage = {setItem: (key,value) => writes.set(key,value)};
assert.deepEqual(adminSettingsPayload(true), {
  provider:'openai', model:'model-id', active_provider:'openai'
});
fields.adminApiKey.value = 'fake-test-secret-do-not-persist';
const request = adminSettingsPayload(true);
assert.equal(request.api_key, fields.adminApiKey.value);
persistDraft();
persistSettings();
for (const stored of writes.values()) {
  assert.ok(!stored.includes('fake-test-secret'));
  assert.ok(!stored.includes('api_key'));
}
fields.adminProvider.value = 'compatible';
assert.equal(adminSettingsPayload().base_url, 'https://example.com/v1');
assert.ok(!('active_provider' in adminSettingsPayload()));
fields.adminProvider.value = 'ollama';
assert.ok(!('api_key' in adminSettingsPayload()));
console.log(JSON.stringify(true));
"""
            )
        )

    def test_cloud_planning_is_available_when_ollama_is_offline(self) -> None:
        self.assertTrue(
            run_javascript(
                """
const fields = new Map();
globalThis.document = {getElementById(id) {
  if (!fields.has(id)) fields.set(id, {
    value:'', checked:true, textContent:'', disabled:false,
    style:{}, classList:{toggle(){}}, required:false
  });
  return fields.get(id);
}};
services = {
  ollama:{connected:false, models:[], error:'Ollama offline'},
  engine:{available:true}, voices:['Local voice']
};
statusLoaded = true;
runtimeReady = true;
providerSettings.providers.find((item) => item.id === 'openai').configured = true;
fields.set('plannerProvider', {value:'openai'});
fields.set('cloudModel', {value:'cloud-model', required:false});
plan = clone(mathExamples.derivative);
updateButtons();
assert.equal(fields.get('planButton').disabled, false);
assert.equal(fields.get('renderButton').disabled, false);
fields.get('plannerProvider').value = 'ollama';
updateButtons();
assert.equal(fields.get('planButton').disabled, true);
assert.equal(fields.get('renderButton').disabled, false);
fields.get('plannerProvider').value = 'gemini';
updateButtons();
assert.equal(fields.get('planButton').disabled, true);
console.log(JSON.stringify(true));
"""
            )
        )

    def test_public_settings_only_adopt_public_metadata(self) -> None:
        self.assertTrue(
            run_javascript(
                """
const fields = {plannerProvider:{value:'ollama'}, keyNotice:{querySelector:()=>({})}};
globalThis.document = {getElementById: (id) => fields[id]};
updatePlanner = () => {};
adoptProviderSettings({active_provider:'openai', providers:[{
  id:'openai',name:'OpenAI',model:'cloud-model',configured:true,key_set:true,
  key_source:'session',scope:'cloud',requires_key:true,api_key:'unwanted-secret'
}]});
assert.equal(fields.plannerProvider.value, 'openai');
assert.equal(providerInfo('openai').key_set, true);
assert.ok(!JSON.stringify(providerSettings).includes('unwanted-secret'));
assert.ok(!('api_key' in providerInfo('openai')));
console.log(JSON.stringify(true));
"""
            )
        )

    def test_provider_actions_restore_focus_only_while_dialog_is_open(self) -> None:
        self.assertTrue(
            run_javascript(
                """
let focused = null;
const fields = new Map();
globalThis.document = {getElementById(id) {
  if (!fields.has(id)) fields.set(id, {
    value:'openai',open:true,disabled:false,
    classList:{toggle(){}},setAttribute(){},querySelectorAll:()=>[],
    focus(){focused = id;}
  });
  return fields.get(id);
}};
setAdminBusy(true, 'testProvider');
setAdminBusy(false, 'testProvider');
assert.equal(focused, 'testProvider');
fields.get('adminDialog').open = false;
focused = null;
setAdminBusy(false, 'saveProvider');
assert.equal(focused, null);
fields.get('adminDialog').open = true;
setAdminBusy(false, 'clearKey');
assert.equal(focused, 'adminApiKey');
console.log(JSON.stringify(true));
"""
            )
        )

    def test_job_start_reveals_progress_once_without_changing_keyboard_focus(
        self,
    ) -> None:
        self.assertTrue(
            run_javascript(
                """
const scrolls = [];
const starts = [];
const elements = new Map();
globalThis.document = {getElementById(id) {
  if (!elements.has(id)) elements.set(id, {
    textContent:'',className:'',classList:{toggle(){}},
    setAttribute(){},removeAttribute(){},querySelector:()=>({style:{}}),
    scrollIntoView: (options) => scrolls.push(options),
    focus: () => { throw new Error('Starting a job must not steal focus'); }
  });
  return elements.get(id);
}};
globalThis.window = {matchMedia:()=>({matches:false})};
setBusy = (value,kind) => starts.push([value,kind]);
beginJob('plan','Planning');
assert.deepEqual(starts, [[true,'plan']]);
assert.deepEqual(scrolls, [{behavior:'smooth',block:'start'}]);
updateJob('plan','running','Still planning');
assert.equal(scrolls.length, 1);
globalThis.window.matchMedia = () => ({matches:true});
beginJob('render','Rendering');
assert.deepEqual(scrolls[1], {behavior:'auto',block:'start'});
console.log(JSON.stringify(true));
"""
            )
        )

    def test_scene_progress_uses_actual_counts_and_other_stages_are_indeterminate(
        self,
    ) -> None:
        self.assertTrue(
            run_javascript(
                """
assert.equal(jobProgress({status:'complete'}), 1);
assert.equal(jobProgress({status:'running',stage:'render',completed_scenes:2,total_scenes:4}), .5);
assert.equal(jobProgress({status:'running',stage:'render',completed_scenes:0,total_scenes:4}), 0);
for (const stage of ['queued','planning','audio','music','export']) {
  assert.equal(jobProgress({status:'running',stage,completed_scenes:2,total_scenes:4}), null);
}
for (const [completed_scenes,total_scenes] of [[5,4],[-1,4],[1,0],[.5,4],[1,Infinity]]) {
  assert.equal(jobProgress({status:'running',stage:'render',completed_scenes,total_scenes}), null);
}
console.log(JSON.stringify(true));
"""
            )
        )

    def test_settings_use_native_dialogs_and_animation_honors_reduced_motion(
        self,
    ) -> None:
        web = Path(__file__).resolve().parents[1] / "web"
        html = (web / "index.html").read_text(encoding="utf-8")
        css = (web / "styles.css").read_text(encoding="utf-8")
        script = (web / "app.js").read_text(encoding="utf-8")
        self.assertIn('<dialog id="adminDialog"', html)
        self.assertIn('id="adminApiKey" type="password"', html)
        self.assertIn('aria-controls="profileMenu"', html)
        self.assertIn('dialog.addEventListener("close"', script)
        self.assertIn('$("adminApiKey").value = ""', script)
        self.assertIn("@media(prefers-reduced-motion:reduce)", css)
        self.assertIn(".progress-track.determinate>span", css)
        self.assertIn(".loading:before", css)
        self.assertIn('value="geometry"', html)
        self.assertIn('value="calculus"', html)


if __name__ == "__main__":
    unittest.main()
