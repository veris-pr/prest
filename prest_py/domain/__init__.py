"""Domain layer for the Python rewrite.

Holds identifier rules, permissions, query parameter semantics, and safe
request interpretation. No SQL assembly lives here — that stays in
``prest_py.postgres``.
"""