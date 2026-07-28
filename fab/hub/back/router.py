from fastapi import APIRouter

router = APIRouter(prefix="/function_approximator", tags=["function_approximator"])


@router.get("/")
def root():
    # toy response; replace with real logic from interp/function_approximator/back
    return {"msg": "function approximator says hello"}
