"""Tests for the in-browser file editor and uploads (issue #42). GitHub is never contacted."""
import base64
import io
import pytest
from werkzeug.datastructures import FileStorage, MultiDict

from app.controllers import file_editor_controller
from app.controllers.file_editor_controller import (
    MISSING, commit_changes, decode_text, editor_mode, load_file, normalize_directory, normalize_path,
    prepare_text, read_uploads, upload_name, validate_target,
)
from app.routes import editor_routes

REPO = '/repos/alice/app'
BRANCHES = ['main', 'dev']


def b64(data):
    return base64.b64encode(data).decode('ascii')


def file_response(path='README.md', content=b'# Hello\n', sha='blob1', size=None):
    return {'type': 'file', 'path': path, 'sha': sha, 'size': len(content) if size is None else size,
            'encoding': 'base64', 'content': b64(content), 'html_url': f'https://github.com/alice/app/blob/main/{path}'}


@pytest.fixture
def github(monkeypatch):
    """A fake github_api with a tiny in-memory Git: responses by (method, path), plus a commit flow."""
    state = {'calls': [], 'responses': {}, 'blobs': 0}

    def fake_api(method, path, token, **kwargs):
        state['calls'].append((method, path, kwargs.get('json'), kwargs.get('params')))
        if (method, path) in state['responses']:
            return state['responses'][(method, path)]
        if method == 'POST' and path.endswith('/git/blobs'):
            state['blobs'] += 1
            return {'sha': f"newblob{state['blobs']}"}, None
        if method == 'POST' and path.endswith('/git/trees'):
            return {'sha': 'newtree'}, None
        if method == 'POST' and path.endswith('/git/commits'):
            return {'sha': 'newcommit123456'}, None
        if path.endswith('/git/ref/heads/main') or path.endswith('/git/ref/heads/dev'):
            return {'object': {'sha': 'headsha'}}, None
        if path.endswith('/git/commits/headsha'):
            return {'tree': {'sha': 'basetree'}}, None
        if method in ('PATCH', 'POST') and '/git/refs' in path:
            return {}, None
        return None, 'Not Found'

    monkeypatch.setattr(file_editor_controller, 'github_api', fake_api)
    monkeypatch.setattr(editor_routes, 'get_installation_access_token', lambda: 'tok')
    monkeypatch.setattr(editor_routes, 'list_branches', lambda owner, repo, token: ([{'name': n} for n in BRANCHES], None))
    monkeypatch.setattr(editor_routes, 'get_repository', lambda owner, repo, token: ({'default_branch': 'main'}, None))
    return state


def calls_to(github, method, suffix):
    return [call for call in github['calls'] if call[0] == method and call[1].endswith(suffix)]


def flashes(client):
    with client.session_transaction() as sess:
        return sess.get('_flashes', [])


# --- Paths, modes, text ------------------------------------------------------

@pytest.mark.parametrize('path, expected', [
    ('docs/a.md', 'docs/a.md'), ('/docs/a.md/', 'docs/a.md'), ('héllo wörld.txt', 'héllo wörld.txt'),
    ('', None), ('../x', None), ('a/../b', None), ('a//b', None), ('./a', None), ('.git/config', None),
    ('a/.GIT/x', None), ('bad\nname', None), (' a/b', 'a/b'), ('a / b', None), ('x' * 1025, None),
])
def test_normalize_path(path, expected):
    assert normalize_path(path) == expected


def test_normalize_directory_allows_root():
    assert normalize_directory('') == '' and normalize_directory('/') == ''
    assert normalize_directory('docs/') == 'docs' and normalize_directory('../x') is None


def test_upload_name_strips_client_paths():
    assert upload_name('C:\\Users\\me\\logo.png') == 'logo.png'
    assert upload_name('dir/notes.txt') == 'notes.txt'
    assert upload_name('..') is None and upload_name('') is None


def test_editor_mode_by_extension():
    assert editor_mode('app/main.py') == (['python'], 'python')
    assert editor_mode('index.HTML')[1] == 'htmlmixed'
    assert editor_mode('Makefile') == ([], 'text/plain')


