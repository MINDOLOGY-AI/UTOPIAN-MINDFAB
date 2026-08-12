from mind.D4T4STEPS.olmo2_1b_interp.utils import stream_to_text
from mind.D4T4STEPS.olmo2_1b_interp.config import TARGETS

stream_to_text(
    "arxiv",
    TARGETS["arxiv"],
    dataset_id="togethercomputer/RedPajama-Data-1T",
    config="arxiv",
    text_field="text",
)
