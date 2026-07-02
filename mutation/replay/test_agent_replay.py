"""Replay the committed agent discovered suites in process (Layer 3 headline).

Nothing is authored here. This module only imports the exact committed specs from
``generated_specs/`` so pytest collects them; ``conftest.py`` has already swapped
their transport to an in process PayFlow. Running this file under mutmut measures
the kill rate of the agent discovered rules, invariants, and metamorphic
relations with zero hand written test cases, which is the README headline claim.
"""

from __future__ import annotations

# The RuleBasedStateMachine TestCase (rules + invariants).
from payflow_spec import TestGeneratedMachine  # noqa: F401

# Every metamorphic relation test the agent authored, imported dynamically. The
# agent names its own relations, so the generated function names vary run to run
# (test_split_refund_mr5, test_reorder_independent_mr2, and so on); binding by a
# fixed name list would break the replay every time discovery renames one. Pulling
# all test_* callables keeps the whole committed relation suite in the mutation
# sweep no matter what the agent called them.
import payflow_mr  # noqa: E402

for _name in [_n for _n in dir(payflow_mr) if _n.startswith("test_")]:
    globals()[_name] = getattr(payflow_mr, _name)
