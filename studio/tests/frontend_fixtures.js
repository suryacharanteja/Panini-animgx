// SPDX-FileCopyrightText: 2026 ndimensions.AI
// SPDX-License-Identifier: MIT
// Authored test fixtures only. Production Studio never loads these videos.
function defaultMath(visual) {
  const defaults = {
    equation: { equations: ["2x + 3 = 7", "2x = 4", "x = 2"] },
    graph: { expression: "x**2", x_min: -3, x_max: 3, y_min: -1, y_max: 9 },
    calculus: { expression: "x**2", x_min: -3, x_max: 3, y_min: -1, y_max: 9, operation: "derivative" },
    geometry: { a: 3, b: 4 },
    vectors: { ax: 2, ay: 1, bx: 1, by: 2 },
  };
  return clone(defaults[visual]);
}

const mathScene = (title, narration, visual, math, duration = 8) => ({ title, narration, visual, math, duration, background: "#101b2d", accent: "#75d8f7" });
const mathExamples = {
  pythagoras: {
    title: "Why a squared plus b squared equals c squared", mode: "math",
    scenes: [
      mathScene("Meet a right triangle", "A right triangle has two perpendicular sides, a and b. The longest side, opposite the right angle, is c.", "geometry", { a: 3, b: 4 }),
      mathScene("The Pythagorean relationship", "The square of the longest side equals the sum of the squares of the other two sides. With sides three and four, c squared is twenty five.", "equation", { equations: ["a^2 + b^2 = c^2", "3^2 + 4^2 = c^2", "9 + 16 = 25", "c = 5"] }, 10),
    ],
  },
  derivative: {
    title: "The derivative of x squared", mode: "math",
    scenes: [
      mathScene("A parabola", "The function x squared draws a parabola. Its steepness changes as we move along the curve.", "graph", defaultMath("graph")),
      mathScene("Follow the tangent", "The tangent shows the instantaneous slope. For x squared, that slope is two x. It is negative on the left and positive on the right.", "calculus", defaultMath("calculus"), 12),
      mathScene("From function to derivative", "Differentiation turns the curve into a rule for its slope: the derivative of x squared is two x.", "equation", { equations: ["f(x) = x^2", "f'(x) = 2x", "f'(1) = 2"] }),
    ],
  },
  sine: {
    title: "The shape of a sine wave", mode: "math",
    scenes: [
      mathScene("A repeating wave", "The sine function repeats smoothly. It reaches one at its crest, minus one at its trough, and crosses zero in between.", "graph", { expression: "sin(x)", x_min: -7, x_max: 7, y_min: -2, y_max: 2 }, 12),
      mathScene("Amplitude and period", "Its amplitude is one. A full cycle spans two pi radians. These patterns help us describe sound, light, and other waves.", "equation", { equations: ["y = \\sin(x)", "-1 \\leq \\sin(x) \\leq 1", "\\sin(x + 2\\pi) = \\sin(x)"] }, 10),
    ],
  },
  vectors: {
    title: "Adding vectors, one move at a time", mode: "math",
    scenes: [
      mathScene("Two directions", "The first vector moves two units right and one up. The second moves one right and two up. Place the second at the tip of the first.", "vectors", defaultMath("vectors"), 12),
      mathScene("Add the components", "Add horizontal components together, then vertical components together. The result moves three right and three up.", "equation", { equations: ["\\mathbf{a} = (2, 1)", "\\mathbf{b} = (1, 2)", "\\mathbf{a} + \\mathbf{b} = (3, 3)"] }, 10),
    ],
  },
  equation: {
    title: "Solve two x plus three equals seven", mode: "math",
    scenes: [
      mathScene("Keep the equation balanced", "To solve two x plus three equals seven, subtract three from both sides. That leaves two x equals four.", "equation", { equations: ["2x + 3 = 7", "2x + 3 - 3 = 7 - 3", "2x = 4"] }, 10),
      mathScene("Isolate x", "Divide both sides by two. We get x equals two. Substituting it back gives seven, so our solution works.", "equation", { equations: ["\\frac{2x}{2} = \\frac{4}{2}", "x = 2", "2(2) + 3 = 7"] }, 10),
    ],
  },
  integral: {
    title: "Area under x squared", mode: "math",
    scenes: [
      mathScene("Accumulate the area", "An integral adds up thin slices under a curve. Here we shade the area under x squared, from zero to two.", "calculus", { expression: "x**2", x_min: 0, x_max: 2, y_min: -1, y_max: 5, operation: "integral" }, 12),
      mathScene("The antiderivative", "An antiderivative of x squared is x cubed divided by three. Evaluating from zero to two gives eight thirds.", "equation", { equations: ["\\int_0^2 x^2 \\, dx", "\\left[\\frac{x^3}{3}\\right]_0^2", "\\frac{8}{3}"] }, 10),
    ],
  },
};

const samples = Object.fromEntries(['math','anime','explainer'].map(mode => [mode, mode === 'math' ? mathExamples.pythagoras : {title:'Authored test storyboard',mode,scenes:[{title:'Authored scene',narration:'Authored narration',visual:'composition',composition:{elements:[{kind:'text',text:'Authored visual',x:0,y:0,start:0,end:0.3}]},duration:8,background:'#162e40',accent:'#e2c883'}]}]));
