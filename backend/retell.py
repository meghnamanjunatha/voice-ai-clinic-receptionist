from fastapi import APIRouter, Depends, HTTPException, Request
from retell.lib.webhook_auth import verify

from .config import Settings, get_settings


async def verify_retell_signature(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> None:
    signature = request.headers.get("X-Retell-Signature")
    if not signature or settings.retell_api_key is None:
        raise HTTPException(status_code=401, detail="Unauthorized")

    raw_body = (await request.body()).decode("utf-8")
    api_key = settings.retell_api_key.get_secret_value()
    try:
        is_valid = verify(
            raw_body,
            api_key,
            signature,
        )
    except Exception:
        is_valid = False

    if not is_valid:
        raise HTTPException(status_code=401, detail="Unauthorized")


router = APIRouter(
    prefix="/retell",
    dependencies=[Depends(verify_retell_signature)],
)
