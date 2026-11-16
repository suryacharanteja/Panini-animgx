# SPDX-FileCopyrightText: 2026 ndimensions.AI
# SPDX-License-Identifier: MIT
# ruff: noqa: PT009
"""Project migration and runtime checks keep unrelated work out of a new brief."""

from __future__ import annotations

import unittest

from studio.tests.test_frontend_math import APP, NODE, run_javascript
from studio.tests.test_frontend_planning import DOM

PROJECT_DOM = (
    DOM
    + r"""
const storage = new Map();
globalThis.localStorage = {
  getItem:(key)=>storage.get(key) || null,
  removeItem:(key)=>storage.delete(key),
  setItem(key,value) {
    storage.set(key,value);
    if (key === draftKey) storedDraft=JSON.parse(value);
  }
};
const makeElement = (tag) => ({tag,children:[],listeners:{},textContent:'',
  append(...children){this.children.push(...children);},
  replaceChildren(...children){this.children=children;},
  addEventListener(type,callback){this.listeners[type]=callback;},
  click(){this.listeners.click?.();}
});
document.createElement = makeElement;
document.createTextNode = (text)=>({textContent:text});
for (const id of ['scenes','video']) {
  const field=$(id);
  field.children=[];
  field.replaceChildren=(...children)=>{field.children=children;};
  field.append=(...children)=>{field.children.push(...children);};
}
$('musicScore').setCustomValidity=(message)=>{$('musicScore').validationMessage=message;};
$('video').pause=()=>{};
$('video').load=()=>{};
$('prompt').focus=()=>{};
setMode=(value)=>{selectedMode=value;updateModeHint();};
"""
)


