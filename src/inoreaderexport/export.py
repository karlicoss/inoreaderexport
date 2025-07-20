from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from uuid import uuid4

from requests_oauthlib import OAuth2Session

from .exporthelpers.export_helper import Json, Parser, setup_parser

# useful to debug requests
# from http.client import HTTPConnection
# HTTPConnection.debuglevel = 1


API = 'https://www.inoreader.com/reader/api/0'

# note: yes, it always contains com.google https://www.inoreader.com/developers/stream-ids
ANNOTATED = 'stream/contents/user/-/state/com.google/annotated'

Token = Json


class Exporter:
    def __init__(self, *, app_id: str, app_key: str, redirect_uri: str, token_path: str) -> None:
        self.app_id = app_id
        self.app_key = app_key
        self.redirect_uri = redirect_uri
        self.token_path = token_path

    def login(self) -> None:
        state = str(uuid4())

        oauth = OAuth2Session(
            self.app_id,
            redirect_uri=self.redirect_uri,
            scope='read',
            state=state,
        )

        authorization_url, state = oauth.authorization_url('https://www.inoreader.com/oauth2/auth')
        print("go to", authorization_url)

        authorization_response = input('Enter the full callback URL\n').strip()

        token = oauth.fetch_token(
            'https://www.inoreader.com/oauth2/token',
            authorization_response=authorization_response,
            client_secret=self.app_key,
        )

        self._save_token(token)

    def _save_token(self, token: Token) -> None:
        Path(self.token_path).write_text(json.dumps(token))

    def _read_token(self) -> Token:
        tpath = Path(self.token_path)
        assert tpath.exists(), f'{tpath} does not exist -- you probably forgot to call --login'
        return json.loads(tpath.read_text())

    # hmm I tried making it work with auto_refresh_token/auto_refresh_kwargs but it didn't work..
    # so let's try to rely on just refreshing the tokens every time we run the script
    def _refresh_token(self) -> None:
        client = self._get_client()
        new_token = client.refresh_token(
            'https://www.inoreader.com/oauth2/token',
            client_id=self.app_id,
            client_secret=self.app_key,
        )
        self._save_token(new_token)

    @lru_cache(None)  # noqa: B019
    def _get_client(self) -> OAuth2Session:
        return OAuth2Session(
            self.app_id,
            token=self._read_token(),
        )

    def _fetch_one(self, continuation: str | None) -> Json:
        MAX_NUMBER = 100  # https://www.inoreader.com/developers/stream-contents
        params: dict[str, str | int] = {
            'annotations': '1',
            'n': MAX_NUMBER,
            **({} if continuation is None else {'c': continuation}),
        }
        return self._get_client().get(API + '/' + ANNOTATED, params=params).json()

    def _fetch_all(self) -> list[Json]:
        # order is newest first by default
        all_items = []

        continuation = None
        while True:
            res = self._fetch_one(continuation=continuation)
            all_items.extend(res['items'])
            continuation = res.get('continuation')
            if continuation is None:
                break

        return all_items

    def export_json(self) -> Json:
        # always refresh token to make sure we don't get stale refresh_token?
        self._refresh_token()

        annotated = self._fetch_all()
        res = {ANNOTATED: annotated}
        return res


def make_parser():
    p = Parser('Export your Inoreader annotation data as JSON.')
    setup_parser(
        parser=p,
        params=[
            'app_id',
            'app_key',
            'redirect_uri',
            'token_path',
        ],
    )
    p.add_argument('--login', action='store_true', help='Use this for initial login to initialize the token in token_path')
    return p


def main() -> None:
    p = make_parser()
    args = p.parse_args()

    params = args.params
    dumper = args.dumper

    exporter = Exporter(**params)  # ty: ignore[missing-argument]

    if args.login:
        exporter.login()

    j = exporter.export_json()
    js = json.dumps(j, ensure_ascii=False, indent=1)
    dumper(js)


if __name__ == '__main__':
    main()
