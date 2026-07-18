import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from retell.lib.webhook_auth import verify

from .config import Settings, get_settings

logger = logging.getLogger(__name__)


async def verify_retell_signature(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> None:
    signature = request.headers.get("X-Retell-Signature")
    api_key_loaded = bool(
        settings.retell_api_key
        and settings.retell_api_key.get_secret_value()
    )
    signature_header_exists = bool(signature)
    logger.warning(
        "Temporary Retell auth diagnostic: path=%s method=%s "
        "retell_api_key_loaded=%s signature_header_exists=%s",
        request.url.path,
        request.method,
        api_key_loaded,
        signature_header_exists,
    )

    if not signature or settings.retell_api_key is None:
        failed_check = (
            "missing_signature_header"
            if not signature
            else "retell_api_key_not_configured"
        )
        logger.warning(
            "Temporary Retell auth failure: failed_check=%s "
            "exception_type=None exception_message=None",
            failed_check,
        )
        raise HTTPException(status_code=401, detail="Unauthorized")

    raw_body = (await request.body()).decode("utf-8")
    api_key = settings.retell_api_key.get_secret_value()
    verifier_raised_exception = False
    try:
        is_valid = verify(
            raw_body,
            api_key,
            signature,
        )
    except Exception as exc:
        verifier_raised_exception = True
        logger.warning(
            "Temporary Retell auth failure: "
            "failed_check=signature_verifier_exception "
            "exception_type=%s exception_message=%s",
            type(exc).__name__,
            str(exc),
        )
        is_valid = False

    if not is_valid:
        if not verifier_raised_exception:
            logger.warning(
                "Temporary Retell auth failure: "
                "failed_check=signature_validation_returned_false "
                "exception_type=None exception_message=None"
            )
        raise HTTPException(status_code=401, detail="Unauthorized")

    logger.warning(
        "Temporary Retell auth diagnostic: authentication_result=success"
    )


router = APIRouter(
    prefix="/retell",
    dependencies=[Depends(verify_retell_signature)],
)
