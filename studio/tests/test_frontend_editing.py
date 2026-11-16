# SPDX-FileCopyrightText: 2026 Panini-Animgx contributors
# SPDX-License-Identifier: MIT
# ruff: noqa: PT009
"""Keep unfinished edits, scene selection, and preview navigation consistent."""

from __future__ import annotations

import unittest

from studio.tests.test_frontend_math import NODE, run_javascript
from studio.tests.test_frontend_projects import PROJECT_DOM


@unittest.skipIf(NODE is None, "Node is needed to test browser helpers")
class FrontendEditingTests(unittest.TestCase):
    """Exercise edits that previously reverted silently or stranded the preview."""

    def test_unfinished_json_and_duration_survive_saved_draft_reload(self) -> None:
        self.assertTrue(
            run_javascript(
                PROJECT_DOM
                + """
markEdited=()=>{};
renderScenes=()=>{};
const scene=plan.scenes[0];
const original=clone(plan);
const input=(value)=>({value,validity:{},setCustomValidity(){},setAttribute(){}});
editComposition(input('{"elements":['),scene);
editSceneDuration(input(''),scene);
editMusicScore(input('{"tempo":'));
const snapshot=clone(draftSnapshot());
assert.equal(snapshot.sceneEdits[0].composition,'{"elements":[');
assert.equal(snapshot.sceneEdits[0].duration,'');
assert.equal(snapshot.musicEdit,'{"tempo":');
assert.deepEqual(snapshot.plan,original);
assert.equal(restoreDraft(snapshot),true);
refreshPlan();
assert.equal(compositionEdits.get(plan.scenes[0]).text,'{"elements":[');
assert.equal(durationEdits.get(plan.scenes[0]),'');
assert.equal($('musicScore').value,'{"tempo":');
assert.match(renderReadiness(),/JSON music score/);
editMusicScore(input(''));
assert.match(renderReadiness(),/duration/);
editSceneDuration(input('12.5'),plan.scenes[0]);
assert.equal(plan.scenes[0].duration,12.5);
assert.match(renderReadiness(),/composition JSON/);
editComposition(input(JSON.stringify(original.scenes[0].composition)),plan.scenes[0]);
assert.equal(renderReadiness(),'');
assert.equal('sceneEdits' in draftSnapshot(),false);
assert.equal('musicEdit' in draftSnapshot(),false);
console.log(JSON.stringify(true));
"""
            )
        )

    def test_math_numbers_never_render_the_old_value_after_invalid_input(self) -> None:
        self.assertTrue(
            run_javascript(
                PROJECT_DOM
                + """
markEdited=()=>{};
plan=clone(mathExamples.pythagoras);
const scene=plan.scenes[0];
const input={value:'',validity:{valid:false},setAttribute(){}};
editMathValue(input,scene,'a',{number:true});
assert.equal(scene.math.a,'');
assert.match(renderReadiness(),/triangle sides/);
assert.equal(validatePlan(plan,true).scenes[0].math.a,'');
input.value='20000';
editMathValue(input,scene,'a',{number:true});
assert.equal(scene.math.a,20000);
assert.match(renderReadiness(),/triangle sides/);
assert.equal(validatePlan(plan,true).scenes[0].math.a,20000);
input.value='7.25';input.validity.valid=true;
editMathValue(input,scene,'a',{number:true});
assert.equal(scene.math.a,7.25);
assert.equal(renderReadiness(),'');
console.log(JSON.stringify(true));
"""
            )
        )

    def test_too_many_equation_lines_are_saved_until_corrected(self) -> None:
        self.assertTrue(
            run_javascript(
                PROJECT_DOM
                + r"""
markEdited=()=>{};
plan=clone(mathExamples.equation);
draftBrief={prompt:'My proof',mode:'math',duration:'30'};
const scene=plan.scenes[0];
const original=clone(scene.math.equations);
const input={value:Array(7).fill('x = 1').join('\n'),setCustomValidity(){},setAttribute(){}};
editMathValue(input,scene,'equations',{multiline:true});
assert.deepEqual(scene.math.equations,original);
assert.match(renderReadiness(),/1–6 equation lines/);
const snapshot=clone(draftSnapshot());
assert.equal(snapshot.sceneEdits[0].equations,input.value);
assert.equal(restoreDraft(snapshot),true);
assert.equal(equationEdits.get(plan.scenes[0]),input.value);
input.value='x = 5\ny = 8';
editMathValue(input,plan.scenes[0],'equations',{multiline:true});
assert.deepEqual(plan.scenes[0].math.equations,['x = 5','y = 8']);
assert.equal(equationEdits.has(plan.scenes[0]),false);
assert.equal(renderReadiness(),'');
console.log(JSON.stringify(true));
"""
            )
        )

    def test_out_of_range_duration_blocks_rendering_without_losing_input(self) -> None:
        self.assertTrue(
            run_javascript(
                PROJECT_DOM
                + """
markEdited=()=>{};
const scene=plan.scenes[0];
const original=scene.duration;
for(const value of ['2','21','1e999','']){
 editSceneDuration({value,setAttribute(){},validity:{}},scene);
 assert.equal(scene.duration,original);
 assert.equal(durationEdits.get(scene),value);
 assert.match(renderReadiness(),/duration/);
 assert.equal(draftSnapshot().sceneEdits[0].duration,value);
}
console.log(JSON.stringify(true));
"""
            )
        )

    def test_deleting_an_earlier_scene_keeps_the_selected_content(self) -> None:
        self.assertTrue(
            run_javascript(
                PROJECT_DOM
                + """
plan.scenes=[1,2,3].map(number=>({...clone(plan.scenes[0]),title:`Scene ${number}`}));
selectedScene=2;
markEdited=()=>{};renderScenes=()=>{};
$('addScene').focus=()=>{};
removeScene(0);
assert.equal(selectedScene,1);
assert.equal(plan.scenes[selectedScene].title,'Scene 3');
removeScene(1);
assert.equal(selectedScene,0);
assert.equal(plan.scenes[selectedScene].title,'Scene 2');
console.log(JSON.stringify(true));
"""
            )
        )

    def test_preview_can_return_to_the_rendered_video_without_reloading_it(
        self,
    ) -> None:
        self.assertTrue(
            run_javascript(
                PROJECT_DOM
                + """
activeRenderId='my-render';
$('video').src='/media/my-render/project.mp4';
renderedFingerprint=JSON.stringify({plan,options:renderOptions()});
showSketch();
assert.equal($('video').hidden,true);
assert.equal($('showVideo').hidden,false);
showRenderedVideo();
assert.equal($('video').hidden,false);
assert.equal($('sceneSketch').hidden,true);
assert.equal($('showSketch').hidden,false);
assert.equal($('showVideo').hidden,true);
assert.equal($('videoCaption').hidden,false);
assert.equal($('video').src,'/media/my-render/project.mp4');
assert.match($('videoCaption').textContent,/Your rendered video/);
showSketch();
assert.equal($('sceneSketch').hidden,false);
assert.equal($('showVideo').hidden,false);
console.log(JSON.stringify(true));
"""
            )
        )

    def test_blank_mode_and_overlong_drafts_restore_for_further_editing(self) -> None:
        self.assertTrue(
            run_javascript(
                PROJECT_DOM
                + """
plan={title:'Untitled video',mode:'math',scenes:[]};
selectedMode='explainer';
updateDraftContext();
assert.equal(plan.mode,'explainer');
assert.equal(draftBrief.mode,'explainer');
assert.equal(restoreDraft(clone(draftSnapshot())),true);
plan.scenes=Array(8).fill(null).map(()=>({...clone(samples.explainer.scenes[0]),duration:20}));
assert.throws(()=>validatePlan(plan),/120 seconds/);
assert.equal(validatePlan(plan,true).scenes.length,8);
assert.equal(restoreDraft(clone(draftSnapshot())),true);
assert.equal(plan.scenes.length,8);
assert.match(renderReadiness(),/120 seconds/);
console.log(JSON.stringify(true));
"""
            )
        )

    def test_validation_feedback_is_visible_and_exposed_to_assistive_technology(
        self,
    ) -> None:
        self.assertTrue(
            run_javascript(
                """
const attributes={};
const input={setCustomValidity(message){this.error=message;},
setAttribute(name,value){attributes[name]=value;}};
const feedback={textContent:'',hidden:true};
updateFieldError(input,feedback,'Fix the JSON');
assert.equal(attributes['aria-invalid'],'true');
assert.equal(input.error,'Fix the JSON');
assert.equal(feedback.textContent,'Fix the JSON');
assert.equal(feedback.hidden,false);
updateFieldError(input,feedback,'');
assert.equal(attributes['aria-invalid'],'false');
assert.equal(feedback.hidden,true);
console.log(JSON.stringify(true));
"""
            )
        )
