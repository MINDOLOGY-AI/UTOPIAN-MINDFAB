from mind.D4T4STEPS.download_scripts.interp_dataset.utils import stream_to_text
from mind.D4T4STEPS.config import TARGETS

stream_to_text(
    "arxiv",
    TARGETS["arxiv"],
    dataset_id="togethercomputer/RedPajama-Data-1T",
    config="arxiv",
    text_field="text",
)
