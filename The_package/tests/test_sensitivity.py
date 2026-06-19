"""
test_sensitivity.py — Parameter sensitivity tests for the accessibility model.

Verifies that key model parameters produce the expected directional effects on
accessibility scores. All tests run without R5 (no GTFS / PBF data required).

Groups:
    Unit tests    — pure Python, use only synthetic DataFrames (fast, no I/O)
    Integration   — use the test dataset and OSMnx graph (cached after first run)
"""

import os
import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from atas.core._accessibility_score import _apply_gravity_model

CSV  = "tests/TestDatasets/test.csv"
GPKG = os.path.abspath("tests/TestDatasets/test.gpkg")


# =============================================================================
# Helpers
# =============================================================================

def _make_fixtures(n_origins=8, n_destinations=8, seed=42):
    """Synthetic (t_walk_df, t_travel_df, attractiveness_df) for unit tests."""
    rng = np.random.default_rng(seed)
    origins = [f"O{i}" for i in range(n_origins)]
    dests   = [f"D{j}" for j in range(n_destinations)]

    t_walk = pd.DataFrame({
        "neighborhood_id": origins,
        "t_walk_min":      rng.uniform(1, 10, n_origins),
    })

    rows = [
        {"from_id": o, "to_id": d, "travel_time": rng.uniform(5, 60)}
        for o in origins for d in dests
    ]
    t_travel = pd.DataFrame(rows)

    attractiveness = pd.DataFrame({
        "neighborhood_id": dests,
        "attractiveness":  rng.uniform(0.1, 1.0, n_destinations),
    })
    return t_walk, t_travel, attractiveness


def _db_setup():
    """Fresh database + network for integration tests (network graph is disk-cached)."""
    from atas.core._classes import Network, Database
    network  = Network("Amsterdam", store_in_file=True,
                       store_dir=os.path.expanduser("~/.percolation_cache/"))
    database = Database(CSV, GPKG)
    database.set_city("Amsterdam")
    database.load_network(network)
    database.obtain_features()
    database.pre_process()
    return network, database


# =============================================================================
# Unit tests — gravity model (_apply_gravity_model)
# =============================================================================

class TestGravityModelBeta:
    """Sensitivity of the gravity model to the distance-decay parameter beta."""

    def test_beta_zero_score_equals_attractiveness_sum(self):
        """
        When beta = 0, exp(-beta * t) = 1 for all OD pairs.
        Every origin receives the full sum of destination attractiveness values,
        regardless of travel time — so all origins score identically.
        """
        t_walk, t_travel, attractiveness = _make_fixtures()
        result = _apply_gravity_model(t_walk, t_travel, attractiveness, beta=0.0)

        expected = attractiveness["attractiveness"].sum()
        assert np.allclose(result["accessibility_score"], expected, rtol=1e-5), (
            f"With beta=0 all origins should score {expected:.4f}, "
            f"got: {result['accessibility_score'].values}"
        )

    def test_beta_higher_lowers_mean_score(self):
        """Higher beta penalises travel time more strongly → lower mean score."""
        t_walk, t_travel, attractiveness = _make_fixtures()
        betas = [0.0, 0.05, 0.1, 0.5, 1.0]

        means = [
            _apply_gravity_model(t_walk, t_travel, attractiveness, beta=b)
            ["accessibility_score"].mean()
            for b in betas
        ]

        for i in range(len(means) - 1):
            assert means[i] >= means[i + 1] - 1e-9, (
                f"Mean score should be non-increasing in beta. "
                f"beta={betas[i]}→{betas[i+1]}: {means[i]:.4f}→{means[i+1]:.4f}"
            )

    def test_beta_higher_increases_score_spread(self):
        """
        Higher beta → more discrimination between well- and poorly-connected origins.
        Origins with short walking time gain a relative advantage when decay is steep.
        """
        rng = np.random.default_rng(0)
        origins = [f"O{i}" for i in range(12)]
        dests   = [f"D{j}" for j in range(12)]

        # Spread t_walk widely so beta has a large effect
        t_walk = pd.DataFrame({
            "neighborhood_id": origins,
            "t_walk_min":      np.linspace(1, 30, 12),
        })
        t_travel = pd.DataFrame([
            {"from_id": o, "to_id": d, "travel_time": rng.uniform(5, 45)}
            for o in origins for d in dests
        ])
        attractiveness = pd.DataFrame({
            "neighborhood_id": dests,
            "attractiveness":  np.ones(12),
        })

        def cv(beta):
            r = _apply_gravity_model(t_walk, t_travel, attractiveness, beta=beta)
            s = r["accessibility_score"]
            return s.std() / s.mean()

        assert cv(1.0) > cv(0.01), (
            "Higher beta should produce greater relative score spread (CV)."
        )

    def test_rank_stability_across_moderate_beta_change(self):
        """
        Neighbourhood rankings should be broadly consistent across a 10-fold
        change in beta (Spearman ρ > 0.6).  A low correlation would indicate the
        model is rank-unstable for any reasonable beta choice.
        """
        t_walk, t_travel, attractiveness = _make_fixtures(n_origins=20, n_destinations=20, seed=7)

        r_low  = _apply_gravity_model(t_walk, t_travel, attractiveness, beta=0.05)
        r_high = _apply_gravity_model(t_walk, t_travel, attractiveness, beta=0.5)

        merged = r_low.merge(r_high, on="neighborhood_id", suffixes=("_lo", "_hi"))
        rho, _ = spearmanr(merged["accessibility_score_lo"], merged["accessibility_score_hi"])

        assert rho > 0.6, (
            f"Rank correlation across beta change too low: ρ = {rho:.3f}"
        )


