// LightGBM models in the browser: tree evaluation and exact SHAP values (TreeSHAP).
// The trees come from momofraud.web_export; TreeSHAP follows Lundberg et al. (2018), Algorithm 2,
// which is what LightGBM's own pred_contrib computes. Parity tests compare both to Python.

import { FEATURES } from "./features.js";

const leafOf = (tree, x) => {
  if (tree.f.length === 0) return 0;
  let node = 0;
  while (node >= 0) node = x[tree.f[node]] <= tree.t[node] ? tree.l[node] : tree.r[node];
  return ~node;
};

// -- TreeSHAP ---------------------------------------------------------------------------------------
// A path element: [featureIndex, zeroFraction, oneFraction, pweight]
function extendPath(path, depth, zero, one, feature) {
  path[depth] = [feature, zero, one, depth === 0 ? 1 : 0];
  for (let i = depth - 1; i >= 0; i--) {
    path[i + 1][3] += one * path[i][3] * (i + 1) / (depth + 1);
    path[i][3] = zero * path[i][3] * (depth - i) / (depth + 1);
  }
}

function unwindPath(path, depth, index) {
  const one = path[index][2], zero = path[index][1];
  let next = path[depth][3];
  for (let i = depth - 1; i >= 0; i--) {
    if (one !== 0) {
      const tmp = path[i][3];
      path[i][3] = next * (depth + 1) / ((i + 1) * one);
      next = tmp - path[i][3] * zero * (depth - i) / (depth + 1);
    } else {
      path[i][3] = path[i][3] * (depth + 1) / (zero * (depth - i));
    }
  }
  for (let i = index; i < depth; i++) {
    path[i][0] = path[i + 1][0]; path[i][1] = path[i + 1][1]; path[i][2] = path[i + 1][2];
  }
}

function unwoundPathSum(path, depth, index) {
  const one = path[index][2], zero = path[index][1];
  let next = path[depth][3], total = 0;
  for (let i = depth - 1; i >= 0; i--) {
    if (one !== 0) {
      const tmp = next * (depth + 1) / ((i + 1) * one);
      total += tmp;
      next = path[i][3] - tmp * zero * ((depth - i) / (depth + 1));
    } else {
      total += (path[i][3] / zero) / ((depth - i) / (depth + 1));
    }
  }
  return total;
}

function treeShap(tree, x, phi) {
  const cover = (node) => (node >= 0 ? tree.c[node] : tree.vc[~node]);
  const recurse = (node, parentPath, depth, zero, one, feature) => {
    const path = parentPath.slice(0, depth).map((e) => e.slice());
    extendPath(path, depth, zero, one, feature);
    if (node < 0) {
      const value = tree.v[~node];
      for (let i = 1; i <= depth; i++) {
        const w = unwoundPathSum(path, depth, i);
        phi[path[i][0]] += w * (path[i][2] - path[i][1]) * value;
      }
      return;
    }
    const split = tree.f[node];
    const hot = x[split] <= tree.t[node] ? tree.l[node] : tree.r[node];
    const cold = hot === tree.l[node] ? tree.r[node] : tree.l[node];
    const w = tree.c[node];
    let inZero = 1, inOne = 1, d = depth;
    let k = 0;
    for (; k <= d; k++) if (path[k][0] === split) break;
    if (k !== d + 1) {
      inZero = path[k][1]; inOne = path[k][2];
      unwindPath(path, d, k);
      d -= 1;
    }
    recurse(hot, path, d + 1, (cover(hot) / w) * inZero, inOne, split);
    recurse(cold, path, d + 1, (cover(cold) / w) * inZero, 0, split);
  };
  if (tree.f.length === 0) return;
  recurse(0, [], 0, 1, 1, -1);
}

// -- the model ------------------------------------------------------------------------------------
export class Model {
  constructor(json) {
    Object.assign(this, json);       // key, name, knows, features, trees, bias, thresholds, test
    this.columns = this.features.map((f) => FEATURES.indexOf(f));
    this.block = json.thresholds.block;
    this.review = json.thresholds.review;
  }

  // full: all 33 feature values (FEATURES order); returns this model's input vector
  input(full) { return this.columns.map((i) => full[i]); }

  raw(full) {
    const x = this.input(full);
    let sum = 0;
    for (const tree of this.trees) sum += tree.v[leafOf(tree, x)];
    return sum;
  }

  probability(full) { return 1 / (1 + Math.exp(-this.raw(full))); }

  // SHAP values in log-odds, one per *full* feature (zero for features the model doesn't use)
  explain(full) {
    const x = this.input(full);
    const phi = new Array(this.features.length).fill(0);
    for (const tree of this.trees) treeShap(tree, x, phi);
    const contributions = new Array(FEATURES.length).fill(0);
    this.columns.forEach((c, i) => { contributions[c] = phi[i]; });
    const raw = this.bias + phi.reduce((a, b) => a + b, 0);
    return { probability: 1 / (1 + Math.exp(-raw)), raw, bias: this.bias, contributions, modelPhi: phi };
  }

  decide(p) { return p >= this.block ? "block" : p >= this.review ? "review" : "approve"; }
}

export async function loadModel(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`could not load ${url}`);
  return new Model(await res.json());
}