def test_decode_text_rejects_binary():
    assert decode_text('héllo'.encode()) == 'héllo'
    assert decode_text(b'\x89PNG\r\n\x1a\n\x00') is None
    assert decode_text(b'\xff\xfe') is None


def test_prepare_text_keeps_line_endings():
    assert prepare_text('a\r\nb\r\n') == 'a\nb\n'
    assert prepare_text('a\r\nb\r\n', original='x\ny\n') == 'a\nb\n'
    assert prepare_text('a\r\nb\r\n', original='x\r\ny\r\n') == 'a\r\nb\r\n'
    assert prepare_text(None) == ''


def test_validate_target():
    assert validate_target(MultiDict({'branch': 'main'}), BRANCHES) == ({'branch': 'main', 'new_branch': None}, None)
    assert validate_target(MultiDict({'branch': 'main', 'target': 'new', 'new_branch': 'fix/typo'}), BRANCHES) == \
        ({'branch': 'main', 'new_branch': 'fix/typo'}, None)
    assert validate_target(MultiDict({'branch': 'nope'}), BRANCHES)[1] == "Choose a branch to commit to."
    assert 'already exists' in validate_target(MultiDict({'branch': 'main', 'target': 'new', 'new_branch': 'dev'}), BRANCHES)[1]
    assert 'valid name' in validate_target(MultiDict({'branch': 'main', 'target': 'new', 'new_branch': 'a..b'}), BRANCHES)[1]


# --- Loading -----------------------------------------------------------------

def test_load_text_file(github):
    github['responses'][('GET', f'{REPO}/contents/docs/README.md')] = (file_response('docs/README.md'), None)
    loaded, error = load_file('alice', 'app', 'docs/README.md', 'dev', 'tok')
    assert error is None
    assert loaded['text'] == '# Hello\n' and loaded['sha'] == 'blob1' and loaded['reason'] is None
    assert github['calls'][0][3] == {'ref': 'dev'}


def test_load_binary_and_large_files(github):
    github['responses'][('GET', f'{REPO}/contents/logo.png')] = (file_response('logo.png', b'\x89PNG\x00\x01'), None)
    loaded, _ = load_file('alice', 'app', 'logo.png', None, 'tok')
    assert loaded['text'] is None and 'binary' in loaded['reason']

    big = dict(file_response('big.csv'), size=5_000_000, encoding='none', content='')
    github['responses'][('GET', f'{REPO}/contents/big.csv')] = (big, None)
    loaded, _ = load_file('alice', 'app', 'big.csv', None, 'tok')
    assert loaded['text'] is None and '1 MB' in loaded['reason']


def test_load_directory_is_an_error(github):
    github['responses'][('GET', f'{REPO}/contents/docs')] = ([{'name': 'a'}], None)
    assert load_file('alice', 'app', 'docs', None, 'tok') == (None, 'docs is not a file.')


def test_paths_are_url_encoded(github):
    load_file('alice', 'app', 'docs/a b#?.md', None, 'tok')
    assert github['calls'][0][1] == f'{REPO}/contents/docs/a%20b%23%3F.md'


# --- Committing --------------------------------------------------------------

def test_commit_to_existing_branch(github):
    github['responses'][('GET', f'{REPO}/contents/a.txt')] = (file_response('a.txt', sha='old'), None)
    commit, error = commit_changes('alice', 'app', {'branch': 'main', 'new_branch': None},
                                   [{'path': 'a.txt', 'content': b'new', 'expected_sha': 'old'}], 'Update a.txt', 'tok')
    assert error is None and commit['sha'] == 'newcommit123456'

    assert calls_to(github, 'POST', '/git/blobs')[0][2] == {'content': b64(b'new'), 'encoding': 'base64'}
    assert calls_to(github, 'POST', '/git/trees')[0][2] == {
        'base_tree': 'basetree', 'tree': [{'path': 'a.txt', 'mode': '100644', 'type': 'blob', 'sha': 'newblob1'}]}
    assert calls_to(github, 'POST', '/git/commits')[0][2] == {
        'message': 'Update a.txt', 'tree': 'newtree', 'parents': ['headsha']}
    assert calls_to(github, 'PATCH', '/git/refs/heads/main')[0][2] == {'sha': 'newcommit123456', 'force': False}
    # The file was checked at the branch tip that the commit builds on
    assert github['calls'][1][3] == {'ref': 'headsha'}


