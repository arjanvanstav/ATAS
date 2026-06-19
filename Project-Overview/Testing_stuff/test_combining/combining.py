import duckdb as db
import networkx as nx
import osmnx as ox
import pandas as pd

CITY = "Groningen"
CSV = "kwb2025.csv"
GEOM = "kwb2025.gpkg"


def main():
    G = get_graph(CITY)
    kwb = get_kwb_city(CITY, CSV, GEOM)
    kwb.to_csv("result.csv")
    spatial_join(G, kwb)


def spatial_join(G:nx.MultiDiGraph, kwb:pd.DataFrame):
    """
        Convert graph into a pd.DataFrame using graph_to_gdfs().
        Then join the two dataframes to analyze the needed data.
    """
    pass


def get_kwb_city(city:str, csv:str, geodata:str):
    """
        Returns:
            A single pandas DataFrame containing the merged data files of the CBS
        Parameters:
            city: a city name of a city in the Netherlands, the name should be in Dutch.
            csv: The path to the csv containing the 'kerncijfers-wijken-en-buurten' from the CBS.
                The format should be the same as in 2025.
            geodata: The path to the geodata containing the 'wijk-en-buurtkaart' from the CBS.
                The format should be the same as in 2025.
    """
    db.sql("INSTALL spatial;")
    db.sql("LOAD spatial;")
    quiry = f"""
        SELECT g.buurtcode, c.regio, c.a_man, c.a_vrouw, g.geom
        FROM read_csv('{csv}') c JOIN ST_Read('{geodata}') g ON c.gwb_code = g.buurtcode
        WHERE c.gm_naam='{city}'
        """
    return db.sql(quiry).df()



def get_graph(city:str, save=False, save_dir="Graphs/"):
    """
        Returns: 
            projected(epsg:28992) osmnx graph of given city. Only car-accessible roads.
        Parameters:
            city: a city name of a city in the Netherlands, the name should be in Dutch.
            save: If true: saves a image of the graph. Default: False
            save_dir: The directory to save the image of the graph, if save is true. Default: 'Graphs/'
    """
    ox.settings.bidirectional_network_types += "drive"
    G = ox.graph_from_place(f"{city}, Netherlands", simplify=True, network_type="drive")
    G_proj = ox.project_graph(G, to_crs="epsg:28992", to_latlong=False)
    ox.plot_graph(G_proj, save=save, show=False, close=True, filepath=f'{save_dir}{city}.png')
    return G_proj

if __name__ == "__main__":
    main()
