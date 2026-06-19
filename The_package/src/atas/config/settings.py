"""
settings.py — Global config for the ATAS package.

All settings live in a single Settings dataclass shared across the package.
Usage:
    from atas.config.settings import get_settings
    settings = get_settings()
    settings.transit_max_edge_dist = 50
    print(settings.describe())
"""


from dataclasses import dataclass, field, fields
from typing import Callable
import numpy as np
import pandas as pd
import matplotlib.colors as mcolor


import atas.config.functions as functions

@dataclass
class Settings:
    example: int = field(
        default=0,
        metadata={"description": "Here the description"}
    )

    ###########################################################################
    ##################### Data importation settings ###########################
    ###########################################################################

    dataset_column_names: dict[str, str] = field (
        default_factory = lambda: {
            "id": "gwb_code",
            "regio": "regio",
            "gm_naam": "gm_naam",
            "recs": "recs",
            "pop": "a_inw",
            "male": "a_man",
            "female": "a_vrouw",
            "age_00_14": "a_00_14",
            "age_15_24": "a_15_24",
            "age_25_44": "a_25_44",
            "age_45_64": "a_45_64",
            "age_65_oo": "a_65_oo",
            "background_nl": "a_nl_all",
            "background_eu": "a_eur_al",
            "background_neu": "a_neu_al",
            "birthplace_nl": "a_geb_nl",
            "birthplace_eu": "a_geb_eu",
            "birthplace_neu": "a_geb_ne",
            "low_education": "a_opl_lg",
            "medium_education": "a_opl_md",
            "high_education": "a_opl_hg",
            "low_income": "p_ink_li",
            "high_income": "p_ink_hi",
            "risk_poverty": "p_ink_ar",
            "buurtcode": "buurtcode",
            "geom": "geom",
            "jobs": "a_bst_b"
        },
        metadata={"description": "Datasets of different years might have different"
                  "column names. Therefore this dictionary allows one to change"
                  "the column names of the dataset that are read by the package."
                  "The keys of the dictionary are the internal names of the data"
                  "used for the simulation. The values are the names of the corresponding"
                  "columns in the datasets (csv / geopackage). Non-existent columns"
                  "will result in an error. Empty columns will not result in an error."
                  "The geom and buurtcode come from the geopackage. All other columns"
                  "come from the csv."}
    )
    dataset_nullstring: list[str] = field (
        default_factory= lambda: ['.'],
        metadata={"description": "The character used for the NULL values in the csv files."
                  "Parameter to allow compatibility for datasets of different years."}
    )
    dataset_delim: str = field (
        default=',',
        metadata={"description": "The character used for the delimiter in the csv files."
                  "Parameter to allow compatibility for datasets of different years."}
    )
    dataset_decimal_separator: str = field (
        default=',',
        metadata={"description": "The separating character when reading floats from csv files."}
    )

    ###########################################################################
    ##################### Simulation settings #################################
    ###########################################################################

    neighborhood_distribution: Callable[[float, float, float, float], np.typing.NDArray[np.float64]] = field(
        default=functions.Poisson_distribution,
        metadata= {"description": "Given the upper and lower bounds of the "\
                    "bounding box of the neighborhood. Generate a list of "\
                    "coordinates of points representing the neighborhood."\
                    "Default uses scipy PoissonDisk distribution."\
                    "Import default with 'import atas.config.functions.Poisson_distribution'"\
                    "This function should return a numpy NDarray consisting of a list of points."\
                    "Points are lists of 2 elements in the form [x, y]"}
    )
    one_way_worth: float = field(
        default=0.7,
        metadata={"description": "The worth of a one way street, as compared to"\
                  "two way streets. The parameter is used for simulations that remove"\
                  "streets from driving networks. Setting this to zero would fully prioritize"\
                  "removing 2-way streets before 1-way streets"}
    )
    transit_max_edge_dist: int = field(
        default=30,
        metadata={"description": "This field determined the maximum distance in meters"\
                  "between a transit node, and the nearest edge."}
    )
    transit_max_pts_dist: int = field(
        default=30,
        metadata={"description": "This field determines the maximum distance in meters"\
                  "between a point in a neighborhood, and the nearest node in the pedestrian network."}
    )
    transit_max_move_dist: int = field(
        default=200,
        metadata={"description": "The maximum distance in meters between the previous"
                  "transit location, and the new moved transit location."}
    )
    max_dist_ped_transit: int = field(
        default=30,
        metadata={"description": "The maximum distance in meters between a transit station"
                  "and the pedestrian network. This is needed as nodes between the networks do"
                  "not nessisarily overlap. This constant acts as a buffer allowing the networks"
                  "to be merged, and obtain the nodes in the driving network accessible by the"
                  "pedestrian network."}
    )

    ###########################################################################
    ##################### Visualization settings ##############################
    ###########################################################################

    png_dpi: int = field(
        default=500,
        metadata={"description": "The dpi used when generating visualizations using the 'png' format."}
    )
    colormap: str = field(
        default='viridis_r',
        metadata={"description": "The colormap used to color the networks based on distance."
                  "Should be a valid matplotlib colormap"}
    )
    color_normalization: Callable[..., mcolor.Normalize] = field(
        default=mcolor.LogNorm,
        metadata={"description": ""}
    )
    legend_num_labels: int = field(
        default=10,
        metadata={"description": "The number of numbers to show on the colorbar legend when"\
                  "plotting the colored network."}
    )


    ###########################################################################
    ##################### Class methods #######################################
    ###########################################################################

    def describe(self):
        """Return all settings with their descriptions as a string."""
        lines = ''
        for f in fields(self):
            name = f.name
            value = getattr(self, name)
            description = f.metadata.get("description", "")
            default = f.default

            lines += f"{name} = {value} (default: {default})\nDescription: {description}\n\n"

        return lines

    def to_df(self) -> pd.DataFrame:
        rows = []
        for f in fields(self):
            rows.append({
                "name": f.name,
                "value": getattr(self, f.name),
                "default": f.default,
                "description": f.metadata.get("description", "")
            })
        return pd.DataFrame(rows)


_settings = Settings()


def get_settings() -> Settings:
    return _settings


def reset_settings():
    global _settings
    _settings = Settings()
