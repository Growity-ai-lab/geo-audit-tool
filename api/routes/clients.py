"""Client CRUD endpoints."""

from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from .. import auth, repository
from ..db import get_db
from ..schemas import ClientCreate, ClientOut, ClientUpdate

# All client endpoints require an authenticated user (shared-access model).
router = APIRouter(
    prefix="/clients",
    tags=["clients"],
    dependencies=[Depends(auth.get_current_user)],
)


@router.post("", response_model=ClientOut, status_code=status.HTTP_201_CREATED)
def create_client(data: ClientCreate, db: Session = Depends(get_db)) -> ClientOut:
    return repository.create_client(db, data)


@router.get("", response_model=List[ClientOut])
def list_clients(db: Session = Depends(get_db)) -> List[ClientOut]:
    return repository.list_clients(db)


@router.get("/{client_id}", response_model=ClientOut)
def get_client(client_id: str, db: Session = Depends(get_db)) -> ClientOut:
    client = repository.get_client(db, client_id)
    if client is None:
        raise HTTPException(status_code=404, detail="client not found")
    return client


@router.patch("/{client_id}", response_model=ClientOut)
def update_client(
    client_id: str, data: ClientUpdate, db: Session = Depends(get_db)
) -> ClientOut:
    client = repository.get_client(db, client_id)
    if client is None:
        raise HTTPException(status_code=404, detail="client not found")
    return repository.update_client(db, client, data)


@router.delete("/{client_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_client(client_id: str, db: Session = Depends(get_db)) -> None:
    client = repository.get_client(db, client_id)
    if client is None:
        raise HTTPException(status_code=404, detail="client not found")
    repository.delete_client(db, client)
