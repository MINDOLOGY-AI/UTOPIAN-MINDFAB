from mind.D4T4STEPS.download_scripts.interp_dataset.utils import stream_to_text
from mind.D4T4STEPS.config import TARGETS

stream_to_text(
    "wikipedia_en",
    TARGETS["wikipedia_en"],
    dataset_id="wikimedia/wikipedia",
    config="20231101.en",
    text_field="text",
)