class TestGravityModelAttractivenessScaling:
    """Sensitivity of the gravity model to attractiveness weights."""

    def test_doubling_attractiveness_doubles_scores(self):
        """Score is linear in attractiveness — doubling all weights doubles all scores."""
        t_walk, t_travel, attractiveness = _make_fixtures()

        attr_2x = attractiveness.copy()
        attr_2x["attractiveness"] *= 2

        r1 = _apply_gravity_model(t_walk, t_travel, attractiveness, beta=0.1)
        r2 = _apply_gravity_model(t_walk, t_travel, attr_2x, beta=0.1)

        r1 = r1.set_index("neighborhood_id")
        r2 = r2.set_index("neighborhood_id")
        ratios = r2["accessibility_score"] / r1["accessibility_score"]

        assert np.allclose(ratios, 2.0, rtol=1e-5), (
            f"Expected 2× scores; got ratios: {ratios.values}"
        )

    def test_unreachable_destination_lowers_origin_score(self):
        """
        An OD pair with NaN travel_time is dropped.
        The affected origin should score lower than when the destination is reachable.
        """
        t_walk, t_travel, attractiveness = _make_fixtures(n_origins=4, n_destinations=4)

        t_travel_nan = t_travel.copy()
        # Make one destination unreachable from one specific origin
        mask = (t_travel_nan["from_id"] == "O0") & (t_travel_nan["to_id"] == "D0")
        t_travel_nan.loc[mask, "travel_time"] = np.nan

        r_full = _apply_gravity_model(t_walk, t_travel,     attractiveness, beta=0.1)
        r_drop = _apply_gravity_model(t_walk, t_travel_nan, attractiveness, beta=0.1)

        score_full = r_full.set_index("neighborhood_id").loc["O0", "accessibility_score"]
        score_drop = r_drop.set_index("neighborhood_id").loc["O0", "accessibility_score"]

        assert score_drop < score_full, (
            f"Dropping a reachable destination should lower the origin's score. "
            f"full={score_full:.4f}, drop={score_drop:.4f}"
        )

    def test_missing_t_walk_uses_worst_case_penalty(self):
        """
        Origins absent from t_walk_df receive the maximum observed t_walk value
        (not zero), ensuring missing stops are penalised rather than rewarded.
        """
        t_walk, t_travel, attractiveness = _make_fixtures(n_origins=5)

        # Remove one origin from t_walk entirely — simulates an unconnected neighbourhood
        t_walk_partial = t_walk[t_walk["neighborhood_id"] != "O0"].copy()
        max_t_walk = t_walk_partial["t_walk_min"].max()

        r_full    = _apply_gravity_model(t_walk,         t_travel, attractiveness, beta=0.1)
        r_partial = _apply_gravity_model(t_walk_partial, t_travel, attractiveness, beta=0.1)

        r_full    = r_full.set_index("neighborhood_id")
        r_partial = r_partial.set_index("neighborhood_id")

        # Manually compute what score O0 should get with max_t_walk penalty
        t_travel_O0 = t_travel[t_travel["from_id"] == "O0"].copy()
        t_travel_O0 = t_travel_O0.merge(attractiveness, left_on="to_id",
                                         right_on="neighborhood_id")
        expected_score_O0 = (
            t_travel_O0["attractiveness"]
            * np.exp(-0.1 * (max_t_walk + t_travel_O0["travel_time"]))
        ).sum()

        assert np.isclose(r_partial.loc["O0", "accessibility_score"],
                          expected_score_O0, rtol=1e-5), (
            "Missing t_walk should use max_t_walk as penalty."
        )


# =============================================================================
# Integration tests — attractiveness (no R5 required)
# =============================================================================

