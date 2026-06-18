# context/selector.py
"""Context selector — selects items by priority, drops secret/temp, enforces budget."""

from context.schemas import ContextItem, ContextBudget


def select_context_items(items: list, intent: str = "", capability_id: str = "",
                         budget: ContextBudget = None) -> tuple:
    budget = budget or ContextBudget()
    warnings = []
    selected = []

    # Drop secret and temp immediately
    for item in items:
        if item.sensitivity == "secret" or item.scope == "temp":
            warnings.append(f"Dropped {item.item_type}:{item.item_id} ({item.sensitivity}/{item.scope})")
            continue
        selected.append(item)

    # Sort by priority (low first), then by recency
    selected.sort(key=lambda i: (i.priority, -i.token_estimate or 0))

    # Truncate by max_items
    if len(selected) > budget.max_items:
        dropped = selected[budget.max_items:]
        selected = selected[:budget.max_items]
        for d in dropped:
            warnings.append(f"Truncated {d.item_type}:{d.item_id} (over max_items={budget.max_items})")

    return selected, warnings
