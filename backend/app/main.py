from contextlib import asynccontextmanager

from fastapi import FastAPI

from . import database


@asynccontextmanager
async def lifespan(app: FastAPI):
    await database.init()
    yield


app = FastAPI(title="Otaki", lifespan=lifespan)