def test_commit_to_new_branch_creates_ref(github):
    commit_changes('alice', 'app', {'branch': 'main', 'new_branch': 'fix/typo'},
                   [{'path': 'a.txt', 'content': b'x', 'expected_sha': MISSING}], 'msg', 'tok')
    assert calls_to(github, 'POST', '/git/refs')[0][2] == {'ref': 'refs/heads/fix/typo', 'sha': 'newcommit123456'}
    assert not calls_to(github, 'PATCH', '/git/refs/heads/main')


def test_several_files_go_into_one_commit(github):
    commit_changes('alice', 'app', {'branch': 'main', 'new_branch': None},
                   [{'path': 'a.png', 'content': b'\x89PNG\x00', 'expected_sha': MISSING},
                    {'path': 'b.txt', 'content': b'b', 'expected_sha': MISSING}], 'msg', 'tok')
    assert len(calls_to(github, 'POST', '/git/blobs')) == 2
    assert len(calls_to(github, 'POST', '/git/commits')) == 1
    tree = calls_to(github, 'POST', '/git/trees')[0][2]['tree']
    assert [entry['path'] for entry in tree] == ['a.png', 'b.txt']
    assert base64.b64decode(calls_to(github, 'POST', '/git/blobs')[0][2]['content']) == b'\x89PNG\x00'


def test_refuses_when_file_changed_since_opened(github):
    github['responses'][('GET', f'{REPO}/contents/a.txt')] = (file_response('a.txt', sha='newer'), None)
    commit, error = commit_changes('alice', 'app', {'branch': 'main', 'new_branch': None},
                                   [{'path': 'a.txt', 'content': b'x', 'expected_sha': 'old'}], 'msg', 'tok')
    assert commit is None and 'was changed on main after you opened it' in error
    assert not calls_to(github, 'POST', '/git/blobs')


def test_new_file_must_not_exist(github):
    github['responses'][('GET', f'{REPO}/contents/a.txt')] = (file_response('a.txt'), None)
    _, error = commit_changes('alice', 'app', {'branch': 'main', 'new_branch': None},
                              [{'path': 'a.txt', 'content': b'x', 'expected_sha': None}], 'msg', 'tok')
    assert error == 'a.txt already exists on main.'


def test_branch_moved_during_commit(github):
    github['responses'][('PATCH', f'{REPO}/git/refs/heads/main')] = (None, 'Update is not a fast forward')
    _, error = commit_changes('alice', 'app', {'branch': 'main', 'new_branch': None},
                              [{'path': 'a.txt', 'content': b'x', 'expected_sha': MISSING}], 'msg', 'tok')
    assert error == "Couldn't update the branch: main was updated while you were committing. Try again."


def test_invalid_repository_name_makes_no_calls(github):
    assert commit_changes('alice', '..', {'branch': 'main', 'new_branch': None},
                          [{'path': 'a', 'content': b''}], 'm', 'tok') == (None, 'Invalid repository name.')
    assert github['calls'] == []


def test_read_uploads():
    files = [FileStorage(io.BytesIO(b'\x00\x01'), filename='logo.png'),
             FileStorage(io.BytesIO(b'hi'), filename='C:\\tmp\\notes.txt')]
    changes, error = read_uploads(files, 'assets')
    assert error is None
    assert changes == [{'path': 'assets/logo.png', 'content': b'\x00\x01', 'expected_sha': MISSING},
                       {'path': 'assets/notes.txt', 'content': b'hi', 'expected_sha': MISSING}]


