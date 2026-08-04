from mind.D4T4STEPS.download_scripts.interp_dataset.utils import stream_to_text
from mind.D4T4STEPS.config import TARGETS

stream_to_text(
    "openwebmath",
    TARGETS["openwebmath"],
    dataset_id="open-web-math/open-web-math",
    text_field="text",
)
