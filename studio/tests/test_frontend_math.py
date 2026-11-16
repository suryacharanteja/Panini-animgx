# SPDX-FileCopyrightText: 2026 Panini-Animgx contributors
# SPDX-License-Identifier: MIT
# ruff: noqa: PT009
"""Exercise the browser's math payloads against its helpers and the server contract."""

from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path
from typing import cast

from studio import server

NODE = shutil.which("node")
APP = Path(__file__).resolve().parents[1] / "web" / "app.js"
BOOTSTRAP = r"""
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const source = fs.readFileSync(process.argv[2], 'utf8');
const boundary = '$("briefForm").addEventListener';
assert.ok(source.includes(boundary), 'Find the browser event binding boundary');
vm.runInThisContext(source.slice(0, source.indexOf(boundary)));
const fixturePath = require('node:path').join(require('node:path').dirname(process.argv[2]), '../tests/frontend_fixtures.js');
vm.runInThisContext(fs.readFileSync(fixturePath, 'utf8'));
"""


def run_javascript(script: str) -> object:
    """Evaluate the actual browser helpers and return their JSON test result."""
    if NODE is None:
        raise unittest.SkipTest("Node is needed to test browser helpers")
    result = subprocess.run(
        [NODE, "-", str(APP)],
        input=BOOTSTRAP + script,
        text=True,
        capture_output=True,
        check=False,
        timeout=20,
        encoding="utf-8",
    )
    if result.returncode:
        raise AssertionError(result.stderr)
    return cast(object, json.loads(result.stdout))


