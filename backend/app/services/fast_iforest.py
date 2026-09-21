"""Exact, vectorised IsolationForest.score_samples for one row.

sklearn walks its 200 trees one by one in Python (~19 ms per row). Here every tree is packed into flat node arrays and
all trees are walked at once, one level per numpy step (~0.3 ms). The arithmetic mirrors sklearn exactly:
float32 inputs compared against float64 thresholds, depth + c(n_leaf) - 1 per tree, 2 ** (-mean_depth / c(max_samples)).
`verified_against` checks equality with sklearn at load; callers fall back to sklearn if it fails.
"""

import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.ensemble._iforest import _average_path_length


class FastIsolationForest:
    def __init__(self, forest: IsolationForest) -> None:
        lefts, rights, feats, thresholds, leaf_values, roots = [], [], [], [], [], []
        offset = 0
        max_depth = 0
        for est, est_features in zip(forest.estimators_, forest.estimators_features_, strict=True):
            t = est.tree_
            n = t.node_count
            depth = t.compute_node_depths() if hasattr(t, "compute_node_depths") else _node_depths(t)
            is_leaf = t.children_left == -1
            roots.append(offset)
            lefts.append(np.where(is_leaf, -1, t.children_left + offset))
            rights.append(np.where(is_leaf, -1, t.children_right + offset))
            feats.append(np.where(is_leaf, 0, np.asarray(est_features)[np.maximum(t.feature, 0)]))
            thresholds.append(t.threshold)
            leaf_values.append(depth + _average_path_length(t.n_node_samples) - 1.0)
            max_depth = max(max_depth, int(depth.max()))
            offset += n
        self.left = np.concatenate(lefts)
        self.right = np.concatenate(rights)
        self.feature = np.concatenate(feats)
        self.threshold = np.concatenate(thresholds)
        self.leaf_value = np.concatenate(leaf_values)
        self.roots = np.asarray(roots)
        self.max_depth = max_depth
        self.denominator = len(forest.estimators_) * _average_path_length([forest._max_samples])[0]

    def score_samples_row(self, x: np.ndarray) -> float:
        """sklearn-compatible score_samples for one row (higher = more normal, as in sklearn)."""
        xv = np.asarray(x, dtype=np.float32).astype(np.float64)  # sklearn validates X as float32
        nodes = self.roots
        for _ in range(self.max_depth):
            left = self.left[nodes]
            internal = left != -1
            if not internal.any():
                break
            go_left = xv[self.feature[nodes]] <= self.threshold[nodes]
            nodes = np.where(internal, np.where(go_left, left, self.right[nodes]), nodes)
        depths = self.leaf_value[nodes].sum()
        return float(-(2.0 ** (-depths / self.denominator)))

    def verified_against(self, forest: IsolationForest, n_features: int, seed: int = 0) -> bool:
        rng = np.random.default_rng(seed)
        X = rng.normal(0, 1, (64, n_features)) * rng.choice([1, 10, 1000], (64, n_features))
        expected = forest.score_samples(X)
        got = np.array([self.score_samples_row(row) for row in X])
        return bool(np.allclose(got, expected, rtol=1e-12, atol=1e-12))


def _node_depths(t) -> np.ndarray:
    depth = np.zeros(t.node_count)
    depth[0] = 1.0
    for i in range(t.node_count):  # parents precede children in sklearn's node order
        if t.children_left[i] != -1:
            depth[t.children_left[i]] = depth[t.children_right[i]] = depth[i] + 1
    return depth
