"""Tests for releases, tags and release assets (issue #43). GitHub is never contacted."""
import io
import pytest
import requests
from werkzeug.datastructures import FileStorage, MultiDict

from app.controllers import releases_controller
from app.controllers.releases_controller import (
    delete_asset, delete_release, generate_notes, human_size, tags_without_release, upload_assets,
    validate_release_form,
)
from app.routes import release_routes

REPO = '/repos/alice/app'
BRANCHES = ['main', 'dev']


def release(release_id=1, **fields):
    data = {'id': release_id, 'tag_name': 'v1.0.0', 'name': 'Version 1', 'body': 'Notes <b>here</b>', 'draft': False,
            'prerelease': False, 'html_url': 'https://github.com/alice/app/releases/tag/v1.0.0',
            'target_commitish': 'main', 'author': {'login': 'alice'}, 'published_at': '2026-11-20T10:00:00Z',
            'assets': [{'id': 50, 'name': 'app.zip', 'size': 2048, 'download_count': 3,
                        'browser_download_url': 'https://github.com/alice/app/releases/download/v1.0.0/app.zip'}]}
    data.update(fields)
    return data


@pytest.fixture
def github(monkeypatch):
    """A fake github_api: responses by (method, path); every call is recorded."""
    state = {'calls': [], 'responses': {}}

    def fake_api(method, path, token, **kwargs):
        state['calls'].append((method, path, kwargs.get('json'), kwargs.get('params')))
        return state['responses'].get((method, path), (None, 'Not Found'))

    monkeypatch.setattr(releases_controller, 'github_api', fake_api)
    monkeypatch.setattr(release_routes, 'get_installation_access_token', lambda: 'tok')
    monkeypatch.setattr(release_routes, 'list_branches', lambda o, r, t: ([{'name': n} for n in BRANCHES], None))
    monkeypatch.setattr(release_routes, 'get_repository', lambda o, r, t: ({'default_branch': 'main'}, None))
    state['responses'][('GET', f'{REPO}/tags')] = ([{'name': 'v1.0.0', 'commit': {'sha': 'a' * 40}},
                                                    {'name': 'v0.9.0', 'commit': {'sha': 'b' * 40}}], None)
    return state


def flashes(client):
    with client.session_transaction() as sess:
        return sess.get('_flashes', [])


class FakeUploadResponse:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload

    @property
    def text(self):
        return str(self._payload)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f'{self.status_code}', response=self)


# --- Validation --------------------------------------------------------------

def test_valid_release_payload():
    payload, error = validate_release_form(MultiDict({
        'tag_name': ' v2.0.0 ', 'target_commitish': 'dev', 'name': '', 'body': 'Line\r\nTwo',
        'prerelease': 'on', 'make_latest': 'false'}), BRANCHES)
    assert error is None
    assert payload == {'tag_name': 'v2.0.0', 'name': 'v2.0.0', 'body': 'Line\nTwo', 'draft': False,
                       'prerelease': True, 'target_commitish': 'dev', 'make_latest': 'false'}


def test_draft_does_not_set_latest_and_sha_target_is_allowed():
    payload, _ = validate_release_form(MultiDict({'tag_name': 'v2', 'draft': 'on', 'target_commitish': 'c' * 40}), BRANCHES)
    assert payload['draft'] is True and 'make_latest' not in payload
    assert payload['target_commitish'] == 'c' * 40


@pytest.mark.parametrize('fields, message', [
    ({'tag_name': ''}, 'valid tag name'),
    ({'tag_name': 'v1..2'}, 'valid tag name'),
    ({'tag_name': 'has space'}, 'valid tag name'),
    ({'tag_name': 'v1', 'target_commitish': 'nope'}, 'Choose a branch'),
    ({'tag_name': 'v1', 'name': 'x' * 1025}, 'at most 1024'),
    ({'tag_name': 'v1', 'body': 'x' * 125001}, 'at most 125000'),
    ({'tag_name': 'v1', 'make_latest': 'always'}, 'Unknown'),
])
def test_invalid_release_forms(fields, message):
    payload, error = validate_release_form(MultiDict(fields), BRANCHES)
    assert payload is None and message in error


def test_tags_without_release():
    tags = [{'name': 'v2'}, {'name': 'v1'}, {'name': 'v0'}]
    assert tags_without_release(tags, [{'tag_name': 'v1'}]) == [{'name': 'v2'}, {'name': 'v0'}]


def test_human_size():
    assert [human_size(n) for n in (0, 500, 2048, 5 * 1024 * 1024, 3 * 1024 ** 3)] == \
        ['0 B', '500 B', '2.0 KB', '5.0 MB', '3.0 GB']


# --- Controller --------------------------------------------------------------

def test_generate_notes(github):
    github['responses'][('POST', f'{REPO}/releases/generate-notes')] = ({'name': 'v2', 'body': '## Changes\n* #5'}, None)
    notes, error = generate_notes('alice', 'app', MultiDict({'tag_name': 'v2', 'target_commitish': 'main',
                                                             'previous_tag_name': 'v1.0.0'}), 'tok')
    assert (notes, error) == ('## Changes\n* #5', None)
    assert github['calls'][0][2] == {'tag_name': 'v2', 'target_commitish': 'main', 'previous_tag_name': 'v1.0.0'}


