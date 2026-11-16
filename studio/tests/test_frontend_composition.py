# SPDX-FileCopyrightText: 2026 ndimensions.AI
# SPDX-License-Identifier: MIT
# ruff: noqa: PT009
"""Preserve reviewed scene content and timing without inserting template topics."""

from __future__ import annotations

import unittest
from typing import cast

from studio import composition_spec
from studio.tests.test_frontend_math import NODE, run_javascript
from studio.tests.test_frontend_planning import DOM

COMPOSITION = r"""
const custom = {
  title:'My diagram', mode:'explainer',
  music:{tempo:93,chords:[[48,55],[51,58,63]]},
  scenes:[{
    title:'A custom scene', narration:'Describe my diagram.',
    visual:'composition', duration:9, background:'#101b2d', accent:'#75d8f7',
    composition:{elements:[
      {kind:'text',text:'  My own title  ',x:-2,y:2,start:0,end:0.2,
       font_size:32,color:'#ab12cd',motion:{start:0.3,end:0.6,x:1,y:2},
       exit:{start:0.8,end:1}},
      {kind:'equation',text:'E = mc^2',x:2,y:1,start:0.2,end:0.35,entrance:'write'},
      {kind:'rectangle',width:2.4,height:1.5,x:-3,y:-1,start:0.1,end:0.3,
       fill_color:'#abcdef',fill_opacity:0.4,stroke_width:3},
      {kind:'circle',radius:0.7,x:3,y:-1,start:0.15,end:0.4},
      {kind:'line',points:[[-1,-2],[1,-2]],start:0.2,end:0.45},
      {kind:'arrow',points:[[-1,0],[1,0]],start:0.4,end:0.6},
      {kind:'polygon',points:[[0,-1],[0.5,-2],[-0.5,-2]],start:0.6,end:0.8}
    ]}
  }]
};
"""