@unittest.skipIf(NODE is None, "Node is needed to test browser helpers")
class FrontendProjectTests(unittest.TestCase):
    """Exercise deletion, blank projects, and server compatibility behavior."""

    def test_startup_deletes_obsolete_projects_and_preserves_valid_math_and_settings(
        self,
    ) -> None:
        self.assertTrue(
            run_javascript(
                PROJECT_DOM
                + """
plan=clone(mathExamples.pythagoras);
draftBrief={prompt:'My authored proof',mode:'math',duration:'30'};
$('prompt').value=draftBrief.prompt;
draftSource='manual';
const valid=clone(draftSnapshot());
const settings={voice_enabled:false,music_enabled:true,quality:'preview'};
for(const key of obsoleteDraftKeys)storage.set(key,JSON.stringify({plan:{title:'Old unrelated data'}}));
storage.set(draftKey,JSON.stringify(valid));
storage.set(settingsKey,JSON.stringify(settings));
assert.equal(loadSavedDraft(),true);
updateDraftContext();
assert.deepEqual(plan,valid.plan);
assert.deepEqual(draftBrief,valid.draftBrief);
assert.equal($('prompt').value,'My authored proof');
assert.equal($('draftBadge').textContent,'Saved draft');
assert.equal(previousDraft,false);
for(const key of obsoleteDraftKeys)assert.equal(storage.has(key),false);
assert.deepEqual(JSON.parse(storage.get(draftKey)),valid);
assert.deepEqual(JSON.parse(storage.get(settingsKey)),settings);
assert.deepEqual([...storage.keys()].sort(),[draftKey,settingsKey].sort());
console.log(JSON.stringify(true));
"""
            )
        )

    def test_startup_never_loads_an_old_project_or_its_entered_brief(self) -> None:
        self.assertTrue(
            run_javascript(
                PROJECT_DOM
                + """
const old={plan:{title:'Unrelated restored story',mode:'anime',scenes:[{
 title:'Introduction',narration:'Old words',visual:'character',duration:10,
 background:'#101b2d',accent:'#75d8f7'}]},prompt:'Obsolete prompt',mode:'anime',duration:'60'};
for(const key of obsoleteDraftKeys)storage.set(key,JSON.stringify(old));
plan={title:'Untitled video',mode:'math',scenes:[]};
draftOrigin='new';$('prompt').value='';
assert.equal(loadSavedDraft(),false);
updateDraftContext();updateSketch();
assert.deepEqual(plan.scenes,[]);
assert.equal(plan.mode,'math');
assert.equal($('prompt').value,'');
assert.equal($('draftBadge').textContent,'Your draft');
assert.equal($('renderButton').disabled,true);
assert.equal($('previewTitle').textContent,'Start with your idea');
assert.equal(storage.size,0);
console.log(JSON.stringify(true));
"""
            )
        )

    def test_invalid_v2_projects_are_discarded_without_creating_another_copy(
        self,
    ) -> None:
        self.assertTrue(
            run_javascript(
                PROJECT_DOM
                + """
const original=clone(draftSnapshot());
const badVisual=clone(original);
badVisual.plan.scenes[0].visual='character';
const mismatch=clone(original);mismatch.draftBrief.mode='math';
const invalid=[{...original,schema_version:1},badVisual,mismatch,{...original,plan:null}];
const settings={quality:'preview'};storage.set(settingsKey,JSON.stringify(settings));
for(const snapshot of invalid){
 storage.set(draftKey,JSON.stringify(snapshot));
 assert.equal(restoreDraft(snapshot),false);
 updateDraftContext();
 assert.deepEqual(plan.scenes,[]);
 assert.equal($('prompt').value,'');
 assert.equal($('draftBadge').textContent,'Your draft');
 assert.equal($('renderButton').disabled,true);
 assert.equal(storage.has(draftKey),false);
 assert.deepEqual([...storage.keys()],[settingsKey]);
 assert.match($('noticeText').textContent,/invalid saved project was discarded/);
}
assert.deepEqual(JSON.parse(storage.get(settingsKey)),settings);
console.log(JSON.stringify(true));
"""
            )
        )

    def test_malformed_v2_storage_is_removed_before_opening_a_blank_project(
        self,
    ) -> None:
        self.assertTrue(
            run_javascript(
                PROJECT_DOM
                + """
plan={title:'Untitled video',mode:'math',scenes:[]};$('prompt').value='';
storage.set(draftKey,'{"plan":');
assert.equal(loadSavedDraft(),false);
assert.equal(storage.has(draftKey),false);
assert.deepEqual(plan.scenes,[]);
assert.equal($('prompt').value,'');
console.log(JSON.stringify(true));
"""
            )
        )

    def test_verified_draft_restores_original_brief_and_exact_authored_data(
        self,
    ) -> None:
        self.assertTrue(
            run_javascript(
                PROJECT_DOM
                + """
plan.scenes[0].duration=9.125;
plan.scenes[0].composition.elements[0].motion={start:0.1,end:0.9,x:2.125,y:-1.625};
plan.music={tempo:97.5,chords:[[39,46],[43,50,55]]};
draftSource='model';planningState='failed';
const snapshot=clone(draftSnapshot());
assert.equal(restoreDraft(snapshot),true);
updateDraftContext();
assert.deepEqual(plan,snapshot.plan);
assert.deepEqual(draftBrief,snapshot.draftBrief);
assert.equal(draftSource,'model');
assert.equal(previousDraft,true);
assert.equal($('draftBadge').textContent,'Previous draft');
assert.equal(storage.size,0);
console.log(JSON.stringify(true));
"""
            )
        )

    def test_new_project_clears_current_content_and_video_without_saving_a_copy(
        self,
    ) -> None:
        self.assertTrue(
            run_javascript(
                PROJECT_DOM
                + """
plan.music={tempo:99,chords:[[41,48]]};
draftSource='model';planningState='failed';
activeRenderId='old-render';renderedFingerprint='old-fingerprint';
musicScoreError='Unfinished score';
storage.set(draftKey,JSON.stringify(draftSnapshot()));
storage.set(settingsKey,JSON.stringify({quality:'preview'}));
const providers=clone(providerSettings);
let clearedVideo=false;
$('video').removeAttribute=(name)=>{if(name==='src')clearedVideo=true;};
newProject();
assert.deepEqual(plan,{title:'Untitled video',mode:'math',scenes:[]});
assert.equal($('prompt').value,'');
assert.equal($('musicScore').value,'');
assert.equal(musicScoreError,'');
assert.equal(draftSource,'manual');
assert.equal(planningState,null);
assert.equal(previousDraft,false);
assert.equal(activeRenderId,null);
assert.equal(renderedFingerprint,null);
assert.equal(clearedVideo,true);
assert.equal($('downloadVideo').hidden,true);
assert.equal($('downloadSubtitles').hidden,true);
assert.equal($('renderButton').disabled,true);
assert.deepEqual(storedDraft.plan.scenes,[]);
assert.deepEqual(JSON.parse(storage.get(draftKey)).plan,plan);
assert.deepEqual([...storage.keys()].sort(),[draftKey,settingsKey].sort());
assert.deepEqual(providerSettings,providers);
assert.deepEqual(JSON.parse(storage.get(settingsKey)),{quality:'preview'});
console.log(JSON.stringify(true));
"""
            )
        )

    def test_storage_failure_does_not_restore_old_data_or_claim_deletion_succeeded(
        self,
    ) -> None:
        self.assertTrue(
            run_javascript(
                PROJECT_DOM
                + """
const attempted=[];
localStorage.removeItem=(key)=>{attempted.push(key);throw new Error('Storage blocked');};
localStorage.setItem=()=>{throw new Error('Storage blocked');};
assert.equal(purgeObsoleteDrafts(),false);
assert.deepEqual(attempted,obsoleteDraftKeys);
assert.match($('noticeText').textContent,/storage prevented deleting project data/);
newProject();
assert.deepEqual(plan.scenes,[]);
assert.equal($('prompt').value,'');
assert.equal($('renderButton').disabled,true);
assert.match($('noticeText').textContent,/storage prevented deleting project data/);
assert.equal($('saveStatus').textContent,'Draft storage unavailable');
assert.equal(restoreDraft({plan:{title:'Invalid',scenes:[]},prompt:'Old input'}),false);
assert.deepEqual(plan.scenes,[]);
assert.equal($('prompt').value,'');
console.log(JSON.stringify(true));
"""
            )
        )

    def test_reset_overwrites_old_content_when_removal_fails_but_writing_works(
        self,
    ) -> None:
        self.assertTrue(
            run_javascript(
                PROJECT_DOM
                + """
storage.set(draftKey,JSON.stringify(draftSnapshot()));
localStorage.removeItem=()=>{throw new Error('Removal blocked');};
newProject();
assert.deepEqual(JSON.parse(storage.get(draftKey)).plan,{title:'Untitled video',mode:'math',scenes:[]});
assert.equal($('notice').hidden,true);
assert.deepEqual(plan.scenes,[]);
console.log(JSON.stringify(true));
"""
            )
        )

    def test_runtime_404_stale_or_unsupported_server_cannot_submit_jobs(self) -> None:
        self.assertTrue(
            run_javascript(
                PROJECT_DOM
                + """
serviceBadge=()=>{};setOptions=()=>{};
(async()=>{
  for (const runtime of [null,{protocol:1,restart_required:false},
    {protocol:2,restart_required:true},{protocol:2}]) {
    const paths=[];
    api=async(path)=>{paths.push(path);if(runtime===null)throw new Error('HTTP 404');return runtime;};
    await loadStatus();
    assert.deepEqual(paths,['/api/runtime']);
    assert.equal(runtimeReady,false);
    assert.equal($('runtimeNotice').hidden,false);
    assert.equal($('runtimeNoticeText').textContent,restartMessage);
    assert.equal($('planButton').disabled,true);
    assert.equal($('renderButton').disabled,true);
    showNotice('Another error');
    $('notice').hidden=true;
    assert.equal($('runtimeNotice').hidden,false);
    await planVideo();
    assert.deepEqual(paths,['/api/runtime']);
  }
  console.log(JSON.stringify(true));
})().catch((error)=>{console.error(error);process.exitCode=1;});
"""
            )
        )

    def test_compatible_runtime_is_checked_before_services_and_clears_restart_banner(
        self,
    ) -> None:
        self.assertTrue(
            run_javascript(
                PROJECT_DOM
                + """
serviceBadge=()=>{};setOptions=()=>{};updatePlanner=()=>{};
const paths=[];
api=async(path)=>{
  paths.push(path);
  if(path==='/api/runtime')return{protocol:2,restart_required:false};
  assert.equal(path,'/api/status');
  return{ollama:{connected:true,models:['local-model']},engine:{available:true},voices:[]};
};
$('runtimeNotice').hidden=false;
(async()=>{
  await loadStatus();
  assert.deepEqual(paths,['/api/runtime','/api/status']);
  assert.equal(runtimeReady,true);
  assert.equal($('runtimeNotice').hidden,true);
  assert.equal($('planButton').disabled,false);
  assert.equal($('renderButton').disabled,false);
  console.log(JSON.stringify(true));
})().catch((error)=>{console.error(error);process.exitCode=1;});
"""
            )
        )

    def test_mode_heading_and_brand_fallback_follow_actual_state(self) -> None:
        self.assertTrue(
            run_javascript(
                PROJECT_DOM
                + """
for (const [selected,title] of [['anime','Bring your story into motion.'],
  ['explainer','Make your ideas clear.'],['math','Make mathematics move.']]) {
  selectedMode=selected;updateModeHint();
  assert.equal($('workspaceTitle').textContent,title);
}
selectedMode='anime';updateModeHint();
assert.match($('modeHint').textContent,/does not run a generative anime/);
const classes=new Set();
const brand={classList:{toggle(name,value){if(value)classes.add(name);else classes.delete(name);},add(name){classes.add(name);}},
  querySelectorAll:()=>images};
const images=[{complete:true,naturalWidth:0,listeners:{},
  addEventListener(type,callback){this.listeners[type]=callback;}},
  {complete:true,naturalWidth:128,listeners:{},
  addEventListener(type,callback){this.listeners[type]=callback;}}];
document.querySelector=()=>brand;
initializeBranding();
assert.equal(classes.has('image-unavailable'),true);
images[0].naturalWidth=2440;images[0].listeners.load();
assert.equal(classes.has('image-unavailable'),false);
images[1].listeners.error();
assert.equal(classes.has('image-unavailable'),true);
console.log(JSON.stringify(true));
"""
            )
        )

    def test_production_has_only_authored_visual_choices_and_original_logo_assets(
        self,
    ) -> None:
        source = APP.read_text(encoding="utf-8")
        html = (APP.parent / "index.html").read_text(encoding="utf-8")
        self.assertNotIn("const mathExamples", source)
        self.assertNotIn("const samples", source)
        self.assertNotIn("const art =", source)
        self.assertNotIn("function defaultMath", source)
        self.assertNotIn('id="loadSample"', html)
        self.assertNotIn('class="story-visuals"', html)
        self.assertIn('id="newProject"', html)
        self.assertNotIn("retainedNotice", html)
        self.assertNotIn("retainedProjects", html)
        self.assertNotIn("downloadable backup", html)
        self.assertNotIn("function archiveDraft", source)
        self.assertNotIn("function downloadRetainedProject", source)
        self.assertNotIn("function updateRetainedProjects", source)
        self.assertIn('id="runtimeNotice"', html)
        self.assertIn("/assets/branding/panini-animgx-lockup.png", html)
        self.assertIn("/assets/branding/panini-animgx-icon-128.png", html)
        self.assertTrue(
            run_javascript(
                """
assert.deepEqual([...visuals],['composition','equation','graph','geometry','calculus','vectors']);
for (const mode of ['math','anime','explainer']) {
  for (const visual of ['orbit','process','bars','character','landscape']) {
    assert.throws(()=>validatePlan({title:'Authored',mode,scenes:[{
      title:'Authored scene',narration:'',visual,duration:6,
      background:'#101b2d',accent:'#75d8f7'}]}),/invalid words, timing, or visuals/);
  }
}
console.log(JSON.stringify(true));
"""
            )
        )
