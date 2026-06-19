import networkx as nx
import osmnx as ox
# print(ox.__version__)

Name = "groningen"

# Not entirely sure why we do this, but the tutorial says it is best
ox.settings.bidirectional_network_types += "drive"

# Create graph of all car-accessible roads in the city specified by 'Name'
G = ox.graph_from_place(f"{Name}, Netherlands", simplify=True, network_type="drive")

# Project the graph to the Coordinate Reference System (CRS) used by the CBS
G_proj = ox.project_graph(G, to_crs="epsg:28992", to_latlong=False)

# Plot the graph, show the plot and save at the Graphs directory
ox.plot_graph(G_proj, save=True, show=True, close=False, filepath=f'./Graphs/{Name}.png')

