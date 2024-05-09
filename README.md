# RepoMaster

RepoMaster is a Flask-based web application designed to interact with the GitHub API, providing essential repository management functionalities.

## Functionalities (Under Development)

### 1. View Repositories

- **Route:** `/repositories`
- **Functionality:** Fetches a list of repositories from a GitHub user or organization.
- **Implementation Steps:**
  - Utilizes the GitHub API to retrieve repository data.
  - Displays fetched repositories in a user-friendly format on a webpage.

### 2. Manage Issues

- **Route:** `/repositories/<repo_name>/issues`
- **Functionality:** Enables viewing, creation, closure, or management of issues for a specific repository.
- **Implementation Steps:**
  - Implements endpoints to retrieve issues for a selected repository.
  - Allows users to create new issues, close existing ones, or perform other basic issue management tasks.

### 3. Delete Repositories

- **Route:** `/delete_repo`
- **Functionality:** Allows users to select and delete multiple repositories.
- **Implementation Steps:**
  - Creates a page where users can see a list of repositories and select those for deletion.
  - Implements a confirmation mechanism before proceeding with the deletion.

## Future Development

These functionalities represent only the initial set of features in RepoMaster. I encourage contributors to expand and enhance the application by implementing additional functionalities such as pull request management, user authentication, or any other GitHub-related features. Feel free to fork this repository and submit pull requests with your improvements!

Your contributions are greatly appreciated! 🚀

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
    set GITHUB_USERNAME=your_github_username
    set GITHUB_TOKEN=your_github_token

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
    export GITHUB_USERNAME=your_github_username
    export GITHUB_TOKEN=your_github_token

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