from enum import Enum


class SurfaceType(str, Enum):
    initial_topo = "initial_topo"
    filled_topo = "filled_topo"


class BoundaryType(str, Enum):
    site_boundary = "site_boundary"
    filled_boundary = "filled_boundary"

class LengthUnit(str, Enum):
    metre = "metre"
    foot = "foot"
    us_survey_foot = "us_survey_foot"