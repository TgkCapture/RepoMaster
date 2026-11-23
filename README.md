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

### Update a File(Buggy)
- **API Endpoint:** `PUT /repos/{owner}/{repo}/contents/{path}`  
- **Functionality:** Modify the content of an existing file.

### Delete a File
**API Endpoint:** `DELETE /repos/{owner}/{repo}/contents/{path}`  
- **Functionality:** Remove a file from the repository.

## Migration to GitHub App
RepoMaster now uses a GitHub App for authentication and repository management, providing enhanced security and scalability:
- **Authentication:** The app uses a GitHub App installation access token for API interactions.
- **Benefits:** Fine-grained permissions, easier token management, and enhanced security.

### Prerequisites
- Install the GitHub App on your account or organization.
- Set up the GitHub App’s private key and ID in the environment variables.

## Project Structure

```
run.py                        # Entry point: creates the app via the factory
app/
  __init__.py                 # create_app() application factory
  config/                     # BaseConfig + Development / Production / Testing configs
  routes/                     # HTTP routes, one module per feature (all on the "main" blueprint)
    auth_routes.py            #   home, GitHub App install/authorize, logout
    repo_routes.py            #   repository list, details, bulk delete
    issue_routes.py           #   issues
    pull_request_routes.py    #   pull requests
    branch_routes.py          #   branches
    content_routes.py         #   repository contents and files
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
The production config refuses to start if `SECRET_KEY` or any GitHub App setting is missing.


### Production Version

As we continue development, you can find the latest production version of the app [here](https://repomaster.tgkcapture.online/).

Feel free to explore and provide feedback!


## Contributors

- [@Tawonga Grant Kanyenda](https://github.com/TgkCapture)