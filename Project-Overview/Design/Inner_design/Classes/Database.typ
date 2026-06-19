= Database
#image("../../Outer_design/database.svg")
== Data stored:
=== connection to database
This is the link to the 'in memory' database. It is easy to have the database written to a specific file, but this shouldn't be necessary, and only creates overhead.

== Methods
=== \_\_init()
+ Creates a connection to the new database (self.conn).\
+ Loads spatial extension
+ Creates and initializes table CBS with csv and geopackage (see picture)

=== to_csv()
- Debug Only
- Give csv representation of the database. One csv file for each of the tables.

=== get_cities()
- Returns a list of all local authorities (cities)

=== pre_process(city)
- Create the Neighborhood class using the given city
- Give 5 points to every neighborhood

=== load_network(nodes)
- Load the nodes of a OSMnx graph into the database, allowing data-analysis.


