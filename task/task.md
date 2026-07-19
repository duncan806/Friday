# First experimental task (spec §10)

A CLI tool that takes a CSV file and answers natural-language questions.

You (the user) must open real CSV files with this tool, ask real questions,
and receive real answers. For example:

- From a sales CSV: "What is the total revenue for March?"
- From an employee roster CSV: "How many people are in each department?"
- From a log CSV: "What is the most frequent error type?"

The surface is clear (a CLI interface), blockages are observable (failing
while answering real questions on real CSVs), and the build cycle is short.
