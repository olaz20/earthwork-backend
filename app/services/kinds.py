"""Which enum member plays which role. The only place to change if your enum names differ."""
from app.schemas.common import BoundaryType, SurfaceType

INITIAL_KIND = SurfaceType.initial_topo
PROGRESS_KIND = SurfaceType.filled_topo
SITE_KIND = BoundaryType.site_boundary
FILL_KIND = BoundaryType.filled_boundary
