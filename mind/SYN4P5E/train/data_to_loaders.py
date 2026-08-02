# takes in bin, numpy data, makes a dataset and then dataloader.  

import os.path
import math

import numpy as np
import torch
from torch.utils.data import Dataset, DataLoader, Subset

# Deterministic per-epoch shuffle with fast resume by skipping batches.
# Use pin_memory to move data from RAM to VRAM faster during training.
# num_workers > 0 fetches multiple batches ahead in parapllel
# set to num_workers to (time_to_load / time_to_train). want training and loading rates to be equal  
def dataset_to_dataloader(
    dataset: Dataset,
    batch_size: int,
    cur_epoch: int = 0,
    start_batch: int = 0,
    num_workers: int = 2,
) -> DataLoader:
    seed = 21 # hard code seed = 21
    generator = torch.Generator().manual_seed(seed + cur_epoch)
    # use set generator to ensure the same results when we pause and resume
    indices = torch.randperm(len(dataset), generator=generator).tolist() #type: ignore  

    # fast skip. if normal iterate through skip then it's very slow because it actually loads everything.  
    start_idx = start_batch * batch_size
    if start_idx > 0:
        indices = indices[start_idx:]

    subset = Subset(dataset, indices)
    return DataLoader(
        subset,
        batch_size=batch_size,
        shuffle=False, # we already shuffled
        num_workers=num_workers,
        prefetch_factor=2, # how much each worker loads
        pin_memory=True, #  makes moving to vram faster
        drop_last=True, #  drops last incomplete batch.
    )

class NumpySupervisedDataset(Dataset):
    # x: (N, ...) and y: (N, ...) kept in RAM.
    def __init__(self, x: np.ndarray, y: np.ndarray):
        assert len(x) == len(y), f"x and y must have same length, got {len(x)} and {len(y)}"
        self.x = x
        self.y = y

    def __len__(self) -> int:
        return len(self.x)

    def __getitem__(self, idx: int):
        # workers read from the same numpy array; as_tensor handles both ndarray slices and scalars.
        return torch.as_tensor(self.x[idx]), torch.as_tensor(self.y[idx])


class BinUnsupervisedDataset(Dataset):
    # streams each sample from a flat binary file on disk.
    # shape includes N first, e.g. (N, seq_len) for token ids.
    def __init__(self, path: str, dtype: torch.dtype, shape: tuple[int, ...]):
        assert len(shape) >= 1, "shape must include the sample count dimension"

        self.path = path
        self.dtype = dtype
        self.shape = shape
        self.num_samples = shape[0]
        self.sample_shape = shape[1:]
        self.sample_numel = math.prod(self.sample_shape)
        self.sample_bytes = self.sample_numel * torch.empty(0, dtype=dtype).element_size()

        expected_size = self.num_samples * self.sample_bytes
        actual_size = os.path.getsize(path)
        assert actual_size == expected_size, (
            f"file size mismatch: {path} is {actual_size} bytes, expected {expected_size} "
            f"for shape {shape} and dtype {dtype}"
        )

    def __len__(self) -> int:
        return self.num_samples

    def __getitem__(self, idx: int):
        assert 0 <= idx < self.num_samples
        offset = idx * self.sample_bytes
        with open(self.path, "rb") as f:
            f.seek(offset)
            raw = f.read(self.sample_bytes)
        # frombuffer views immutable bytes, so clone into writable tensor memory.
        return torch.frombuffer(raw, dtype=self.dtype).reshape(self.sample_shape).clone()
