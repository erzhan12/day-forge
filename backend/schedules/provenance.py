"""Server-authenticated origin for blocks reconstructed by the Undo endpoint."""

from django.core import signing

from schedules.models import TimeBlock

_SALT = "schedules.timeblock.restore-origin.v1"


def restore_proof(block: TimeBlock) -> str:
    # Sign only stable identity and title. Changes to time/category/completion
    # must not discard the import classification during Undo.
    return signing.Signer(salt=_SALT).sign_object(
        [block.schedule_id, block.id, block.title, block.origin]
    )


def origin_from_restore_proof(
    proof: str, schedule_id: int, block_id: int, title: str
) -> str | None:
    try:
        signed_schedule, signed_block_id, signed_title, origin = signing.Signer(
            salt=_SALT
        ).unsign_object(proof)
    except (signing.BadSignature, ValueError, TypeError):
        return None
    if (
        signed_schedule != schedule_id
        or block_id != signed_block_id
        or signed_title != title
        or origin not in TimeBlock.Origin.values
    ):
        return None
    return origin
