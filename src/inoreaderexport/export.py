from __future__ import annotations

import json
from uuid import uuid4
import sys

from requests_oauthlib import OAuth2Session

# useful to debug requests
# from http.client import HTTPConnection
# HTTPConnection.debuglevel = 1


app_id = 'TODO'
app_key = 'TODO'
redirect_uri = 'TODO'
token = 'TODO'


def get_token():
    state = str(uuid4())

    oauth = OAuth2Session(
        app_id,
        redirect_uri=redirect_uri,
        scope='read',
        state=state,
    )

    authorization_url, state = oauth.authorization_url(
        'https://www.inoreader.com/oauth2/auth'
    )
    print("go to", authorization_url)

    authorization_response = input('Enter the full callback URL').strip()

    # insert the resulting URI
    # input()
    # authorization_response = 'https://github.com/karlicoss?code=370ffb7af265cf5214d3d6a8c00664ba1c1050be&state=aa25d7e4-a8d4-4862-9d11-0d638d8cf421'

    token = oauth.fetch_token(
        'https://www.inoreader.com/oauth2/token',
        authorization_response=authorization_response,
        client_secret=app_key,
    )
    return token


API = 'https://www.inoreader.com/reader/api/0'

# note: yes, it always contains com.google https://www.inoreader.com/developers/stream-ids
ANNOTATED = 'stream/contents/user/-/state/com.google/annotated'


# client = OAuth2Session(app_id, token=token)
# res = client.get(API + '/' + METHOD)
# print(res.json())

# todo not sure if really need it? I suppose if the token in secrets is stale it would get auto refreshed
# del token['expires_at']
# token['expires_in'] = 0

# without token_updater, it throws a TokenUpdated exception
# we are not saving it anywhere (relying on refresh_token to get new access_token every time), so this just prevents the exception
def token_updater(xxx):
    pass


client = OAuth2Session(
    app_id,
    token=token,
    auto_refresh_url='https://www.inoreader.com/oauth2/token',
    auto_refresh_kwargs={
        'client_id': app_id,
        'client_secret': app_key,
    },
    token_updater=token_updater,
)


def fetch_one(continuation: str | None):
    MAX_NUMBER = 100  # https://www.inoreader.com/developers/stream-contents
    # MAX_NUMBER = 20  # https://www.inoreader.com/developers/stream-contents
    # TODO assert result is OK?
    # MAX_NUMBER = 2
    return client.get(
        API + '/' + ANNOTATED,
        params={
            'annotations': '1',
            'n': MAX_NUMBER,
            **({} if continuation is None else {'c': continuation}),
        },
    ).json()


def fetch_all():
    # order is newest first by default
    all_items = []

    continuation = None
    while True:
        res = fetch_one(continuation=continuation)
        all_items.extend(res['items'])
        continuation = res.get('continuation')
        if continuation is None:
            break

    return all_items


def get_json():
    annotated = fetch_all()
    res = {ANNOTATED: annotated}
    return res


def main() -> None:
    from argparse import ArgumentParser
    p = ArgumentParser()
    p.add_argument('--login', action='store_true')
    args = p.parse_args()

    if args.login:
        print(get_token())
        sys.exit(0)

    j = get_json()
    # j = {}

    json.dump(j, fp=sys.stdout, ensure_ascii=False, indent=2, sort_keys=True)

if __name__ == '__main__':
    main()


