"""HTTP error shape the Svelte client already understands (`kind` / `message` / `retryable`)."""

from fastapi import HTTPException


def app_error(
    status: int, kind: str, message: str, *, retryable: bool = False
) -> HTTPException:
    return HTTPException(
        status_code=status,
        detail={"kind": kind, "message": message, "retryable": retryable},
    )


def not_implemented(feature: str) -> HTTPException:
    return app_error(
        501,
        "NotImplemented",
        f"{feature} is not wired yet (milestone 1). "
        "Participant records stay in Qualtrics and will never be stored in this app.",
    )