@unittest.skipIf(NODE is None, "Node is needed to test browser helpers")
class FrontendMathTests(unittest.TestCase):
    """Keep math editing, saved drafts, and render payloads consistent."""

    def test_authored_math_fixtures_roundtrip_and_meet_server_contract(self) -> None:
        samples = cast(
            dict[str, dict[str, object]],
            run_javascript(
                """
for (const example of Object.values(mathExamples)) {
  assert.deepEqual(validatePlan(example), example);
  assert.deepEqual(validatePlan(JSON.parse(JSON.stringify(example))), example);
}
assert.equal(plan.mode, 'math');
assert.deepEqual(plan.scenes, []);
assert.equal(draftOrigin, 'new');
console.log(JSON.stringify(mathExamples));
"""
            ),
        )
        self.assertEqual(
            set(samples),
            {"pythagoras", "derivative", "sine", "vectors", "equation", "integral"},
        )
        for name, sample in samples.items():
            with self.subTest(name=name):
                result = server.validate_plan(sample)
                self.assertEqual(result["mode"], "math")
                self.assertEqual(result["scenes"], sample["scenes"])

    def test_custom_math_survives_render_payload_and_saved_draft(self) -> None:
        self.assertTrue(
            run_javascript(
                r"""
for (const visual of mathVisuals) {
  const scene = mathScene('Edited scene', 'Narration', visual, defaultMath(visual));
  if (visual === 'equation') scene.math.equations = ['y = \\sin(x)', 'x = 2'];
  if (visual === 'graph' || visual === 'calculus') scene.math.expression = 'cos(x)';
  if (visual === 'geometry') scene.math.a = 7;
  if (visual === 'vectors') scene.math.by = -3;
  const custom = {title:'Custom', mode:'math', scenes:[scene]};
  const payload = validatePlan(custom);
  assert.deepEqual(payload.scenes[0].math, scene.math);
  assert.deepEqual(validatePlan(JSON.parse(JSON.stringify(payload))), payload);
  const omitted = {...scene};
  delete omitted.math;
  assert.throws(() => validatePlan({...custom, scenes:[omitted]}), /Math settings/);
}
for (const mode of ['explainer', 'anime']) {
  assert.deepEqual(validatePlan(samples[mode]), samples[mode]);
  for (const visual of visuals) {
    const scene = {
      title:'Flexible visual', narration:'', visual, duration:6,
      background:'#101b2d', accent:'#75d8f7'
    };
    if (mathVisuals.has(visual)) scene.math = defaultMath(visual);
    if (visual === 'composition') scene.composition = {elements:[{
      kind:'text', text:'My content', start:0, end:0.25
    }]};
    assert.equal(validatePlan({title:'Mix', mode, scenes:[scene]}).scenes[0].visual, visual);
  }
}
console.log(JSON.stringify(true));
"""
            )
        )

    def test_invalid_dimensions_and_functions_do_not_form_render_payloads(self) -> None:
        self.assertTrue(
            run_javascript(
                """
const invalid = [
  ['equation', {equations:[]}],
  ['equation', {equations:Array(7).fill('x=1')}],
  ['equation', {equations:['x'.repeat(201)]}],
  ['equation', {equations:[' ']}],
  ['graph', {...defaultMath('graph'), expression:'__import__(x)'}],
  ['graph', {...defaultMath('graph'), expression:'x;alert(1)'}],
  ['graph', {...defaultMath('graph'), x_min:5, x_max:5}],
  ['graph', {...defaultMath('graph'), y_min:-21}],
  ['graph', {...defaultMath('graph'), x_max:Infinity}],
  ['graph', {...defaultMath('graph'), x_min:0, x_max:0.05}],
  ['calculus', {...defaultMath('calculus'), operation:'execute'}],
  ['calculus', {...defaultMath('calculus'), operation:'integral', y_min:1}],
  ['calculus', {...defaultMath('calculus'), operation:'integral', y_min:-10, y_max:-1}],
  ['geometry', {a:0,b:4}],
  ['geometry', {a:10001,b:4}],
  ['vectors', {ax:5,ay:0,bx:1,by:2}],
  ['vectors', {ax:0,ay:0,bx:true,by:2}],
];
for (const [visual, math] of invalid) {
  assert.throws(() => validatePlan({
    title:'Invalid', mode:'math', scenes:[mathScene('Math', '', visual, math)]
  }));
}
assert.deepEqual(validateMath('geometry', {a:5,b:12}), {a:5,b:12});
const scientific = {...defaultMath('graph'), expression:'1e-3 * x + 1E3'};
assert.equal(validateMath('graph', scientific).expression, scientific.expression);
const shortRange = {...defaultMath('graph'), x_min:1, x_max:1.1};
assert.equal(validateMath('graph', shortRange).x_max, 1.1);
for (const visual of ['orbit', 'process', 'bars', 'character', 'landscape']) {
  assert.throws(() => validatePlan({
    title:'Math needs math', mode:'math', scenes:[{
      title:'Generic', narration:'', visual, duration:6,
      background:'#101b2d', accent:'#75d8f7'
    }]
  }), /invalid words, timing, or visuals/);
}
console.log(JSON.stringify(true));
"""
            )
        )

    def test_math_edit_marks_previous_render_stale(self) -> None:
        self.assertTrue(
            run_javascript(
                """
const fields = {
  voiceEnabled: {checked:true}, voice: {value:'Local voice'},
  musicEnabled: {checked:true}, musicVolume: {value:'0.18'},
  quality: {value:'preview'}, videoCaption: {textContent:''}
};
globalThis.document = {getElementById: (id) => fields[id]};
plan = clone(mathExamples.derivative);
activeRenderId = 'rendered-math';
renderedFingerprint = JSON.stringify({plan, options:renderOptions()});
updateVideoCaption();
assert.match(fields.videoCaption.textContent, /^Your rendered video/);
plan.scenes[0].math.expression = 'cos(x)';
updateVideoCaption();
assert.match(fields.videoCaption.textContent, /^Previous render/);
console.log(JSON.stringify(true));
"""
            )
        )

    def test_equation_sketch_uses_text_for_user_input(self) -> None:
        self.assertTrue(
            run_javascript(
                """
const elements = new Map();
const makeElement = (tag) => ({
  tag,textContent:'',innerHTML:'',children:[],style:{setProperty(){}},hidden:false,
  setAttribute(){},append(...children){this.children.push(...children);},
  replaceChildren(...children){this.children=children;this.innerHTML='';}
});
globalThis.document = {
  getElementById(id) {
    if (!elements.has(id)) elements.set(id, makeElement('div'));
    return elements.get(id);
  },
  createElementNS:(_namespace,tag)=>makeElement(tag),
  createElement:(tag)=>makeElement(tag),
  querySelectorAll: () => []
};
const text = '<img src=x onerror=alert(1)>';
plan = {title:'Text', mode:'math', scenes:[mathScene('Equation', '', 'equation', {
  equations:[text, 'x = 2']
})]};
updateSketch();
assert.equal(elements.get('sketchMath').textContent, text + '\\n' + 'x = 2');
assert.equal(elements.get('sketchMath').innerHTML, '');
console.log(JSON.stringify(true));
"""
            )
        )


if __name__ == "__main__":
    unittest.main()