def test_read_uploads_errors():
    assert read_uploads([], '')[1] == "Choose at least one file to upload."
    many = [FileStorage(io.BytesIO(b''), filename=f'f{i}') for i in range(21)]
    assert 'at most 20' in read_uploads(many, '')[1]
    dupes = [FileStorage(io.BytesIO(b''), filename='a.txt'), FileStorage(io.BytesIO(b''), filename='x/a.txt')]
    assert read_uploads(dupes, '')[1] == "a.txt was selected twice."
    assert "isn't a valid file name" in read_uploads([FileStorage(io.BytesIO(b''), filename='..')], '')[1]


# --- Editor routes -----------------------------------------------------------

def test_editor_page_shows_file_with_mode(logged_in_client, github):
    github['responses'][('GET', f'{REPO}/contents/app.py')] = (file_response('app.py', b'\nprint("<hi>")\n'), None)
    html = logged_in_client.get('/github/repos/alice/app/edit?path=app.py&branch=dev').data.decode()
    assert 'data-mode="python"' in html and 'mode/python/python.min.js' in html
    # Escaped, and the file's leading newline survives the textarea's dropped first newline
    assert 'data-mode="python">\n\nprint(&#34;&lt;hi&gt;&#34;)' in html
    assert 'name="sha" value="blob1"' in html
    assert '<option value="dev" selected>dev</option>' in html


def test_editor_for_binary_file_offers_upload(logged_in_client, github):
    github['responses'][('GET', f'{REPO}/contents/img/logo.png')] = (file_response('img/logo.png', b'\x00\xff'), None)
    html = logged_in_client.get('/github/repos/alice/app/edit?path=img/logo.png').data.decode()
    assert 'binary file' in html and '<textarea' not in html
    assert '/github/repos/alice/app/upload?dir=img&amp;branch=main' in html


def test_new_file_page_prefills_folder(logged_in_client, github):
    html = logged_in_client.get('/github/repos/alice/app/edit?dir=docs').data.decode()
    assert 'value="docs/"' in html and 'Preview' in html


@pytest.mark.parametrize('url, status', [
    ('/github/repos/alice/app/edit?path=../secret', 400),
    ('/github/repos/alice/app/edit?path=missing.txt', 404),
    ('/github/repos/alice/bad%20name/edit', 400),
])
def test_editor_rejects_bad_requests(logged_in_client, github, url, status):
    assert logged_in_client.get(url).status_code == status


def test_saving_an_edit(logged_in_client, github):
    github['responses'][('GET', f'{REPO}/contents/README.md')] = (file_response(), None)
    response = logged_in_client.post('/github/repos/alice/app/edit', data={
        'original_path': 'README.md', 'sha': 'blob1', 'branch': 'main', 'target': 'current',
        'content': '# Hello\r\nWorld\r\n', 'message': ''})
    assert response.status_code == 302
    assert response.headers['Location'].endswith('/github/repos/alice/app/contents?branch=main')
    blob = calls_to(github, 'POST', '/git/blobs')[0][2]
    assert base64.b64decode(blob['content']) == b'# Hello\nWorld\n'  # LF kept
    assert calls_to(github, 'POST', '/git/commits')[0][2]['message'] == 'Update README.md'
    assert flashes(logged_in_client) == [('success', 'Committed README.md to main (newcomm).')]


def test_unchanged_edit_is_not_committed(logged_in_client, github):
    github['responses'][('GET', f'{REPO}/contents/README.md')] = (file_response(), None)
    response = logged_in_client.post('/github/repos/alice/app/edit', data={
        'original_path': 'README.md', 'sha': 'blob1', 'branch': 'main', 'content': '# Hello\r\n'})
    assert response.status_code == 302
    assert flashes(logged_in_client) == [('info', 'No changes to commit.')]
    assert not calls_to(github, 'POST', '/git/blobs')


def test_edit_conflict_keeps_users_text(logged_in_client, github):
    github['responses'][('GET', f'{REPO}/contents/README.md')] = (file_response(sha='blob2'), None)
    response = logged_in_client.post('/github/repos/alice/app/edit', data={
        'original_path': 'README.md', 'sha': 'blob1', 'branch': 'main', 'content': 'my edit'})
    assert response.status_code == 400
    html = response.data.decode()
    assert 'after you opened it' in html and 'my edit</textarea>' in html


