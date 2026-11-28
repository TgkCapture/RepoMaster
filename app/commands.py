"""commands.py

Command-line jobs (`flask --app run <command>`).

run-scheduled-deletions  Delete repositories whose soft-delete grace period is over
                         (issue #51). Run it regularly, e.g. hourly from cron:
                         0 * * * *  cd /path/to/RepoMaster && flask --app run run-scheduled-deletions
"""
import click


def register_commands(app):
    @app.cli.command('run-scheduled-deletions')
    def run_scheduled_deletions():
        """Delete repositories whose grace period is over."""
        from app.controllers.auth_controller import get_installation_access_token
        from app.controllers.soft_delete_controller import run_due_deletions

        results = run_due_deletions(get_installation_access_token)
        for repo, status, message in results:
            click.echo(f"{repo}: {status} ({message})")
        click.echo(f"{len(results)} scheduled deletion(s) processed.")
