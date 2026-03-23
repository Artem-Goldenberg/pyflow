"""Re-export the generated `models` registry.

`generate_models_from_provider(...)` writes the concrete registry to
`pyflow/_generated/models.py`. That generated module nests provider namespaces
directly inside `models` and also exposes a flat top-level model view.
"""

from __future__ import annotations

import importlib


models = importlib.import_module("pyflow._generated.models").models


__all__ = ["models"]
