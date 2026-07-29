from pathlib import Path
import torch

PROJECT_ROOT = Path.cwd()
DATA_DIR = PROJECT_ROOT / "data" / "interp_journey" / "function_approximator"

DEFAULT_EPOCHS = 200
DEFAULT_LR = 1e-3
DEFAULT_BATCH_SIZE = 32
DEFAULT_DIMS = (2, 8, 8, 2)  # for 2d3d2d; pages override per task

DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
DTYPE = torch.float32
