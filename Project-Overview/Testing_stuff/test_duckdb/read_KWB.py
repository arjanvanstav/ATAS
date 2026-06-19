import duckdb as db

query = """
SELECT gwb_code_8 as gemeente, a_man, a_vrouw
FROM read_csv('kwb2025.csv')
WHERE recs = 'Buurt'
LIMIT 10;
"""

kwb = db.sql(query)
print(kwb)

