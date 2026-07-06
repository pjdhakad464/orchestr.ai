"""Landing page feature module.

Isolated from the tool/dashboard pages: all landing content lives in
`content.py` (edit that file to change copy), the markup lives in
`app/templates/landing/`, and the styling in `app/static/landing/landing.css`.
Nothing here touches the in-app light design system or the API.
"""

from .content import LANDING

__all__ = ["LANDING"]
