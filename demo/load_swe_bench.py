from datasets import load_dataset
import json
from pathlib import Path

wanted = {
    "sqlfluff__sqlfluff-2419",
    "sqlfluff__sqlfluff-1733",
}

ds = load_dataset("SWE-bench/SWE-bench_Lite", split="test")
rows = [row for row in ds if row["instance_id"] in wanted]

Path("swebench_cases.json").write_text(json.dumps(rows, indent=2))
print([row["instance_id"] for row in rows])
