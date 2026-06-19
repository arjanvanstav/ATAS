"""
Needed duckdb (pip install duckdb)
needed spatial extensions duck db
(pip install duckdb-extensions duckdb-extension-spatial)

"""

import duckdb as db

# Initialize spatial in the duckdb
db.sql("INSTALL spatial;")
db.sql("LOAD spatial;")

# All other stuff in table is not entered (empty / -99997)
query = """
    SELECT buurtcode, geom
    FROM ST_Read('wijkenbuurten_2025_v1.gpkg') 
    LIMIT 4
    """

geo = db.sql(query)

geo.to_csv("geomap.csv")
