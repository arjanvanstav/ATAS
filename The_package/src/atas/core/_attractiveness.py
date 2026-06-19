"""
_attractiveness.py — Compute an attractiveness score for each neighborhood.

Attractiveness represents how many "opportunities" a neighborhood offers as a destination
(jobs, residents, amenities). It is used as a weight in the gravity model.

Score = weighted sum of population, jobs, and amenities (each optionally normalized to 0–1).
"""



def compute_attractiveness(database, weights=None, normalize_cols=False):
    """
    Compute an attractiveness score for each neighborhood.

    Parameters:
        database: Database object (must have pre_process() run)
        weights: Dict mapping component name to weight. Supported: "population", "jobs", "amenities", "area".
                 Default: equal weight for population, jobs, and amenities.
        normalize_cols: If True, scale each component to [0, 1] before weighting so no
                        single component dominates because of its larger absolute values.

    Returns:
        DataFrame with columns: neighborhood_id, attractiveness
    """

    if weights is None:
        weights = {"population": 1.0, "jobs": 1.0, "amenities": 1.0}

    df = database.conn.sql("""
        SELECT
            id AS neighborhood_id,
            population,
            amenities,
            area,
            jobs
        FROM Neighborhoods
    """).df()

    # Min-max normalization: scale each column to [0, 1]
    if normalize_cols:
        for column_name in weights.keys():
            if column_name not in df.columns:
                raise ValueError(f"Unknown attractiveness component: '{column_name}'")

            col_min = df[column_name].min()
            col_max = df[column_name].max()

            if col_max > col_min:
                df[column_name] = (df[column_name] - col_min) / (col_max - col_min)
            else:
                # All values identical — this component has no discriminating power
                df[column_name] = 0.0

    df["attractiveness"] = 0.0
    for column_name, weight in weights.items():
        if column_name not in df.columns:
            raise ValueError(f"Unknown attractiveness component: '{column_name}'")
        df["attractiveness"] += weight * df[column_name]

    return df[["neighborhood_id", "attractiveness"]]
