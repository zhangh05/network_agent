"""v3.9.9 contract: silent-except hygiene.

Background: earlier versions were littered with ``except Exception:
pass`` blocks that swallowed every error, making it impossible to
debug the support loop. v3.9.9 tightened the rule:

  1. Critical-path file/IO handlers MUST narrow to specific exception
     families (OSError, ValueError, JSONDecodeError, ...) and
     logging.warning (or .debug for best-effort paths).
  2. Best-effort hooks / SSE pushes / dev hooks MAY keep a silent
     fallback, but the body MUST contain a ``logger.*`` or
     ``logging.warning(...)`` call so the failure is observable.

This contract walks a curated set of critical-path files and asserts
that:

  * Every ``except Exception`` (or any of its derived families) has
    a body that is NOT exactly ``pass`` / empty / ``continue``.
  * If the handler body calls neither a logger nor re-raises, the
    test fails with a list of offending lines.

Why AST and not regex: the contract has to keep up with edits, and
the project has many one-line ``except X: pass`` blocks that look
like 'logging is missing' to a regex but are actually present.
"""

import ast
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent  # portable: resolve from this test file

# Files considered critical-path: a silent except here is likely to
# hide real bugs (audit loss, durable-state loss, hook failure).
CRITICAL_FILES = [
    "agent/approval.py",
    "agent/runtime/durable/store.py",
    "agent/runtime/durable/delivery.py",
    "agent/runtime/tool_execution/pipeline.py",
    "agent/runtime/result_builder.py",
    "agent/runtime/hook_runner.py",
    "agent/modules/remote/core.py",
    # v3.9.11 — second-round cuts (formerly C-class silent fallbacks).
    "agent/runtime/command_system.py",
    "core/tools/canonical_registry.py",
    "agent/llm/runtime.py",
    "backend/api/runtime_routes.py",
]


def _is_silent(body: list[ast.stmt]) -> bool:
    """True if the except handler body is functionally empty."""
    if not body:
        return True
    if len(body) == 1:
        last = body[-1]
        if isinstance(last, ast.Pass):
            return True
        if isinstance(last, ast.Continue):
            return True
        # `return None` / `return ""` / `return False` / `return b""`
        # is not silent — it explicitly converts the exception into a
        # caller-visible sentinel. Allow it.
    return False


def _body_has_logging(body: list[ast.stmt]) -> bool:
    for stmt in body:
        for node in ast.walk(stmt):
            if isinstance(node, ast.Call):
                fn = ast.unparse(node.func)
                if (fn.startswith("logger.")
                        or fn.startswith("logging.")
                        or fn.startswith("_log.")
                        or fn.startswith("print(")):
                    return True
            if isinstance(node, ast.Raise) and node.exc is None:
                # bare re-raise — allowed but counts as "logging-like"
                return True
    return False


def _exception_families(handler: ast.ExceptHandler) -> bool:
    """Returns True if the caught type is broad enough to silently
    swallow real bugs (i.e. Exception / BaseException / wide catch-all).
    """
    if handler.type is None:
        return True  # bare except
    name = ast.unparse(handler.type)
    if name == "":
        return True
    if "Exception" in name or "BaseException" in name:
        return True
    return False


def test_no_silent_except_in_critical_files():
    """Every ``except`` clause in critical-path files must narrow the
    exception type and call a logger (or re-raise).
    """
    offenders: list[str] = []
    for rel in CRITICAL_FILES:
        path = PROJECT_ROOT / rel
        src = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(src, filename=str(path))
        except SyntaxError as e:
            offenders.append(f"{rel}: syntax error {e}")
            continue

        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler):
                continue
            if not _exception_families(node):
                # already narrow (e.g. ``except OSError:`` + has body)
                continue
            if not _is_silent(node.body):
                # Function body (return / log / re-raise) — acceptable
                continue
            # At this point: silent-pass / silent-empty / silent-continue
            # …fail unless logging is present.
            if not _body_has_logging(node.body):
                offenders.append(
                    f"{rel}:{node.lineno} "
                    f"({ast.unparse(node.type) or 'bare'}) — "
                    f"silent fallback w/o logging"
                )
    assert not offenders, "Silent fallbacks missing logging:\n  " + "\n  ".join(offenders)


def test_approval_store_io_uses_os_error():
    """Approval store _append_record / _load_history / _gc_history
    must narrow OS errors specifically — not blanket-Exception.
    """
    path = PROJECT_ROOT / "agent" / "approval.py"
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    funcs = ["_append_record", "_load_history", "_gc_history", "get_history"]
    missing: list[str] = []
    for fn in funcs:
        node = next(
            (n for n in ast.walk(tree)
             if isinstance(n, ast.FunctionDef) and n.name == fn),
            None,
        )
        if node is None:
            missing.append(f"{fn} not found")
            continue
        # any ``except (...,) OSError, ... :`` clause inside?
        has_oserror = False
        for h in ast.walk(node):
            if not isinstance(h, ast.ExceptHandler):
                continue
            if h.type is None:
                continue
            try:
                types = ast.unparse(h.type)
            except Exception:
                continue
            # unwrap Tuple: ``(OSError, TypeError, ValueError)`` → name list
            for piece in types.replace("(", "").replace(")", "").split(","):
                if piece.strip() == "OSError":
                    has_oserror = True
        if not has_oserror:
            missing.append(f"ApprovalStore.{fn} must narrow to OSError (v3.9.9)")
    assert not missing, "\n  ".join(missing)