def test_generate_notes_needs_a_tag(github):
    assert generate_notes('alice', 'app', MultiDict({}), 'tok')[1].startswith('Enter the tag name first')
    assert github['calls'] == []


def test_delete_release_and_tag(github):
    github['responses'][('DELETE', f'{REPO}/releases/1')] = (None, None)
    github['responses'][('DELETE', f'{REPO}/git/refs/tags/v1.0.0')] = (None, None)
    messages, error = delete_release('alice', 'app', release(), True, 'tok')
    assert error is None
    assert messages == [('success', 'Release Version 1 deleted.'), ('success', 'Tag v1.0.0 deleted.')]


def test_delete_release_keeps_tag_by_default_and_reports_tag_failure(github):
    github['responses'][('DELETE', f'{REPO}/releases/1')] = (None, None)
    messages, _ = delete_release('alice', 'app', release(), False, 'tok')
    assert len(messages) == 1 and not any('/git/refs' in c[1] for c in github['calls'])

    messages, _ = delete_release('alice', 'app', release(), True, 'tok')
    assert messages[1] == ('error', "The release was deleted, but the tag v1.0.0 couldn't be: Not Found")


def test_draft_release_never_deletes_a_tag(github):
    github['responses'][('DELETE', f'{REPO}/releases/1')] = (None, None)
    delete_release('alice', 'app', release(draft=True), True, 'tok')
    assert not any('/git/refs' in c[1] for c in github['calls'])


def test_upload_assets(monkeypatch):
    sent = []

    def fake_post(url, params, data, timeout, headers):
        sent.append((url, params, data, headers['Content-Type']))
        return FakeUploadResponse(400 if params['name'] == 'bad.bin' else 201,
                                  {'message': 'Validation Failed'} if params['name'] == 'bad.bin' else {})

    monkeypatch.setattr(releases_controller.requests, 'post', fake_post)
    files = [FileStorage(io.BytesIO(b'\x00zip'), filename='build.zip', content_type='application/zip'),
             FileStorage(io.BytesIO(b'x'), filename='app.zip'),
             FileStorage(io.BytesIO(b'y'), filename='bad.bin', content_type='weird type'),
             FileStorage(io.BytesIO(b'z'), filename='..')]
    results = upload_assets('alice', 'app', release(), files, 'tok')

    assert results == [('success', 'Uploaded build.zip.'),
                       ('error', 'app.zip: an asset with this name already exists. Delete it first.'),
                       ('error', 'bad.bin: Validation Failed'),
                       ('error', "'..' isn't a valid file name.")]
    assert sent[0] == ('https://uploads.github.com/repos/alice/app/releases/1/assets', {'name': 'build.zip'},
                       b'\x00zip', 'application/zip')
    assert sent[1][3] == 'application/octet-stream'


def test_upload_assets_limits():
    assert upload_assets('alice', 'app', release(), [], 'tok') == [('error', 'Choose at least one file to upload.')]
    many = [FileStorage(io.BytesIO(b''), filename=f'f{i}') for i in range(11)]
    assert 'at most 10' in upload_assets('alice', 'app', release(), many, 'tok')[0][1]


def test_delete_asset_must_belong_to_release(github):
    assert delete_asset('alice', 'app', release(), 999, 'tok') == (None, "That file isn't part of this release.")
    assert github['calls'] == []
    github['responses'][('DELETE', f'{REPO}/releases/assets/50')] = (None, None)
    assert delete_asset('alice', 'app', release(), 50, 'tok') == ('app.zip', None)


# --- Routes ------------------------------------------------------------------

def test_releases_page(logged_in_client, github):
    github['responses'][('GET', f'{REPO}/releases')] = ([release(), release(2, tag_name='v2.0.0-rc1', name='',
                                                                            draft=True, prerelease=True)], None)
    html = logged_in_client.get('/repos/alice/app/releases').data.decode()
    assert 'Version 1' in html and 'v2.0.0-rc1' in html
    assert 'draft' in html and 'pre-release' in html
    # v0.9.0 has no release, so it's offered
    assert '/repos/alice/app/releases/new?tag=v0.9.0' in html
    assert 'releases/new?tag=v1.0.0' not in html


def test_release_detail_escapes_notes(logged_in_client, github):
    github['responses'][('GET', f'{REPO}/releases/1')] = (release(), None)
    html = logged_in_client.get('/repos/alice/app/releases/1').data.decode()
    assert 'Notes &lt;b&gt;here&lt;/b&gt;' in html
    assert 'app.zip' in html and '2.0 KB' in html and '3 downloads' in html


def test_missing_release_is_404(logged_in_client, github):
    assert logged_in_client.get('/repos/alice/app/releases/7').status_code == 404


