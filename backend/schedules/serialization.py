"""Schedule block payload shared by API and Inertia responses."""

from schedules.provenance import restore_proof


def serialize_block(block) -> dict:
    return {
        "id": block.id,
        "title": block.title,
        "start_time": block.start_time.strftime("%H:%M"),
        "end_time": block.end_time.strftime("%H:%M"),
        "category": block.category,
        "is_completed": block.is_completed,
        "sort_order": block.sort_order,
        "restore_proof": restore_proof(block),
    }


def serialize_schedule(schedule) -> dict:
    return {
        "id": schedule.id,
        "date": schedule.date.isoformat(),
        "status": schedule.status,
        "revision": schedule.revision,
    }


def serialize_schedule_snapshot(schedule, blocks) -> dict:
    """Serialize rows already captured together inside the write transaction."""
    return {
        "schedule": serialize_schedule(schedule),
        "blocks": [serialize_block(block) for block in blocks],
        "revision": schedule.revision,
    }
