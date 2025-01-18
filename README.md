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
  

# Upcoming Features (Under Development)

## Branch and Tag Management

### Get Repository Contents
**API Endpoint:** `GET /repos/{owner}/{repo}/contents/{path}`  
Retrieve the content of a file or directory.

---

### Create a File
**API Endpoint:** `PUT /repos/{owner}/{repo}/contents/{path}`  
Add a new file to the repository.

---

### Update a File
**API Endpoint:** `PUT /repos/{owner}/{repo}/contents/{path}`  
Modify the content of an existing file.

---

### Delete a File
**API Endpoint:** `DELETE /repos/{owner}/{repo}/contents/{path}`  
Remove a file from the repository.

---

### Create a Branch
**API Endpoint:** `POST /repos/{owner}/{repo}/git/refs`  
Create a new branch from an existing reference.

---

### Delete a Branch
**API Endpoint:** `DELETE /repos/{owner}/{repo}/git/refs/heads/{branch}`  
Remove a branch permanently.

---

### Get Branch Details
**API Endpoint:** `GET /repos/{owner}/{repo}/branches/{branch}`  
Fetch details about a specific branch, including protection rules.

---

### List All Branches
**API Endpoint:** `GET /repos/{owner}/{repo}/branches`  
Retrieve a list of all branches in a repository.

---

### Rename a Branch
**API Endpoint:** `POST /repos/{owner}/{repo}/branches/{branch}/rename`  
Rename a branch.


## Migration to GitHub App
RepoMaster now uses a GitHub App for authentication and repository management, providing enhanced security and scalability:
- **Authentication:** The app uses a GitHub App installation access token for API interactions.
- **Benefits:** Fine-grained permissions, easier token management, and enhanced security.

### Prerequisites
- Install the GitHub App on your account or organization.
- Set up the GitHub App’s private key and ID in the environment variables.

## Setting Up the Project Locally

### For Windows:
1. **Clone the Repository:**
   ```bash
   git clone <repository_url>
   cd RepoMaster

2. **Set Up Python Virtual Environment:**
    ```bash
      python -m venv venv
      venv\Scripts\activate

3. **Install Dependencies:**
    ```bash
    pip install -r requirements.txt

4. **Set Environment Variables:**
    ```bash
    set GITHUB_APP_ID=your_github_app_id
    set GITHUB_PRIVATE_KEY_PATH=path_to_your_private_key.pem

5. **Run the Flask Application:**
    ```bash
    python run.py

6. **Access the Application:**
Open a web browser and visit http://127.0.0.1:5000/ to access the application.


### For Linux 

1. **Clone the Repository:**
   ```bash
   git clone <repository_url>
   cd RepoMaster

2. **Set Up Python Virtual Environment:**
    ```bash
    python -m venv venv
    source venv/bin/activate

3. **Install Dependencies:**
    ```bash 
      pip install -r requirements.txt

4. **Set Environment Variables:**
    ```bash
  export GITHUB_APP_ID=your_github_app_id
  export GITHUB_PRIVATE_KEY_PATH=path_to_your_private_key.pem

5. **Run the Flask Application:**
    ```bash
    python app.py

6. **Access the Application:**
Open a web browser and visit http://127.0.0.1:5000/ to access the application.


### Production Version

As we continue development, you can find the latest production version of the app [here](https://repomaster.tgkcapture.online/).

Feel free to explore and provide feedback!


## Contributors

- [@Tawonga Grant Kanyenda](https://github.com/TgkCapture)