def test_new_release_form_prefills_tag_and_default_branch(logged_in_client, github):
    html = logged_in_client.get('/repos/alice/app/releases/new?tag=v0.9.0').data.decode()
    assert 'value="v0.9.0"' in html
    html = logged_in_client.get('/repos/alice/app/releases/new').data.decode()
    assert '<option value="main" selected>main</option>' in html


def test_creating_a_release(logged_in_client, github):
    github['responses'][('POST', f'{REPO}/releases')] = (release(9, name='v2'), None)
    response = logged_in_client.post('/repos/alice/app/releases/new', data={
        'action': 'save', 'tag_name': 'v2', 'target_commitish': 'main', 'body': 'Hi', 'make_latest': 'true'})
    assert response.headers['Location'].endswith('/repos/alice/app/releases/9')
    assert github['calls'][-1][2] == {'tag_name': 'v2', 'name': 'v2', 'body': 'Hi', 'draft': False,
                                      'prerelease': False, 'target_commitish': 'main', 'make_latest': 'true'}
    assert flashes(logged_in_client) == [('success', 'Release v2 created.')]


def test_generate_button_fills_notes_without_saving(logged_in_client, github):
    github['responses'][('POST', f'{REPO}/releases/generate-notes')] = ({'body': '* Added <things>'}, None)
    response = logged_in_client.post('/repos/alice/app/releases/new', data={
        'action': 'generate', 'tag_name': 'v2', 'target_commitish': 'main', 'body': 'old'})
    html = response.data.decode()
    assert response.status_code == 200
    assert '* Added &lt;things&gt;</textarea>' in html
    assert not any(call[0] == 'POST' and call[1] == f'{REPO}/releases' for call in github['calls'])


def test_invalid_release_keeps_form_values(logged_in_client, github):
    response = logged_in_client.post('/repos/alice/app/releases/new', data={
        'action': 'save', 'tag_name': 'bad tag', 'body': 'Keep me'})
    assert response.status_code == 400
    assert b'Keep me</textarea>' in response.data and b'valid tag name' in response.data


def test_github_error_on_create_is_shown(logged_in_client, github):
    github['responses'][('POST', f'{REPO}/releases')] = (None, 'Validation Failed')
    response = logged_in_client.post('/repos/alice/app/releases/new', data={'action': 'save', 'tag_name': 'v2'})
    assert response.status_code == 400 and b'Validation Failed' in response.data


def test_editing_a_release(logged_in_client, github):
    github['responses'][('GET', f'{REPO}/releases/1')] = (release(), None)
    github['responses'][('PATCH', f'{REPO}/releases/1')] = (release(), None)
    html = logged_in_client.get('/repos/alice/app/releases/1/edit').data.decode()
    assert 'value="Version 1"' in html and 'Notes &lt;b&gt;here&lt;/b&gt;</textarea>' in html

    response = logged_in_client.post('/repos/alice/app/releases/1/edit', data={
        'action': 'save', 'tag_name': 'v1.0.0', 'name': 'Version 1.0', 'draft': 'on'})
    assert response.headers['Location'].endswith('/repos/alice/app/releases/1')
    assert github['calls'][-1][0] == 'PATCH' and github['calls'][-1][2]['name'] == 'Version 1.0'


def test_delete_route(logged_in_client, github):
    github['responses'][('GET', f'{REPO}/releases/1')] = (release(), None)
    github['responses'][('DELETE', f'{REPO}/releases/1')] = (None, None)
    response = logged_in_client.post('/repos/alice/app/releases/1/delete', data={})
    assert response.headers['Location'].endswith('/repos/alice/app/releases')
    assert flashes(logged_in_client) == [('success', 'Release Version 1 deleted.')]


def test_asset_routes(logged_in_client, github, monkeypatch):
    github['responses'][('GET', f'{REPO}/releases/1')] = (release(), None)
    monkeypatch.setattr(release_routes, 'upload_assets', lambda o, r, rel, files, t: [('success', f'{len(files)} files')])
    response = logged_in_client.post('/repos/alice/app/releases/1/assets', data={
        'assets': [(io.BytesIO(b'a'), 'a.bin'), (io.BytesIO(b'b'), 'b.bin')]}, content_type='multipart/form-data')
    assert response.headers['Location'].endswith('/repos/alice/app/releases/1')
    assert flashes(logged_in_client) == [('success', '2 files')]

    github['responses'][('DELETE', f'{REPO}/releases/assets/50')] = (None, None)
    logged_in_client.post('/repos/alice/app/releases/1/assets/50/delete')
    assert flashes(logged_in_client)[-1] == ('success', 'Deleted app.zip.')


def test_invalid_repository_name(logged_in_client, github):
    assert logged_in_client.get('/repos/alice/bad%20name/releases').status_code == 400


@pytest.mark.parametrize('url', ['/repos/alice/app/releases', '/repos/alice/app/releases/new',
                                 '/repos/alice/app/releases/1'])
def test_pages_require_login(client, url):
    assert client.get(url).status_code == 403
