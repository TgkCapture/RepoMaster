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
- **Route:** `/repositories/<repo_name>/issues`
- **Functionality:** Enables viewing, creation, closure, or management of issues for a specific repository.
- **Planned Features:**
  - Endpoints to retrieve and display issues for a repository.
  - Options to create new issues, close existing ones, or perform other basic issue management tasks.

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

### 4. Manage Pull Requests (Available)
- **Route:** `/repositories/<repo_name>/pull_requests`
- **Functionality:** Enables viewing, creation, merging, or management of pull requests for a specific repository.  

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