@unittest.skipIf(NODE is None, "Node is needed to test browser helpers")
class FrontendCompositionTests(unittest.TestCase):
    """Keep the browser and rendering language in agreement."""

    def test_reviewed_composition_and_music_survive_payload_roundtrip(self) -> None:
        result = cast(
            dict[str, object],
            run_javascript(
                COMPOSITION
                + """
const payload = validatePlan(custom);
assert.equal(payload.scenes[0].duration, 9);
assert.equal(payload.scenes[0].composition.elements[0].text, '  My own title  ');
assert.equal(payload.scenes[0].composition.elements[0].color, '#AB12CD');
assert.deepEqual(payload.music, custom.music);
assert.deepEqual(validatePlan(JSON.parse(JSON.stringify(payload))), payload);
assert.equal(custom.scenes[0].composition.elements[0].color, '#ab12cd');
for (const mode of ['math', 'anime', 'explainer']) {
  assert.equal(validatePlan({...custom, mode}).scenes[0].visual, 'composition');
}
console.log(JSON.stringify(payload));
"""
            ),
        )
        scenes = cast(list[dict[str, object]], result["scenes"])
        self.assertEqual(
            composition_spec.validate_composition(scenes[0]["composition"]),
            scenes[0]["composition"],
        )

    def test_no_content_or_timing_is_substituted_for_invalid_model_elements(
        self,
    ) -> None:
        self.assertTrue(
            run_javascript(
                """
const invalid = [
  undefined, {}, {elements:[]}, {elements:Array(25).fill({kind:'text',text:'a',start:0,end:1})},
  {elements:[{kind:'text',start:0,end:1}]},
  {elements:[{kind:'text',text:'a',end:1}]},
  {elements:[{kind:'text',text:'a',start:0.2,end:0.2}]},
  {elements:[{kind:'text',text:'a',start:0,end:1,code:'print(1)'}]},
  {elements:[{kind:'text',text:'a',start:0,end:1,font_size:true}]},
  {elements:[{kind:'text',text:'a',start:0,end:1,fill_color:'#aabbcc'}]},
  {elements:[{kind:'text',text:'a\\t',start:0,end:1}]},
  {elements:[{kind:'equation',text:'x=1\\ny=2',start:0,end:1}]},
  {elements:[{kind:'rectangle',width:2,start:0,end:1}]},
  {elements:[{kind:'circle',radius:3.1,start:0,end:1}]},
  {elements:[{kind:'arrow',points:[[0,0],[0,0]],start:0,end:1}]},
  {elements:[{kind:'line',points:[[0,0],[1,1]],x:1,start:0,end:1}]},
  {elements:[{kind:'polygon',points:[[0,0],[1,1],[2,2]],start:0,end:1}]},
  {elements:[{kind:'text',text:'a',start:0,end:0.5,motion:{start:-0.1,end:0.6,x:1,y:1}}]},
  {elements:[{kind:'text',text:'a',start:0,end:0.2,motion:{start:0.3,end:0.6,x:1,y:1},exit:{start:0.5,end:1}}]},
  {elements:[{kind:'text',text:'a',start:0,end:0.2,exit:{start:0.5,end:1,code:'x'}}]}
];
for (const value of invalid) assert.throws(() => validateComposition(value));
assert.deepEqual(validateComposition({elements:[]}, true), {elements:[]});
console.log(JSON.stringify(true));
"""
            )
        )

    def test_concurrent_appearance_and_movement_roundtrip_without_rewriting_windows(
        self,
    ) -> None:
        payload = cast(
            dict[str, object],
            run_javascript(
                """
const authored = {elements:[{
  kind:'circle',radius:0.5,x:-3,y:0,start:0,end:1,
  motion:{start:0.25,end:0.75,x:3,y:0}
}]};
const before = clone(authored);
const validated = validateComposition(authored);
assert.deepEqual(validated, before);
assert.deepEqual(authored, before);
const project = {title:'My moving circle',mode:'anime',scenes:[{
  title:'Move while appearing',narration:'',visual:'composition',duration:9,
  background:'#101b2d',accent:'#75d8f7',composition:authored
}]};
assert.deepEqual(validatePlan(project).scenes[0].composition, before);
assert.deepEqual(validatePlan(JSON.parse(JSON.stringify(project))), project);
const summary = compositionSummary(project.scenes[0]);
assert.match(summary, /0–9s entrance/);
assert.match(summary, /moves to \\(3, 0\\) 2.25–6.75s/);
console.log(JSON.stringify(validated));
"""
            ),
        )
        self.assertEqual(composition_spec.validate_composition(payload), payload)

    def test_exit_waits_for_both_concurrent_windows_to_finish(self) -> None:
        self.assertTrue(
            run_javascript(
                """
for (const [entranceEnd,motionEnd] of [[0.6,0.4],[0.2,0.8]]) {
  const element = {kind:'text',text:'My content',start:0,end:entranceEnd,
    motion:{start:0.1,end:motionEnd,x:1,y:0},
    exit:{start:Math.max(entranceEnd,motionEnd),end:1}};
  assert.deepEqual(validateComposition({elements:[element]}), {elements:[element]});
  const collision = clone(element);
  collision.exit.start -= 0.01;
  assert.throws(()=>validateComposition({elements:[collision]}), /exit start/);
}
const beforeAppearance = {kind:'text',text:'My content',start:0.2,end:0.5,
  motion:{start:0,end:0.3,x:1,y:0}};
assert.deepEqual(validateComposition({elements:[beforeAppearance]}), {elements:[beforeAppearance]});
console.log(JSON.stringify(true));
"""
            )
        )

    def test_blank_and_incomplete_drafts_do_not_load_example_content(self) -> None:
        self.assertTrue(
            run_javascript(
                """
assert.equal(plan.title, 'Untitled video');
assert.deepEqual(plan.scenes, []);
assert.throws(() => validatePlan(plan));
assert.deepEqual(validatePlan(plan, true), plan);
const scene = {
  title:'Untitled scene',narration:'',visual:'composition',duration:6,
  background:'#101b2d',accent:'#75d8f7',composition:{elements:[]}
};
plan.scenes.push(scene);
assert.deepEqual(validatePlan(plan, true).scenes[0].composition, {elements:[]});
assert.throws(() => validatePlan(plan), /composition needs/);
for (const visual of mathVisuals) {
  const blank = {...scene, visual, math:emptyMath(visual)};
  delete blank.composition;
  assert.deepEqual(validatePlan({...plan, scenes:[blank]}, true).scenes[0].math, blank.math);
  assert.throws(() => validatePlan({...plan, scenes:[blank]}));
}
console.log(JSON.stringify(true));
"""
            )
        )

    def test_empty_user_draft_restores_without_loading_a_story(self) -> None:
        self.assertTrue(
            run_javascript(
                DOM
                + """
const empty = {title:'My next video',mode:'explainer',scenes:[]};
setMode = (value) => {selectedMode=value;};
restoreDraft({schema_version:2,provenance:'manual',plan:empty,origin:'edited',prompt:'A new idea',mode:'explainer',
  duration:'45',draftBrief:{prompt:'A new idea',mode:'explainer',duration:'45'}});
updateDraftContext();
assert.deepEqual(plan, empty);
assert.equal(mode(), 'explainer');
assert.equal($('prompt').value, 'A new idea');
assert.equal(previousDraft, false);
assert.equal($('renderButton').disabled, true);
assert.match($('renderHint').textContent, /add your first scene/);
console.log(JSON.stringify(true));
"""
            )
        )

    def test_invalid_json_edits_are_kept_visible_and_block_rendering(self) -> None:
        self.assertTrue(
            run_javascript(
                COMPOSITION
                + """
plan = validatePlan(custom);
const scene = plan.scenes[0];
const reviewed = clone(scene.composition);
let saved = 0;
markEdited = () => {saved++;};
updateButtons = () => {};
const input = {value:'{"elements": [',setCustomValidity(message){this.error=message;}};
editComposition(input, scene);
assert.deepEqual(scene.composition, reviewed);
assert.equal(compositionEdits.get(scene).text, input.value);
assert.match(renderReadiness(), /Finish the composition JSON/);
assert.equal(saved, 1);
input.value = JSON.stringify({elements:[{kind:'text',text:'Changed content',start:0.2,end:0.7}]});
editComposition(input, scene);
assert.equal(input.error, '');
assert.equal(scene.composition.elements[0].text, 'Changed content');
assert.equal(scene.composition.elements[0].start, 0.2);
assert.equal(renderReadiness(), '');
assert.equal(saved, 2);
console.log(JSON.stringify(true));
"""
            )
        )

    def test_changing_visual_clears_errors_from_the_previous_composition(self) -> None:
        self.assertTrue(
            run_javascript(
                COMPOSITION
                + """
plan = validatePlan(custom);
const scene = plan.scenes[0];
markEdited = () => {};
updateButtons = () => {};
const input = {value:'{',setCustomValidity(){}};
editComposition(input, scene);
assert.match(renderReadiness(), /Finish the composition JSON/);
changeSceneVisual(scene, 'graph');
assert.equal(compositionEdits.has(scene), false);
assert.equal('composition' in scene, false);
assert.equal(scene.math.expression, '');
scene.math = {expression:'cos(x)',x_min:-3,x_max:3,y_min:-2,y_max:2};
assert.equal(renderReadiness(), '');
changeSceneVisual(scene, 'composition');
assert.equal(compositionEdits.has(scene), false);
assert.equal('math' in scene, false);
assert.deepEqual(scene.composition, {elements:[]});
assert.match(renderReadiness(), /composition needs/);
assert.equal(visuals.has('character'), false);
assert.throws(()=>changeSceneVisual(scene, 'character'), /supported scene visual/);
console.log(JSON.stringify(true));
"""
            )
        )

    def test_first_manual_scene_uses_selected_style_without_replacing_saved_work(
        self,
    ) -> None:
        self.assertTrue(
            run_javascript(
                DOM
                + """
plan = {title:'Untitled video',mode:'math',scenes:[]};
selectedMode = 'anime';
let focusCount = 0;
$('scenes').lastElementChild = {querySelector:()=>({focus(){focusCount++;}})};
renderScenes = () => {};
markEdited = () => {};
addSceneToDraft();
assert.equal(plan.mode, 'anime');
assert.equal(draftBrief.mode, 'anime');
assert.equal(plan.scenes[0].visual, 'composition');
assert.deepEqual(plan.scenes[0].composition, {elements:[]});
assert.equal(previousDraft, false);
const retained = clone(plan.scenes[0]);
selectedMode = 'explainer';
addSceneToDraft();
assert.equal(plan.mode, 'anime');
assert.deepEqual(plan.scenes[0], retained);
assert.equal(focusCount, 2);
console.log(JSON.stringify(true));
"""
            )
        )

    def test_last_scene_can_be_removed_to_return_to_an_empty_draft(self) -> None:
        self.assertTrue(
            run_javascript(
                DOM
                + COMPOSITION
                + """
plan = validatePlan(custom);
previousDraft = true;
let focused = false;
$('addScene').focus = () => {focused=true;};
renderScenes = () => {};
markEdited = () => {};
busy = true;
removeScene(0);
assert.equal(plan.scenes.length, 1);
busy = false;
removeScene(0);
assert.deepEqual(plan.scenes, []);
assert.equal(selectedScene, 0);
assert.equal(previousDraft, false);
assert.equal($('draftContext').hidden, true);
assert.equal($('renderButton').disabled, true);
assert.equal(focused, true);
assert.deepEqual(validatePlan(plan, true).scenes, []);
console.log(JSON.stringify(true));
"""
            )
        )

    def test_failed_planning_on_fresh_draft_does_not_claim_previous_content(
        self,
    ) -> None:
        self.assertTrue(
            run_javascript(
                DOM
                + """
plan = {title:'Untitled video',mode:'math',scenes:[]};
draftOrigin = 'new';
setBusy = (value, kind) => {busy=value;busyKind=value ? kind : null;updateButtons();};
api = async () => {
  assert.equal(previousDraft, false);
  assert.equal($('draftContext').hidden, true);
  throw new Error('Provider unavailable');
};
(async () => {
  await planVideo();
  assert.equal(planningState, 'failed');
  assert.equal(previousDraft, false);
  assert.equal($('draftContext').hidden, true);
  assert.equal($('draftBadge').textContent, 'Your draft');
  assert.deepEqual(plan.scenes, []);
  assert.equal($('renderButton').disabled, true);
  console.log(JSON.stringify(true));
})().catch((error)=>{console.error(error);process.exitCode=1;});
"""
            )
        )

    def test_math_sketches_follow_supplied_content_and_missing_data_stays_blank(
        self,
    ) -> None:
        self.assertTrue(
            run_javascript(
                """
for (const visual of mathVisuals) {
  assert.equal(typeof art, 'undefined');
  assert.deepEqual(mathArtElements({visual,math:emptyMath(visual)}), []);
  assert.deepEqual(mathArtElements({visual}), []);
}
assert.deepEqual(mathArtElements({visual:'equation',math:{equations:['E = mc^2','F = ma']}}).map((element)=>element.text), ['E = mc^2','F = ma']);
const graph = mathArtElements({visual:'graph',math:{expression:'cos(x)',x_min:-3,x_max:3,y_min:-2,y_max:2}});
assert.deepEqual(graph.map((element)=>element.kind), ['line','line','text']);
assert.equal(graph[2].text, 'y = cos(x)');
const calculus = mathArtElements({visual:'calculus',math:{expression:'sin(x)',operation:'integral',x_min:-3,x_max:3,y_min:-2,y_max:2}});
assert.equal(calculus[2].text, 'integral: sin(x)');
const triangle = mathArtElements({visual:'geometry',math:{a:2,b:5}})[0].points;
assert.ok(Math.abs((triangle[2][1]-triangle[0][1])/(triangle[1][0]-triangle[0][0]) - 5/2) < 1e-10);
const vectors = mathArtElements({visual:'vectors',math:{ax:-2,ay:1,bx:3,by:-2}});
assert.deepEqual(vectors[0].points, [[0,0],[-2,1]]);
assert.deepEqual(vectors[1].points, [[-2,1],[1,-1]]);
assert.deepEqual(vectors[2].points, [[0,0],[1,-1]]);
const makeNode = (tag) => ({tag,children:[],textContent:'',innerHTML:'',setAttribute(){},
  append(...children){this.children.push(...children);},replaceChildren(...children){this.children=children;this.innerHTML='';}});
globalThis.document = {createElement:(tag)=>makeNode(tag),createElementNS:(_namespace,tag)=>makeNode(tag)};
const container = makeNode('div');
setSceneArt(container, {visual:'equation',math:{equations:[]}});
assert.equal(container.children[0].tag, 'span');
assert.equal(container.children[0].textContent, 'Add math content');
console.log(JSON.stringify(true));
"""
            )
        )

    def test_sketch_uses_supplied_geometry_and_literal_text(self) -> None:
        self.assertTrue(
            run_javascript(
                COMPOSITION
                + """
const makeNode = (tag) => ({tag,attributes:{},children:[],textContent:'',innerHTML:'',
  setAttribute(name,value){this.attributes[name]=value;},
  append(...children){this.children.push(...children);},
  replaceChildren(...children){this.children=children;this.innerHTML='';}
});
globalThis.document = {createElementNS:(_namespace,tag)=>makeNode(tag)};
const scene = validatePlan(custom).scenes[0];
scene.composition.elements[0].text = '<img src=x onerror=alert(1)>';
const container = makeNode('div');
setSceneArt(container, scene);
assert.equal(container.innerHTML, '');
assert.equal(container.children.length, 1);
const svg = container.children[0];
assert.deepEqual(svg.children.map((child)=>child.tag), ['text','text','rect','circle','line','line','polyline','polygon']);
assert.equal(svg.children[0].children[0].textContent, scene.composition.elements[0].text);
assert.equal(svg.children[2].attributes.width, '24');
assert.equal(svg.children[3].attributes.r, '7');
assert.match(compositionSummary(scene), /<img src=x onerror=alert\\(1\\)>/);
assert.match(compositionSummary(scene), /0–1.8s entrance/);
assert.match(compositionSummary(scene), /moves to \\(1, 2\\) 2.7–5.4s/);
console.log(JSON.stringify(true));
"""
            )
        )

    def test_music_is_editable_and_invalid_scores_block_rendering(self) -> None:
        self.assertTrue(
            run_javascript(
                COMPOSITION
                + """
plan = validatePlan(custom);
markEdited = () => {};
updateButtons = () => {};
const input = {value:'{"tempo":112,"chords":[[44,51],[47,54,59]]}',
  setCustomValidity(message){this.error=message;}};
const prior = JSON.stringify(plan);
editMusicScore(input);
assert.deepEqual(plan.music, {tempo:112,chords:[[44,51],[47,54,59]]});
assert.notEqual(JSON.stringify(plan), prior);
assert.equal(renderReadiness(), '');
input.value = '{"tempo":300,"chords":[[48]]}';
editMusicScore(input);
assert.match(renderReadiness(), /Music tempo/);
assert.equal(plan.music.tempo, 112);
input.value = '';
editMusicScore(input);
assert.equal('music' in plan, false);
assert.equal(renderReadiness(), '');
for (const invalid of [null,{}, {tempo:true,chords:[[48]]},
  {tempo:80,chords:[]},{tempo:80,chords:[[35]]},{tempo:80,chords:[[48.5]]},
  {tempo:80,chords:[[48]],file:'remote.mp3'}]) assert.throws(()=>validateMusic(invalid));
console.log(JSON.stringify(true));
"""
            )
        )

    def test_visual_and_music_edits_mark_the_previous_video_stale(self) -> None:
        self.assertTrue(
            run_javascript(
                COMPOSITION
                + """
const fields = {
  voiceEnabled:{checked:true},voice:{value:'Local voice'},
  musicEnabled:{checked:true},musicVolume:{value:'0.18'},quality:{value:'preview'},
  videoCaption:{textContent:''}
};
globalThis.document = {getElementById:(id)=>fields[id]};
plan = validatePlan(custom);
activeRenderId = 'reviewed-video';
renderedFingerprint = JSON.stringify({plan,options:renderOptions()});
markEdited = updateVideoCaption;
updateButtons = () => {};
const input = {value:JSON.stringify({elements:[{
  kind:'circle',radius:1.2,start:0.2,end:0.6
}]}),setCustomValidity(){}};
editComposition(input, plan.scenes[0]);
assert.match(fields.videoCaption.textContent, /^Previous render/);
renderedFingerprint = JSON.stringify({plan,options:renderOptions()});
updateVideoCaption();
assert.match(fields.videoCaption.textContent, /^Your rendered video/);
input.value = JSON.stringify({tempo:87,chords:[[40,47],[43,50]]});
editMusicScore(input);
assert.match(fields.videoCaption.textContent, /^Previous render/);
console.log(JSON.stringify(true));
"""
            )
        )


if __name__ == "__main__":
    unittest.main()