class TestAttractivenessWeightSensitivity:
    """Sensitivity of compute_attractiveness to weight configurations."""

    def test_weight_zero_equals_omitting_component(self):
        """
        Setting a component's weight to 0 should produce the same scores as
        computing attractiveness without that component.
        """
        from atas.core._attractiveness import compute_attractiveness
        _, database = _db_setup()

        df_pop_only       = compute_attractiveness(database, weights={"population": 1.0})
        df_pop_jobs_zero  = compute_attractiveness(database, weights={"population": 1.0, "jobs": 0.0})

        merged = df_pop_only.merge(df_pop_jobs_zero,
                                   on="neighborhood_id", suffixes=("_a", "_b"))
        assert np.allclose(merged["attractiveness_a"], merged["attractiveness_b"], rtol=1e-6), (
            "weight=0 for a component should give the same result as omitting it."
        )

    def test_different_weights_change_output(self):
        """Population-only and jobs-only weight configs should produce different rankings."""
        from atas.core._attractiveness import compute_attractiveness
        _, database = _db_setup()

        df_pop  = compute_attractiveness(database, weights={"population": 1.0}, normalize_cols=True)
        df_jobs = compute_attractiveness(database, weights={"jobs": 1.0},       normalize_cols=True)

        merged = df_pop.merge(df_jobs, on="neighborhood_id", suffixes=("_pop", "_jobs"))
        rho, _ = spearmanr(merged["attractiveness_pop"], merged["attractiveness_jobs"])

        # They should not be identical (different data) but also not be orthogonal
        assert rho < 0.99, "Population-only and jobs-only configs should differ."
        assert rho > -0.5, "Population and jobs should not be strongly anti-correlated."

    def test_all_scores_are_non_negative(self):
        """Attractiveness scores are always >= 0 regardless of weight configuration."""
        from atas.core._attractiveness import compute_attractiveness
        _, database = _db_setup()

        for weights in [
            {"population": 1.0},
            {"jobs": 1.0},
            {"amenities": 1.0},
            {"population": 0.5, "jobs": 0.5, "amenities": 1.0},
        ]:
            df = compute_attractiveness(database, weights=weights, normalize_cols=True)
            assert (df["attractiveness"] >= 0).all(), (
                f"Negative attractiveness with weights={weights}"
            )

    def test_normalization_preserves_rank_ordering(self):
        """
        Enabling normalize_cols should not change the rank ordering of neighbourhoods.
        (Normalisation scales individual columns before summing, but min-max scaling
        is monotone within each column so ranks should be preserved for single-column
        configurations.)
        """
        from atas.core._attractiveness import compute_attractiveness
        _, database = _db_setup()

        df_raw  = compute_attractiveness(database, weights={"population": 1.0},
                                         normalize_cols=False)
        df_norm = compute_attractiveness(database, weights={"population": 1.0},
                                         normalize_cols=True)

        merged = df_raw.merge(df_norm, on="neighborhood_id", suffixes=("_raw", "_norm"))
        rho, _ = spearmanr(merged["attractiveness_raw"], merged["attractiveness_norm"])

        assert rho > 0.99, (
            f"Normalisation should not change rank ordering; ρ = {rho:.4f}"
        )


# =============================================================================
# Integration tests — t_walk (no R5 required)
# =============================================================================

class TestTWalkCoverageSensitivity:
    """Sensitivity of t_walk to the max_pts_dist tolerance."""

    def test_larger_max_pts_dist_covers_at_least_as_many_neighborhoods(self):
        """
        A more permissive point-to-node distance threshold should yield at least
        as many neighbourhoods with a valid t_walk result as a tight threshold.
        """
        from atas.core._classes import Network, Database
        from atas.core._t_walk import compute_t_walk

        def run(max_pts_dist):
            # Fresh Network per run: compute_t_walk adds transit nodes to the graph
            # in-memory, so reusing the same object across runs corrupts node attributes.
            # The graphml cache makes re-loading fast.
            net = Network("Amsterdam", store_in_file=True,
                          store_dir=os.path.expanduser("~/.percolation_cache/"))
            db = Database(CSV, GPKG)
            db.set_city("Amsterdam")
            db.load_network(net)
            db.obtain_features()
            db.pre_process()
            return compute_t_walk(db, net, max_pts_dist=max_pts_dist)

        df_tight  = run(max_pts_dist=5)
        df_normal = run(max_pts_dist=50)

        assert len(df_normal) >= len(df_tight), (
            f"max_pts_dist=50 should cover >= max_pts_dist=5. "
            f"Got: tight={len(df_tight)}, normal={len(df_normal)}"
        )

    def test_t_walk_results_are_positive(self):
        """Average walking distances must be strictly positive for all returned rows."""
        from atas.core._classes import Network, Database
        from atas.core._t_walk import compute_t_walk

        net = Network("Amsterdam", store_in_file=True,
                      store_dir=os.path.expanduser("~/.percolation_cache/"))
        db = Database(CSV, GPKG)
        db.set_city("Amsterdam")
        db.load_network(net)
        db.obtain_features()
        db.pre_process()

        df = compute_t_walk(db, net)

        assert len(df) > 0, "t_walk should return results for at least one neighbourhood."
        assert (df["avg_dist"] > 0).all(), (
            "All avg_dist values should be strictly positive."
        )
