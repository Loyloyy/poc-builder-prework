Implement `evaluate(expr: str) -> float` in `calc.py`: parse and evaluate an arithmetic
expression string and return its numeric value.

Support:
- binary operators `+` `-` `*` `/` and `^` (exponent)
- parentheses for grouping
- unary minus (e.g. `-3`, `2 * -3`)
- arbitrary whitespace

Precedence (highest to lowest): `^` (right-associative), then `*` `/`, then `+` `-`
(left-associative). Raise `ValueError` on malformed input (e.g. `"1 +"`, `"(1 + 2"`).

Pure stdlib. You may organize the code across modules as you see fit, as long as
`from calc import evaluate` works. Make `python -m pytest -q` pass.
