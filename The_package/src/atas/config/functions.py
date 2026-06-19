"""
functions.py — Helper functions used as defaults in settings.py.
"""

from scipy.stats import qmc


def Poisson_distribution(lower_x, upper_x, lower_y, upper_y, radius=100,
                         ncanidates=7, optimization=None):
    """
    Generate evenly spread sample points within a bounding box using Poisson disk sampling.

    Points are spaced at least `radius` meters apart, giving better coverage than random sampling.
    Used to represent a neighborhood with multiple locations instead of a single centroid.

    Parameters:
        lower_x, upper_x: left and right x-coordinates (meters, EPSG:28992)
        lower_y, upper_y: bottom and top y-coordinates
        radius: minimum distance between any two points (meters)
        ncanidates: candidate positions to try before giving up on a new point
        optimization: optional scipy optimization strategy

    Returns:
        NumPy array of shape (n_points, 2) with [x, y] coordinates
    """

    # Normalize radius to unit square [0,1]^2, then scale back after sampling
    scale = max(upper_x - lower_x, upper_y - lower_y)
    radius_normalised = radius / scale

    # seed=42 keeps results deterministic across runs
    engine = qmc.PoissonDisk(
        d=2,
        radius=radius_normalised,
        ncandidates=ncanidates,
        optimization=optimization,
        seed=42,
    )

    sample_unit = engine.fill_space()
    sample_scaled = qmc.scale(sample_unit, [lower_x, lower_y], [upper_x, upper_y])

    return sample_scaled
