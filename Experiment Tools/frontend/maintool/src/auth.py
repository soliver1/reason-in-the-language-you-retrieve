import logging
import secrets
import pathlib as pl
from time import sleep
from collections import namedtuple
from typing import Annotated

import bcrypt

from pydantic import BaseModel

import fastapi
from fastapi import APIRouter, HTTPException, Depends, Cookie, Form
from .storage import storage
from .helper import push_events

from .config import settings


class NotAuthenticatedException(Exception):
    pass


logger = logging.getLogger(__name__)


auth_router = APIRouter(prefix='/auth', tags=['auth'])


class Access(BaseModel):
    id: int
    user_id: int

    resource_type: str
    resource_id: str
    rights: str

    instigator_id: int | None

    @property
    def instigator(self):
        if self.instigator_id is None:
            return None

        with storage.get_db() as db:
            data = db.execute('SELECT username FROM users WHERE id=?', (self.instigator_id, )).fetchone()
            return data if data else None

    def editable(self):
        return self.rights in ('edit', )

    def __bool__(self):
        return self.rights in ('edit', 'readonly')


class User(BaseModel):
    id: int
    username: str
    password: str
    admin: bool = False

    def profile_image_path(self):
        return pl.Path(f'static/user_profile_pics/{self.id}_.png')

    def profile_image_placeholder_path(self):
        return pl.Path(f'static/user_profile_pics/{'user' if not self.admin else 'admin'}.png')

    def get_image_path(self):
        if (pl.Path('frontend') / self.profile_image_path()).exists():
            return self.profile_image_path()
        else:
            return self.profile_image_placeholder_path()

    def get_access_of_type(self, type_) -> list[Access]:
        with storage.get_db() as db:
            datas = db.execute('SELECT * FROM accessrights WHERE user_id=? AND resource_type=?', (self.id, type_,)).fetchall()
            return [Access(**d) for d in datas if d['rights'] in ('edit', 'readonly')]

    def get_access_resource(self, res_id)-> Access:
        with storage.get_db() as db:
            data = db.execute('SELECT * FROM accessrights WHERE user_id=? AND resource_id=?', (self.id, res_id,)).fetchone()
            if data:
                return Access(**data)
            else:
                return Access(**{'id': -1, 'user_id': self.id, 'resource_type': 'Unknown', 'resource_id': res_id, 'rights': 'forbidden', 'instigator_id': None})

    def grant_access(self, type_, resource, right, instigator=None) -> Access:
        with storage.get_db() as db:
            cur = db.cursor()

            cur.execute(
                'INSERT INTO accessrights(user_id, resource_type, resource_id, rights, instigator_id) VALUES (?, ?, ?, ?, ?) ON CONFLICT(user_id, resource_type, resource_id) DO UPDATE SET rights=?, instigator_id=?', 
                (self.id, type_, resource, right, instigator, right, instigator))
            db.commit()

            id_ = cur.lastrowid

            return Access(**dict(id=id_, user_id=self.id, resource_type=type_, resource_id=resource, rights=right, instigator_id=instigator))

    def filter_access(self, sequence, type_):
        accesses = {access.resource_id: access for access in self.get_access_of_type(type_)}
        return ((item, accesses[item]) for item in sequence if item in accesses)



def get_user_from_db(username):
    with storage.get_db() as db:
        logger.info(f'Try to find {username}')
        user_data = db.execute('SELECT * FROM users WHERE username=?', (username,)).fetchone()
        logger.info(f'Found {user_data}')

        if not user_data:
            logger.info('Data wrong')
            return None
        
        return User(**user_data)


def create_session(user):
    with storage.get_db() as db:
        session_id = secrets.token_urlsafe(64)

        db.execute('INSERT INTO sessions VALUES (?, ?)', (session_id, user.id))

        db.commit()
        return session_id


def delete_session(user):
    with storage.get_db() as db:
        db.execute('DELETE FROM sessions WHERE user_id=?', (user.id, ))

        db.commit()


def get_user(pnpmanager: Annotated[str, Cookie()]=None):
    if pnpmanager:
        with storage.get_db() as db:
            user = db.execute('SELECT users.* FROM sessions join users on sessions.user_id = users.id WHERE sessions.id = ?', (pnpmanager, )).fetchone()

            if user:
                return User(**user)
    raise NotAuthenticatedException()


def get_admin(user: Annotated[User, Depends(get_user)]):
    if user.admin:
        return user
    raise HTTPException(status_code=403)


def get_optional_user(pnpmanager: Annotated[str, Cookie()]=None):
    if pnpmanager:
        with storage.get_db() as db:
            user = db.execute('SELECT users.* FROM sessions join users on sessions.user_id = users.id WHERE sessions.id = ?', (pnpmanager, )).fetchone()

            if user:
                return User(**user)
    return None


Resource = namedtuple('Resource', 'id, user, access')

class ResourceGetter:
    def __init__(self, param_name, res_type, editable=False, is_query=False, optional=False):
        self.param_name = param_name
        self.res_type = res_type
        self.editable = editable
        self.is_query = is_query
        self.optional = optional

    def __call__(self, request: fastapi.Request, user: Annotated[User, Depends(get_user)]):
        if self.param_name in (request.path_params if not self.is_query else request.query_params):
            res_id = (request.path_params if not self.is_query else request.query_params)[self.param_name]

            access = user.get_access_resource(res_id)
            if access.rights != 'forbidden' and access.resource_type == self.res_type and (not self.editable or access.rights == 'edit'):
                return Resource(res_id, user, access)

        if self.optional: 
            return None
        raise HTTPException(status_code=404)


@auth_router.get('/me')
async def get_me(user: Annotated[User, Depends(get_user)]):
    return user


@auth_router.post('/login', response_class=fastapi.responses.HTMLResponse)
async def login_session(
    username: Annotated[str, Form()], 
    password: Annotated[str, Form()], 
    response: fastapi.Response, 
    request: fastapi.Request):
    
    user = get_user_from_db(username)

    if user is None or not bcrypt.checkpw(password.encode('utf-8'), user.password.encode('utf-8')):
        sleep(2)
        return '<span>Invalid credentials</span>'

    delete_session(user)
    session = create_session(user)

    response.set_cookie(key='pnpmanager', value=session, secure=settings.auth_use_secure_cookie, httponly=True)

    push_events(response, {'userLogin': 'username'})
    return '<span>Success</span>'


@auth_router.get('/logout')
async def logout_session(user: Annotated[User, Depends(get_user)], response: fastapi.Response):

    delete_session(user)

    response.delete_cookie('pnpmanager')
    return fastapi.responses.RedirectResponse("/")
