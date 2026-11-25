"""Text feature: how well a company's own purpose text matches its industry code description.

Runs locally. Reads the local free-text table and the SN2025 code list, computes TF-IDF character
n-gram similarities, and writes numbers only. The text itself never leaves the laptop.
"""

from __future__ import annotations

import logging
import re

import pyarrow as pa

from foretaksrisiko.acquire.landing import Landing, ParquetBatchWriter, read_table
from foretaksrisiko.acquire.sampling import build_section_lookup

log = logging.getLogger(__name__)

TEXT_FEATURES_SCHEMA = pa.schema(
    [
        ("organisasjonsnummer", pa.string()),
        ("text_chars", pa.int32()),
        ("text_sim_own_code", pa.float64()),
        ("text_sim_best", pa.float64()),
        ("text_rank_own_code", pa.int32()),
        ("text_sim_section", pa.float64()),
    ]
)

PLACEHOLDER = "00.000"
_WS = re.compile(r"\s+")


def normalise(text: str | None) -> str:
    return _WS.sub(" ", (text or "").strip().lower())


def code_descriptions(items: list[dict]) -> dict[str, str]:
    """Description of every leaf code: its own name plus the names of its ancestors."""
    name = {it["code"]: it["name"] or "" for it in items}
    parent = {it["code"]: it.get("parent_code") for it in items}
    level = {it["code"]: int(it["level"]) for it in items}
    out: dict[str, str] = {}
    for code in items:
        c = code["code"]
        if level[c] < 5:
            continue
        parts = []
        current: str | None = c
        while current is not None and current in name:
            parts.append(name[current])
            current = parent.get(current)
        out[c] = normalise(" ".join(parts))
    return out


def build_text_features(landing: Landing, chunk_size: int = 20_000) -> dict:
    from sklearn.feature_extraction.text import TfidfVectorizer

    units = read_table(
        landing.root / "enheter", columns=["organisasjonsnummer", "naeringskode1"]
    ).to_pylist()
    texts = read_table(landing.root / "enheter_tekst").to_pylist()
    sn = read_table(landing.root / "klass" / "sn2025").to_pylist()
    descriptions = code_descriptions(sn)
    codes = sorted(descriptions)
    code_index = {c: i for i, c in enumerate(codes)}
    section_of = build_section_lookup(sn)
    sections = sorted({it["code"] for it in sn if int(it["level"]) == 1})
    section_text = {it["code"]: normalise(it["name"]) for it in sn if int(it["level"]) == 1}
    section_index = {sct: i for i, sct in enumerate(sections)}

    text_by_orgnr = {
        t["organisasjonsnummer"]: normalise(
            " ".join(x for x in (t["vedtektsfestet_formaal"], t["aktivitet"]) if x)
        )
        for t in texts
    }
    orgnrs = [u["organisasjonsnummer"] for u in units]
    company_texts = [text_by_orgnr.get(o, "") for o in orgnrs]
    own_codes = [u["naeringskode1"] for u in units]

    vectorizer = TfidfVectorizer(
        analyzer="char_wb", ngram_range=(3, 5), min_df=3, sublinear_tf=True
    )
    vectorizer.fit([descriptions[c] for c in codes] + [t for t in company_texts if t])
    code_matrix = vectorizer.transform([descriptions[c] for c in codes])
    section_matrix = vectorizer.transform([section_text[sct] for sct in sections])

    counts = {
        "companies": len(orgnrs),
        "with_text": sum(1 for t in company_texts if t),
        "with_own_code": 0,
    }
    with ParquetBatchWriter(landing.table_dir("text_features"), TEXT_FEATURES_SCHEMA) as writer:
        for start in range(0, len(orgnrs), chunk_size):
            chunk_texts = company_texts[start : start + chunk_size]
            sims = (vectorizer.transform(chunk_texts) @ code_matrix.T).toarray()
            sims_section = (vectorizer.transform(chunk_texts) @ section_matrix.T).toarray()
            for offset, text in enumerate(chunk_texts):
                i = start + offset
                row = {name: None for name in TEXT_FEATURES_SCHEMA.names}
                row["organisasjonsnummer"] = orgnrs[i]
                row["text_chars"] = len(text)
                if text:
                    best = float(sims[offset].max())
                    row["text_sim_best"] = best
                    code = own_codes[i]
                    if code and code != PLACEHOLDER and code in code_index:
                        counts["with_own_code"] += 1
                        own = float(sims[offset, code_index[code]])
                        row["text_sim_own_code"] = own
                        row["text_rank_own_code"] = int((sims[offset] > own).sum()) + 1
                        sct = section_of(code)
                        if sct in section_index:
                            row["text_sim_section"] = float(
                                sims_section[offset, section_index[sct]]
                            )
                writer.write(row)
            log.info(
                "text features: %d of %d companies",
                min(start + chunk_size, len(orgnrs)),
                len(orgnrs),
            )
    counts["codes"] = len(codes)
    counts["vocabulary"] = int(len(vectorizer.vocabulary_))
    landing.update_manifest("text_features", counts)
    log.info("text features done: %s", counts)
    return counts