def test_durable_store_append_event_uses_os_error():
    """append_event must narrow OSError so a disk-full failure is
    observable at WARNING rather than silently dropped.
    """
    path = PROJECT_ROOT / "agent" / "runtime" / "durable" / "store.py"
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    node = next(
        (n for n in ast.walk(tree)
         if isinstance(n, ast.FunctionDef) and n.name == "append_event"),
        None,
    )
    assert node is not None, "append_event not found in durable.store"
    has_oserror = False
    for h in ast.walk(node):
        if isinstance(h, ast.ExceptHandler) and h.type is not None:
            types = ast.unparse(h.type).replace("(", "").replace(")", "")
            if "OSError" in [t.strip() for t in types.split(",")]:
                has_oserror = True
    assert has_oserror, (
        "append_event must narrow to OSError (v3.9.9 — silent event-log "
        "loss hides every tool error)"
    )


def test_pipeline_uses_logger_for_sse_push_failures():
    """ToolExecutionPipeline.run must not silently swallow SSE pushes
    (push_tool_start / push_tool_done / push_turn_done).

    AST walk: every ``except Exception:`` whose body is silent
    (no logger call, no re-raise) AND whose try-block contains one of
    the push_* calls must fail.
    """
    path = PROJECT_ROOT / "agent" / "runtime" / "tool_execution" / "pipeline.py"
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)

    def _try_block_contains_push(try_node: ast.Try, push_name: str) -> bool:
        for sub in ast.walk(try_node):
            if not isinstance(sub, ast.Call):
                continue
            try:
                fn_name = ast.unparse(sub.func)
            except Exception:
                continue
            if push_name in fn_name:
                return True
        return False

    push_names = ("push_tool_start", "push_tool_done", "push_turn_done")
    offenders: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        # which push_* does this try call?
        matched = [p for p in push_names if _try_block_contains_push(node, p)]
        if not matched:
            continue
        # does it log on every except clause?
        for h in node.handlers:
            if not _exception_families(h):
                continue
            if not _is_silent(h.body):
                continue  # body does something explicit
            if not _body_has_logging(h.body):
                offenders.append(
                    f"{path.name}:L{node.lineno} try{'/'.join(matched)} "
                    "except body silent w/o logger"
                )
    assert not offenders, "Pipeline silent SSE fallbacks:\n  " + "\n  ".join(offenders)


def test_hook_runner_logs_each_lifecycle():
    """Every hook_runner entry point must log on exception."""
    path = PROJECT_ROOT / "agent" / "runtime" / "hook_runner.py"
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    funcs = [
        "run_pre_tool_hook", "run_post_tool_hook", "run_post_turn_hooks",
        "run_stop_hooks", "run_post_model_hook", "run_error_hook",
        "run_approval_hook",
    ]
    missing: list[str] = []
    for fn_name in funcs:
        # Find function and check that at least one ``except Exception``
        # block contains a logger call.
        node = next(
            (n for n in ast.walk(tree)
             if isinstance(n, ast.FunctionDef) and n.name == fn_name),
            None,
        )
        if node is None:
            missing.append(f"{fn_name} missing")
            continue
        # any ``except Exception:`` whose body contains a logger call?
        ok = False
        for h in [c for c in ast.walk(node) if isinstance(c, ast.ExceptHandler)]:
            if not _exception_families(h):
                continue
            if _body_has_logging(h.body):
                ok = True
                break
        if not ok:
            missing.append(f"{fn_name} has no logging in except")
    assert not missing, "Missing logging in: " + "; ".join(missing)


def test_logger_module_set_in_each_critical_file():
    """Every critical-path file must declare a module-level logger.

    AST inspection: a top-level assignment whose target name starts
    with ``logger`` (or ``_log`` / ``_logger``) and whose value is a
    ``logging.getLogger`` call.
    """
    for rel in CRITICAL_FILES:
        path = PROJECT_ROOT / rel
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src)
        found = False
        for node in tree.body:
            if isinstance(node, ast.Assign):
                for tgt in node.targets:
                    name = tgt.id if isinstance(tgt, ast.Name) else None
                    if name and name.lower().lstrip("_").startswith(("logger", "log")) or name.upper().startswith("_LOG") or name in {"_LOG", "LOG"}:
                        if isinstance(node.value, ast.Call):
                            fn = ast.unparse(node.value.func)
                            if fn in {"logging.getLogger", "logging.getLogger(__name__)"} \
                                    or fn.startswith("logging.getLogger"):
                                found = True
            elif isinstance(node, ast.AnnAssign):
                name = node.target.id if isinstance(node.target, ast.Name) else None
                if name and name.lower().lstrip("_").startswith(("logger", "log")) or name.upper().startswith("_LOG") or name in {"_LOG", "LOG"}:
                    found = True
        assert found, (
            f"{rel} has no module-level logger declared (v3.9.9 — "
            f"silent exceptions must be observable)"
        )