def test_new_file_on_new_branch_opens_pull_request(logged_in_client, github):
    response = logged_in_client.post('/github/repos/alice/app/edit', data={
        'path': 'docs/new.md', 'branch': 'main', 'target': 'new', 'new_branch': 'docs/new', 'open_pr': 'on',
        'content': 'Hi', 'message': 'Add docs'})
    assert response.headers['Location'].endswith('/repositories/app/pull_requests?create=1&base=main&head=docs/new')
    assert calls_to(github, 'POST', '/git/refs')[0][2]['ref'] == 'refs/heads/docs/new'


def test_new_file_with_bad_path_is_rejected(logged_in_client, github):
    response = logged_in_client.post('/github/repos/alice/app/edit', data={
        'path': '../x', 'branch': 'main', 'content': 'x'})
    assert response.status_code == 400 and b'Enter a valid file path' in response.data
    assert not calls_to(github, 'POST', '/git/blobs')


# --- Upload routes -----------------------------------------------------------

def test_upload_page(logged_in_client, github):
    html = logged_in_client.get('/github/repos/alice/app/upload?dir=assets&branch=dev').data.decode()
    assert 'enctype="multipart/form-data"' in html and 'value="assets"' in html
    assert '<option value="dev" selected>dev</option>' in html


def test_uploading_files(logged_in_client, github):
    response = logged_in_client.post('/github/repos/alice/app/upload', data={
        'dir': 'assets', 'branch': 'main', 'target': 'current',
        'files': [(io.BytesIO(b'\x89PNG\x00'), 'logo.png'), (io.BytesIO(b'hi'), 'notes.txt')],
    }, content_type='multipart/form-data')
    assert response.status_code == 302
    assert response.headers['Location'].endswith('/github/repos/alice/app/contents?path=assets&branch=main')
    assert [e['path'] for e in calls_to(github, 'POST', '/git/trees')[0][2]['tree']] == ['assets/logo.png', 'assets/notes.txt']
    assert calls_to(github, 'POST', '/git/commits')[0][2]['message'] == 'Upload logo.png, notes.txt'
    assert flashes(logged_in_client) == [('success', 'Uploaded 2 files to main (newcomm).')]


def test_upload_without_files(logged_in_client, github):
    response = logged_in_client.post('/github/repos/alice/app/upload', data={'branch': 'main'},
                                     content_type='multipart/form-data')
    assert response.status_code == 400 and b'Choose at least one file' in response.data


def test_upload_too_large_is_refused(logged_in_client, github, app):
    app.config['MAX_CONTENT_LENGTH'] = 10
    response = logged_in_client.post('/github/repos/alice/app/upload', data={
        'branch': 'main', 'files': [(io.BytesIO(b'x' * 100), 'big.bin')]}, content_type='multipart/form-data')
    assert response.status_code == 413
    assert not calls_to(github, 'POST', '/git/blobs')


def test_contents_page_links_to_editor_and_upload(logged_in_client, monkeypatch):
    from app.routes import content_routes
    monkeypatch.setattr(content_routes, 'get_repository_contents', lambda *a: [
        {'name': 'a.txt', 'path': 'docs/a.txt', 'type': 'file', 'sha': 's', 'download_url': '#'}])
    monkeypatch.setattr(content_routes, 'get_branches', lambda *a: ['main'])
    monkeypatch.setattr(content_routes, 'get_github_issues', lambda *a: [])
    monkeypatch.setattr(content_routes, 'get_pull_requests', lambda *a: [])
    html = logged_in_client.get('/github/repos/alice/app/contents?path=docs&branch=main').data.decode()
    assert '/github/repos/alice/app/edit?path=docs/a.txt&amp;branch=main' in html
    assert '/github/repos/alice/app/edit?dir=docs&amp;branch=main' in html
    assert '/github/repos/alice/app/upload?dir=docs&amp;branch=main' in html


@pytest.mark.parametrize('url', ['/github/repos/alice/app/edit', '/github/repos/alice/app/upload'])
def test_pages_require_login(client, url):
    assert client.get(url).status_code == 403
