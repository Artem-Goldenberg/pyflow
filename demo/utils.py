from dataclasses import dataclass
from pathlib import Path
import pandas as pd


@dataclass(frozen=True)
class ChunkSpec:
    source: str
    chunk_index: int
    rows: pd.DataFrame

    @property
    def row_count(self) -> int:
        return len(self.rows)


def load_sentiment_dataset(dataset_dir: Path) -> pd.DataFrame:
    sources = (
        ("amazon", dataset_dir / "amazon_cells_labelled.txt"),
        ("imdb", dataset_dir / "imdb_labelled.txt"),
        ("yelp", dataset_dir / "yelp_labelled.txt"),
    )

    rows: list[dict[str, str | int]] = []
    for source, path in sources:
        with path.open("r", encoding="utf-8") as handle:
            for raw_line in handle:
                line = raw_line.rstrip("\n")
                if not line:
                    continue
                text, label_text = line.rsplit("\t", maxsplit=1)
                rows.append({"source": source, "text": text, "label": int(label_text)})

    dataset = pd.DataFrame(rows)
    source_sizes = dataset.groupby("source").size().to_dict()
    if source_sizes != {"amazon": 1000, "imdb": 1000, "yelp": 1000}:
        raise RuntimeError(f"Unexpected source sizes: {source_sizes}")
    dataset["row_id"] = dataset.index
    dataset["label_name"] = dataset["label"].map({1: "positive", 0: "negative"})
    return dataset[["row_id", "source", "label", "label_name", "text"]]


def build_chunks(dataset: pd.DataFrame, chunk_size: int) -> list[ChunkSpec]:
    chunks: list[ChunkSpec] = []
    for source, source_frame in dataset.groupby("source", sort=True):
        source_frame = source_frame.sort_values("row_id").reset_index(drop=True)
        for chunk_index, start in enumerate(range(0, len(source_frame), chunk_size)):
            rows = source_frame.iloc[start : start + chunk_size].copy()
            chunks.append(ChunkSpec(source=source, chunk_index=chunk_index, rows=rows))
    return chunks
