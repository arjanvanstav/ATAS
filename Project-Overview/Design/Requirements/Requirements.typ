/*
  This file describes the basic usage we expect from the python package.
  The usage should be separated in different functionalities we want.
*/

= Requirements
== Pre-simulation methods

=== Initialization with datafiles
The package should allow the Initialization of new datasets (provided they have the same form)
One should be able to initialize a new simulation with a csv and geopackage.
This should be done by dictating the path to these files.

=== return available cities
As it might not be known what local_authority's are available it should be possible to get a list of all available cities mentioned in the datafile.

=== Choose a city (can be added as parameters for simulation methods)
To have more specific research possibilities, and to limit simulation time, the simulation should always be city/local_authority (gemeente) specific. \

== simulation methods
=== Simulating transit distance after a single street transformation
This simulation should obtain the fraction of car-accessible road to transform into pedestrian area.\ 
Then it should estimate the location of the new transit points. \
Doing so it should calculate the new distance to those transit points for every neighborhood (buurt).\
Then it should divide the new distance by the amount of people living in that neighborhood of a certain demographic group. This should be done for every demographic group. The results should be added to a total. This would result in the average increase in distance for every demographic group. \
The parameters should include the demographic groups to target (performance wise).\
The parameters should include any visualizing mechanics, like saving an image of the transformed map (before and after in a single image), and make the increase in distance per neighborhood visual with colors. Also maybe a bar diagram showing the results. The results should also be returned by the method in the form of a dictionary. \

=== Simulating transit distance for a series of street transformations
This simulation runs the single street transformation simulation for a series of fractions. The series of fractions is given as a range with a start, end and stepsize or number of steps.\
This is a separate method as it should be optimized to decrease the runtime. (Single API call for obtaining network, keep on working on created network that has already deleted some streets).\
Extra parameters should include demographic groups (performance).\
Whether or not to print the progress of the simulation to stdout (As large simulations could take a long time).\
Visualizing parameters. Visualizing would include: Saving a graph with the fraction (f) as the x-axis and the increased distance to transit as the y-axis, with different lines for every demographic group. The first fragmentation curve with the Largest Connected Component as the y-axis. The second fragmentation curve with the second Largest Connected Component as the y-axis.\

== Gui
=== The average experience using the Gui (dashboard)
+ Specify path to CBS data (csv and geopackage)
+ Import data (button that imports data from path to CBS)
+ Choose city to perform simulation on from the list of available cities
+ Choose from list of available simulations:
+ Choose simulation specific options
 - List the parameters of the simulation
+ Run simulation (button)
 - Show progress bar (as simulation can take a long time)
 - Show succeeded / failed
 - Allow for a dropdown that shows debug/detailed information to program state
