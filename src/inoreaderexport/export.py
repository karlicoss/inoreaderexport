from __future__ import annotations

import json
from functools import cache
from pathlib import Path
from uuid import uuid4

from requests_oauthlib import OAuth2Session

from .exporthelpers.export_helper import Json, Parser, setup_parser

# useful to debug requests
# from http.client import HTTPConnection
# HTTPConnection.debuglevel = 1


API = 'https://www.inoreader.com/reader/api/0'

# note: yes, it always contains com.google https://www.inoreader.com/developers/stream-ids
CONTENT_STREAMS = (
    'stream/contents/user/-/state/com.google/annotated',
    'stream/contents/user/-/state/com.google/starred',
    'stream/contents/user/-/state/com.google/broadcast',
    'stream/contents/user/-/state/com.google/like',
    'stream/contents/user/-/state/com.google/saved-web-pages',
)

READING_LIST = 'user/-/state/com.google/reading-list'
READ = 'user/-/state/com.google/read'

ACCOUNT_REQUESTS: dict[str, dict[str, str | int]] = {
    'subscription/list': {
        'team_assets': '1',
        'ino': 'reader',
    },
    'tag/list': {
        'types': '1',
        'counts': '1',
        'team_assets': '1',
        'ino': 'reader',
    },
    'preference/stream/list': {
        'ino': 'reader',
    },
    'user-info': {
        'ino': 'reader',
    },
    'preference/list': {
        'ino': 'reader',
    },
}

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

    @cache  # noqa: B019
    def _get_client(self) -> OAuth2Session:
        return OAuth2Session(
            self.app_id,
            token=self._read_token(),
        )

    def _get_json(self, *, endpoint: str, params: dict[str, str | int]) -> Json:
        response = self._get_client().get(API + '/' + endpoint, params=params)
        response.raise_for_status()
        result = response.json()
        assert isinstance(result, dict), result
        return result

    def _fetch_paginated(
        self,
        *,
        endpoint: str,
        params: dict[str, str | int],
        items_key: str,
    ) -> list[Json]:
        """Fetch every continuation page and combine the response lists stored under ``items_key``."""
        # order is newest first by default
        all_items: list[Json] = []
        continuation = None
        while True:
            request_params = {
                **params,
                **({} if continuation is None else {'c': continuation}),
            }
            res = self._get_json(endpoint=endpoint, params=request_params)
            page_items = res[items_key]
            assert isinstance(page_items, list), page_items
            all_items.extend(page_items)
            continuation = res.get('continuation')
            if continuation is None:
                break
            assert isinstance(continuation, str), continuation

        return all_items

    def _fetch_content_stream(self, *, stream: str) -> list[Json]:
        return self._fetch_paginated(
            endpoint=stream,
            params={
                'annotations': '1',
                'summaries': '1',
                # 100 is the documented maximum: https://www.inoreader.com/developers/stream-contents
                'n': 100,
            },
            items_key='items',
        )

    def _fetch_item_refs(self, *, include: str | None, exclude: str | None) -> list[Json]:
        assert (include is None) != (exclude is None), (include, exclude)
        params: dict[str, str | int] = {
            'includeAllDirectStreamIds': 'false',
            # 1000 is the documented maximum: https://www.inoreader.com/developers/item-ids
            'n': 1000,
            's': READING_LIST,
        }
        if include is not None:
            params['it'] = include
        if exclude is not None:
            params['xt'] = exclude
        return self._fetch_paginated(
            endpoint='stream/items/ids',
            params=params,
            items_key='itemRefs',
        )

    def _fetch_account(self) -> dict[str, Json]:
        return {
            endpoint: self._get_json(endpoint=endpoint, params=params) for endpoint, params in ACCOUNT_REQUESTS.items()
        }

    def export_json(self, *, include_reading_state: bool = False) -> Json:
        # always refresh token to make sure we don't get stale refresh_token?
        self._refresh_token()

        # Keep exact stream endpoint keys and separate item lists.
        # This preserves the original annotated shape and makes overlapping stream membership explicit.
        res: Json = {stream: self._fetch_content_stream(stream=stream) for stream in CONTENT_STREAMS}
        res['account'] = self._fetch_account()
        if include_reading_state:
            res['reading_state'] = {
                'stream': READING_LIST,
                'read': {
                    'include': READ,
                    'itemRefs': self._fetch_item_refs(include=READ, exclude=None),
                },
                'unread': {
                    'exclude': READ,
                    'itemRefs': self._fetch_item_refs(include=None, exclude=READ),
                },
            }
        return res


def make_parser():
    p = Parser('Export your Inoreader account data as JSON.')
    setup_parser(
        parser=p,
        params=[
            'app_id',
            'app_key',
            'redirect_uri',
            'token_path',
        ],
    )
    p.add_argument(
        '--login', action='store_true', help='Use this for initial login to initialize the token in token_path'
    )
    p.add_argument(
        '--include-reading-state',
        action='store_true',
        help=(
            'Include fully paginated read/unread item IDs. '
            'This can exhaust the daily Zone 1 quota before the export is written.'
        ),
    )
    return p


def main() -> None:
    p = make_parser()
    args = p.parse_args()

    params = args.params
    dumper = args.dumper

    exporter = Exporter(**params)

    if args.login:
        exporter.login()

    j = exporter.export_json(include_reading_state=args.include_reading_state)
    js = json.dumps(j, ensure_ascii=False, indent=1)
    dumper(js)


if __name__ == '__main__':
    main()
