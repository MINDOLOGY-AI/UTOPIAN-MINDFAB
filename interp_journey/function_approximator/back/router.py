from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Literal

from interp_journey.function_approximator.back import (
    config,
    dataset,
    registry,
    trainer,
)

router = APIRouter(prefix="/function_approximator", tags=["function_approximator"])


class TrainRequest1d1d(BaseModel):
    task: Literal["1d1d"]
    grid: list[list[list[int]]]
    epochs: int = config.DEFAULT_EPOCHS
    lr: float = config.DEFAULT_LR
    batch_size: int = config.DEFAULT_BATCH_SIZE
    dims: tuple[int, ...] = (1, 16, 16, 1)


class TrainRequest2d3d(BaseModel):
    task: Literal["2d3d"]
    grid: list[list[list[int]]]
    epochs: int = config.DEFAULT_EPOCHS
    lr: float = config.DEFAULT_LR
    batch_size: int = config.DEFAULT_BATCH_SIZE
    dims: tuple[int, ...] = (2, 16, 16, 3)


class TrainRequest2d3d2d(BaseModel):
    task: Literal["2d3d2d"]
    inputs: list[tuple[float, float]]
    outputs: list[tuple[float, float]]
    epochs: int = config.DEFAULT_EPOCHS
    lr: float = config.DEFAULT_LR
    batch_size: int = config.DEFAULT_BATCH_SIZE
    dims: tuple[int, ...] = (2, 8, 8, 2)


TrainRequest = TrainRequest1d1d | TrainRequest2d3d | TrainRequest2d3d2d


@router.post("/train")
def train(req: TrainRequest):
    if req.task == "1d1d":
        x, y = dataset.grid_to_line_function(req.grid)
    elif req.task == "2d3d":
        x, y = dataset.grid_to_2d_rgb_samples(req.grid)
    elif req.task == "2d3d2d":
        x, y = dataset.pairs_to_2d3d2d(req.inputs, req.outputs)
    else:
        raise HTTPException(status_code=400, detail="unknown task")

    result = trainer.train_model(
        task=req.task,
        dims=req.dims,
        epochs=req.epochs,
        lr=req.lr,
        batch_size=req.batch_size,
        x=x,
        y=y,
    )

    model = result.pop("model")
    registry.register(result["session_id"], {**result, "model": model})

    return {
        "session_id": result["session_id"],
        "dims": result["dims"],
        "loss_curve": result["loss_curve"],
        "loss_image": f"/api/function_approximator/loss/{result['session_id']}",
        "final_loss": result["final_loss"],
    }


@router.get("/loss/{session_id}")
def get_loss_image(session_id: str):
    meta = registry.get(session_id)
    if meta is None:
        raise HTTPException(status_code=404, detail="session not found")
    from fastapi.responses import FileResponse
    return FileResponse(meta["loss_image_path"])


class PredictRequest(BaseModel):
    session_id: str
    x: list[list[float]]


@router.post("/predict")
def predict(req: PredictRequest):
    if registry.get(req.session_id) is None:
        raise HTTPException(status_code=404, detail="session not found")
    out = registry.predict(req.session_id, req.x)
    return {"y": out.tolist()}


class HyperplaneRequest(BaseModel):
    session_id: str
    layer: int  # 0 or 1
    neuron: int
    grid_res: int = 100


@router.post("/hyperplane")
def hyperplane(req: HyperplaneRequest):
    if registry.get(req.session_id) is None:
        raise HTTPException(status_code=404, detail="session not found")
    data = registry.hyperplane_sweep(req.session_id, req.layer, req.neuron, req.grid_res)
    return data


class NeuronWeightsRequest(BaseModel):
    session_id: str
    layer: Literal["encoder", "decoder"]
    index: int
    weights: tuple[float, float]
    bias: float | None = None


@router.post("/neuron_weights")
def set_neuron_weights(req: NeuronWeightsRequest):
    if registry.get(req.session_id) is None:
        raise HTTPException(status_code=404, detail="session not found")
    registry.set_neuron_weights(req.session_id, req.layer, req.index, list(req.weights), req.bias)
    return {"ok": True}


class DecoderBiasRequest(BaseModel):
    session_id: str
    index: int
    bias: float


@router.post("/decoder_bias")
def set_decoder_bias(req: DecoderBiasRequest):
    if registry.get(req.session_id) is None:
        raise HTTPException(status_code=404, detail="session not found")
    registry.set_decoder_bias(req.session_id, req.index, req.bias)
    return {"ok": True}


class LiteralNeuronsRequest(BaseModel):
    session_id: str


@router.post("/literal_neurons")
def literal_neurons(req: LiteralNeuronsRequest):
    if registry.get(req.session_id) is None:
        raise HTTPException(status_code=404, detail="session not found")
    return registry.literal_neurons(req.session_id)


class SpaceShiftRequest(BaseModel):
    session_id: str
    grid_res: int = 20


@router.post("/space_shift")
def space_shift(req: SpaceShiftRequest):
    if registry.get(req.session_id) is None:
        raise HTTPException(status_code=404, detail="session not found")
    return registry.space_shift(req.session_id, req.grid_res)


@router.delete("/session/{session_id}")
def delete_session(session_id: str):
    if registry.get(session_id) is None:
        raise HTTPException(status_code=404, detail="session not found")
    registry.delete(session_id)
    return {"ok": True}


@router.get("/")
def root():
    return {"msg": "function approximator backend"}
