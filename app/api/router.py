from fastapi import APIRouter

from app.api.routes import (  
    projects,
    surveys,
    computations,
    progress,
    reports,
    boundaries,

)

api_router = APIRouter()


api_router.include_router(projects.router)
api_router.include_router(boundaries.router)
api_router.include_router(surveys.router)
api_router.include_router(computations.router)
api_router.include_router(progress.router)
api_router.include_router(reports.router)