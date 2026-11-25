"""ORM-free template size limits shared by template validation and the AI draft cap.

``ai.schemas.MAX_DRAFT_ACTIONS`` is derived from ``MAX_TEMPLATE_BLOCKS``, so a
draft can always return every block of a full template (issue #222).
"""

MAX_TEMPLATE_BLOCKS = 50
