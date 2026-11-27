# RepoMaster

RepoMaster is a Flask-based web application designed to interact with the GitHub API, providing essential repository management functionalities using a GitHub App for authentication.

## Functionalities

### 1. View Repositories (Available)
- **Route:** `/github/repositories`
- **Functionality:** Fetches a list of repositories accessible by the authenticated GitHub App installation.
- **Implementation Details:**
  - Uses a GitHub App to authenticate and retrieve repositories.
  - Displays fetched repositories in a user-friendly format on a webpage.
  - Requires the GitHub App to be installed on the user’s account or organization.

### 2. Manage Issues (Available)
- **Route:** `/repositories/<repo_name>/issues?state=open|closed|all`
- **Functionality:** Lists a repository's issues (pull requests are left out), with an open / closed / all filter. Create issues and close or reopen them from the list.
- **Issue page** (`/repositories/<repo_name>/issues/<number>`):
  - Edit the title and description
  - Close (as completed or not planned) and reopen
  - Read and post comments
  - Add / remove labels (from the repository's labels)
  - Assign / unassign people who can be assigned in the repository
  - Set or clear the milestone (open milestones)
- Pull request numbers open on the pull request page. The inbox and repository contents pages link to the issue page.
- Issue text is shown as plain text (Markdown isn't rendered).

### 3. Delete Repositories (Available)
- **Route:** `/delete_repo`
- **Functionality:** Allows users to select and delete multiple repositories.
- **Planned Features:**
  - A page where users can see a list of repositories and select those for deletion.
  - Confirmation mechanism before proceeding with the deletion.

### 3a. Bulk Repository Actions (Available)
- **Route:** `/repositories/bulk`
- **Functionality:** Apply one change to many repositories at once:
  - Archive / unarchive
  - Make private / public
  - Add / remove topics (merged with each repository's existing topics, max 20)
  - Change the default branch (the branch must exist in each repository)
  - Add a collaborator with a chosen permission (invites them, or changes their permission if they already have access)
  - Remove a collaborator (also cancels their pending invitations; repositories where they have no access are reported as "no change")
  - Delete permanently (you must type `delete` on the confirmation page)
- **Flow:** select repositories (with filter and select-all) → review a confirmation page listing every repository that will change → apply and get a per-repository success/failure report. One failure doesn't stop the rest.

### 3b. Cleanup Dashboard (Available)
- **Route:** `/repositories/cleanup?months=6`
- **Functionality:** Finds repositories that probably need attention (archived ones are skipped):
  - **Inactive:** no push in the last N months (selectable, default 6)
  - **Empty:** size 0
  - **Unmodified forks:** no commits of their own compared with the parent's default branch
- **Branches** (`/repositories/cleanup/branches?repo=owner/name`): for one repository, lists branches already **merged** into the default branch and **stale** branches (unmerged, nothing new in N months), and deletes the selected ones. The default branch and protected branches are never deleted.
- Archive / delete of repositories goes through the bulk actions confirmation step.

### 3c. Issue & PR Inbox (Available)
- **Route:** `/inbox`
- **Functionality:** One list of every open issue and pull request across the repositories available to RepoMaster, using a single GitHub search request per page.
  - Filter by type (issues / PRs), repository, label, author and age (e.g. opened in the last 7 days, open longer than 90 days)
  - Sort by recently updated, newest, oldest or least recently updated
  - 50 per page (GitHub search returns at most 1,000 results)
  - Each item links to its page in RepoMaster and on GitHub

### 3d. Create Repositories (Available)
- **Route:** `/repositories/new`
- **Functionality:** Create a repository and set it up in one step:
  - Name, description and visibility
  - Start empty (optional README, `.gitignore` template and license) or from one of your template repositories (optionally with all branches)
  - Copy labels from an existing repository
  - Protect the default branch (1 approving review, no force pushes or deletion)
- **How it works:** GitHub only lets a user's own token create repositories in a personal account, so submitting the form sends you through GitHub's authorization once more (instant if RepoMaster is already authorized). That token is used for this one request and never stored. A results page shows each step; setup steps that fail (e.g. branch protection on a private repository without a paid plan) don't undo the creation.

### 3e. Releases & Tags (Available)
- **Route:** `/repos/<owner>/<repo>/releases` (the **Releases** button on each repository)
- **Functionality:**
  - List releases (including drafts and pre-releases) and the tags that don't have a release yet
  - Create a release from an existing or new tag (on a chosen branch), with title, notes, draft / pre-release and "latest release" options
  - **Generate release notes** from merged pull requests (since the previous release or a chosen tag) and review them before saving
  - Edit and delete releases, optionally deleting the tag too
  - Upload release files (up to 10 at a time) and delete them
- Release notes are shown as plain text.

### 3f. Repository Analytics (Available)
- **Route:** `/repos/<owner>/<repo>/analytics` (the **Analytics** button on each repository)
- **Functionality:** Charts (Chart.js) and tables for one repository:
  - Views and clones per day, total and unique (last 14 days), plus top referrers and popular pages
  - Commits per week over the last 12 months
  - Languages by share of code
  - Top 20 contributors with commits and lines added / removed
- Each chart has a "Show data" table, and the page follows the system's light / dark setting.
- GitHub computes the statistics in the background the first time they're requested; RepoMaster retries briefly and otherwise asks you to reload in a minute. Each section loads independently, so one that fails (e.g. traffic without permission) doesn't hide the rest.
- Traffic needs the GitHub App's **Administration: Read** permission.

### 3g. GitHub Actions (Available)
- **Route:** `/repos/<owner>/<repo>/actions` (the **Actions** button on each repository)
- **Functionality:**
  - Workflows and recent runs, filterable by workflow and status, with paging
  - Run page with jobs, steps and durations; **re-run failed jobs**, **re-run all jobs** or **cancel** a running run
  - **Download logs** (GitHub's short-lived .zip link)
  - **Run a workflow manually** (`workflow_dispatch`): RepoMaster reads the workflow file on the chosen branch and builds a form from its inputs (text, number, boolean, choice), validating them before dispatching
  - **Secrets:** list names, add / replace and delete. Values are encrypted in RepoMaster with the repository's public key (libsodium sealed box, via PyNaCl) and are never shown, logged or sent in plain text
- Needs the GitHub App permissions **Actions: Read & write** and **Secrets: Read & write**.

### 3h. Notifications (Available)
- **Routes:** `POST /github/webhook` (called by GitHub) and `/notifications`
- **Functionality:** GitHub sends the App's events to RepoMaster's webhook, which turns the useful ones into notifications:
  - Pull requests opened, ready for review, **review requested**, merged / closed, reopened
  - Issues opened, closed, reopened, assigned
  - Pushes to a branch
  - **Failed CI**: failed workflow runs, and failed checks from other CI apps
  - RepoMaster installed / suspended on an account
- A **Notifications** button with an unread count (refreshed every minute) is on the repositories, inbox and home pages. Opening a notification marks it read and goes to the matching RepoMaster page.
- Every delivery is verified with `GITHUB_WEBHOOK_SECRET` (the `X-Hub-Signature-256` HMAC); without the secret configured, deliveries are refused. GitHub's redeliveries are ignored, uninstalling removes that installation's notifications, and the newest 500 per installation are kept.
- Notifications are stored in a small SQLite database (`instance/repomaster.db` by default, or `DATABASE_PATH`).

### 3i. Security Overview (Available)
- **Route:** `/security` (the **Security** button on the repositories and inbox pages)
- **Functionality:** One page with the open security alerts of every repository RepoMaster can access, most severe first:
  - **Dependabot:** severity, package and ecosystem, the version that fixes it, CVE / GHSA and manifest file
  - **Secret scanning:** the secret type, whether it's still active and whether it was leaked publicly. The secret itself is never shown or stored
  - **Code scanning:** rule, tool and file / line (for repositories where it's enabled)
- Filter by severity, alert type and repository; each alert links to GitHub. The repository and type filters also limit which GitHub requests are made.
- GitHub doesn't rate leaked secrets, so RepoMaster lists them as **critical**. Code scanning rules without a security severity map error → high, warning → medium, note → low.
- Repositories where a feature is off, or the App lacks permission, are listed under "Couldn't check" with GitHub's reason instead of failing the page. Up to 100 alerts per repository and type are shown.
- Needs the GitHub App permissions **Dependabot alerts: Read**, **Secret scanning alerts: Read** and **Code scanning alerts: Read**.

### 3j. Collaborators & Teams (Available)
- **Route:** `/repos/<owner>/<repo>/collaborators` (the **Collaborators** button on each repository)
- **Functionality:**
  - List collaborators with their permission level (Read, Triage, Write, Maintain, Admin, or a custom organization role)
  - Invite a collaborator, change their permission or remove them. The owner's access can't be changed
  - Pending invitations: change the offered permission or cancel the invitation
  - **Organization repositories:** teams with access, change a team's permission, remove a team, or give another team in the organization access
- To add or remove one person across many repositories, use the collaborator actions in **Bulk Actions**.
- Needs the GitHub App permission **Administration: Read & write** (collaborators and invitations), and for teams on organizations **Members: Read**.

### 4. Manage Pull Requests (Available)
- **Route:** `/repositories/<repo_name>/pull_requests?state=open|closed|all`
- **Functionality:** Lists a repository's pull requests (open / closed / all) and creates new ones.
- **Pull request page** (`/repositories/<repo_name>/pull_requests?pr_number=<number>`): everything needed to review and merge without leaving RepoMaster:
  - Changed files with a colored diff (first 100 files; the rest are linked on GitHub)
  - Reviews (with who approved / requested changes) and review comments
  - Check runs (CI status) for the latest commit
  - A clear merge status: conflicts, blocked by branch protection, behind, failing checks
  - Merge with a merge commit, squash or rebase (only the methods the repository allows), with an optional commit title/message and an option to delete the head branch afterwards
  - Close and reopen
- Merging sends the commit RepoMaster showed you, so if new commits were pushed in the meantime GitHub refuses the merge and you're asked to review them first.

### 5. Branch Management (Available)

#### Get Branch Details
- **API Endpoint:** `GET /repos/{owner}/{repo}/branches/{branch}`  
- **Functionality:** Fetch details about a specific branch, including protection rules.

#### List All Branches
- **API Endpoint:** `GET /repos/{owner}/{repo}/branches`  
- **Functionality:** Retrieve a list of all branches in a repository.

#### Create a Branch
- **API Endpoint:** `POST /repos/{owner}/{repo}/git/refs`  
- **Functionality:** Create a new branch from an existing reference.

#### Branch Protection
- **Route:** `/repos/<owner>/<repo>/branch-protection?branch=<name>` (the **Protection** button on the branch list)
- **API Endpoint:** `GET/PUT/DELETE /repos/{owner}/{repo}/branches/{branch}/protection`
- **Functionality:** View and edit a branch's protection rules: required pull request reviews (approval count, dismiss stale approvals, code owners, approval of the latest push), required status checks (with "must be up to date"), conversation resolution, linear history, applying the rules to admins, and allowing force pushes / deletion. Settings the editor doesn't show (who may push, who may dismiss reviews, which app a check must come from) are kept when saving. Protection can also be removed.

#### Compare Branches
- **Route:** `/repos/<owner>/<repo>/compare?base=<branch>&head=<branch>`
- **API Endpoint:** `GET /repos/{owner}/{repo}/compare/{base}...{head}`
- **Functionality:** Shows whether a branch is ahead of, behind, identical to or diverged from another, with the commit list. When the branch has new commits it offers **Open pull request** (pre-filled), or links to the pull request that's already open.

### Delete a Branch
- **API Endpoint:** `DELETE /repos/{owner}/{repo}/git/refs/heads/{branch}`  
- **Functionality:** Remove a branch permanently.

### Rename a Branch
- **API Endpoint:** `POST /repos/{owner}/{repo}/branches/{branch}/rename`  
- **Functionality:** Rename a branch.

### Get Repository Contents
- **API Endpoint:** `GET /repos/{owner}/{repo}/contents/{path}`  
- **Functionality:** Retrieve the content of a file or directory.

### Create a File
- **API Endpoint:** `PUT /repos/{owner}/{repo}/contents/{path}`  
- **Functionality:** Add a new file to the repository.

### Update a File
- **API Endpoint:** `PUT /repos/{owner}/{repo}/contents/{path}`  
- **Functionality:** Modify the content of an existing file.

### File Editor & Uploads
- **Routes:** `/github/repos/<owner>/<repo>/edit?path=<file>&branch=<branch>` (no `path`: a new file) and `/github/repos/<owner>/<repo>/upload?dir=<folder>`
- **API Endpoints:** Git Data API: `GET /git/ref/heads/{branch}`, `POST /git/blobs`, `POST /git/trees`, `POST /git/commits`, `PATCH /git/refs/heads/{branch}` / `POST /git/refs`
- **Functionality:**
  - Code editor (CodeMirror) with syntax highlighting chosen from the file extension; falls back to a plain text area if the editor can't load
  - Markdown preview (sanitized) for `.md` files
  - Upload up to 20 files (text or binary, 25 MB per upload) into a folder as **one commit**
  - Commit to the current branch, or to a **new branch**, optionally going straight to the pull request form
  - Safe saves: if the file changed on GitHub after you opened it (or the branch moved while committing), nothing is overwritten and your edit stays in the editor
  - Line endings are kept: a file that uses LF stays LF even though browsers submit CRLF
  - Binary files and files over 1 MB open read-only, with a link to upload a replacement

### Delete a File
**API Endpoint:** `DELETE /repos/{owner}/{repo}/contents/{path}`  
- **Functionality:** Remove a file from the repository.

## Migration to GitHub App
RepoMaster now uses a GitHub App for authentication and repository management, providing enhanced security and scalability:
- **Sign-in:** Users sign in with GitHub (the App's user authorization / OAuth flow). RepoMaster then asks GitHub which App installations *that user* can access and only uses one of those, so nobody can act on an installation that isn't theirs.
- **API calls:** Repository operations use a short-lived installation access token for the verified installation.
- **Benefits:** Fine-grained permissions, easier token management, and enhanced security.

### GitHub App settings
On the App's settings page (**GitHub → Settings → Developer settings → GitHub Apps → your app**):

| Setting | Value |
|---|---|
| **Callback URL** | `https://<your-domain>/github/callback` (add `http://127.0.0.1:5000/github/callback` for local development) |
| **Setup URL** (under *Post installation*) | `https://<your-domain>/github/authorize` |
| **Request user authorization (OAuth) during installation** | Off. RepoMaster starts sign-in itself, with CSRF protection, after installation |
| **Client secret** | Generate one and put it in `GITHUB_CLIENT_SECRET` |
| **Private key** | Generate one and point `GITHUB_PRIVATE_KEY_PATH` at the `.pem` file |
| **Webhook** | Active, URL `https://<your-domain>/github/webhook`, and a secret that matches `GITHUB_WEBHOOK_SECRET` |
| **Subscribe to events** | Pull request, Issues, Push, Workflow run, Check run (installation events are always sent) |

### Prerequisites
- Install the GitHub App on your account or organization (the **Login with GitHub** button sends you there if you haven't).
- Set the GitHub App's ID, name, private key, Client ID and Client secret in the environment variables.

## Project Structure

```
run.py                        # Entry point: creates the app via the factory
app/
  __init__.py                 # create_app() application factory
  config/                     # BaseConfig + Development / Production / Testing configs
  routes/                     # HTTP routes, one module per feature (all on the "main" blueprint)
    auth_routes.py            #   home, sign-in with GitHub, App install/setup, logout
    repo_routes.py            #   repository list, details, bulk delete
    issue_routes.py           #   issues
    pull_request_routes.py    #   pull requests
    branch_routes.py          #   branches
    content_routes.py         #   repository contents and files
    bulk_routes.py            #   bulk repository actions
    cleanup_routes.py         #   cleanup dashboard and branch cleanup
    inbox_routes.py           #   cross-repository issue & PR inbox
    security_routes.py        #   security alerts across repositories
    collaborator_routes.py    #   collaborators, invitations and teams
    repo_creation_routes.py   #   create repositories
  controllers/                # GitHub REST API calls (auth, repos, issues, pull requests)
  templates/                  # Jinja templates
  static/                     # CSS, JS, images
tests/                        # pytest suite
```

## Setting Up the Project Locally

1. **Clone the repository:**
   ```bash
   git clone <repository_url>
   cd RepoMaster
   ```

2. **Create and activate a virtual environment:**
   ```bash
   python -m venv venv
   venv\Scripts\activate        # Windows
   source venv/bin/activate     # Linux / macOS
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements-dev.txt   # app + test dependencies
   ```

4. **Configure environment variables:** copy `.env.default` to `.env` and fill it in.

   | Variable | Description |
   |---|---|
   | `FLASK_CONFIG` | `development` (default), `production` or `testing` |
   | `SECRET_KEY` | Flask session secret. Required in production |
   | `GITHUB_APP_ID` | Your GitHub App's ID |
   | `GITHUB_APP_NAME` | Your GitHub App's URL slug (used for the install link) |
   | `GITHUB_PRIVATE_KEY_PATH` | Path to the GitHub App's `.pem` private key |
   | `GITHUB_CLIENT_ID` | The GitHub App's Client ID (for user sign-in) |
   | `GITHUB_CLIENT_SECRET` | A Client secret generated on the GitHub App |
   | `GITHUB_OAUTH_CALLBACK_URL` | Optional. Exact callback URL; set it when running behind a reverse proxy so it matches the App's Callback URL |
   | `GITHUB_WEBHOOK_SECRET` | The secret set on the App's webhook. Webhook deliveries are refused until it's set |
   | `DATABASE_PATH` | Optional. Where the SQLite database is stored (default `instance/repomaster.db`) |

5. **Run the application:**
   ```bash
   python run.py
   ```
   Then open http://127.0.0.1:5000/.

6. **Run the tests:**
   ```bash
   pytest
   ```

### Deploying

Point your WSGI server at `run:app` (e.g. `gunicorn run:app`) and set `FLASK_CONFIG=production`.
The production config refuses to start if `SECRET_KEY` or any GitHub App setting (including the Client ID and secret) is missing.


### Production Version

As we continue development, you can find the latest production version of the app [here](https://repomaster.tgkcapture.online/).

Feel free to explore and provide feedback!


## Contributors

- [@Tawonga Grant Kanyenda](https://github.com/TgkCapture)