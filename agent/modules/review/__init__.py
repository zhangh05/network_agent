# agent/modules/review/__init__.py
"""Manual review flow capability (v0.9).

Lets the user inspect, accept, ignore, or annotate
manual_review_items attached to a translated_config artifact
(or any artifact that carries them in its metadata).

Critical safety:
- This module NEVER modifies the original translated_config content.
- This module NEVER generates a deployable_config.
- This module NEVER touches a real device.
- Review status / user_note are stored in a sidecar JSON file per
  artifact; the artifact's own metadata is read-only from this module.
"""
